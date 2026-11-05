"""One local worker and a bounded in-process queue; durable state lives in SQLite."""
from __future__ import annotations

import json
import queue
import threading

from .collect.runner import run_collection
from .contracts import IngestionError, JobConfig
from .ingest import import_bytes, read_input


class JobService:
    def __init__(self, store, sources=None, allow_network=False, credential_path=None):
        self.store, self.sources, self.allow_network = store, sources or {}, allow_network
        self.credential_path = credential_path
        self.queue = queue.Queue(maxsize=100)
        self.submit_lock = threading.Lock()
        self.store.interrupt_jobs()
        self.worker = threading.Thread(target=self._work, name="ingestion-worker", daemon=True)
        self.worker.start()

    def validate(self, request):
        if not isinstance(request, dict) or set(request) - {"config", "source", "user_ids"}:
            raise IngestionError("invalid_job_request")
        config = JobConfig.parse(request.get("config", {}))
        if config.mode == "collect":
            if not self.allow_network:
                raise IngestionError("server_network_disabled")
            if request.get("source"):
                raise IngestionError("source_not_allowed_for_collection")
        elif config.mode == "import":
            source = request.get("source")
            if not isinstance(source, str) or source not in self.sources:
                raise IngestionError("unregistered_source")
            registered = self.sources[source]
            if config.kind != registered["kind"] or config.series_id != registered.get("series_id", ""):
                raise IngestionError("source_configuration_conflict")
        else:
            raise IngestionError("use_replay_maintenance_command")
        uids = request.get("user_ids", [])
        if not isinstance(uids, list) or len(uids) > 100 or any(not isinstance(x, str) or not x.isdigit() for x in uids):
            raise IngestionError("invalid_user_ids")
        return config

    def submit(self, key, request):
        self.validate(request)
        with self.submit_lock:
            if self.queue.full():
                raise IngestionError("queue_full")
            jid, created = self.store.create_job(key, request)
            if created:
                self.queue.put_nowait(jid)
        return self.status(jid)

    def status(self, jid):
        row = self.store.job(jid)
        result = json.loads(row["result_json"]) if row["result_json"] else None
        return {"job_id": jid, "state": row["state"], "created_at": row["created_at"],
                "updated_at": row["updated_at"], "result": result, "error_code": row["error_code"]}

    def action(self, jid, action):
        if action == "resume":
            row = self.store.job(jid)
            self.validate(json.loads(row["request_json"]))
            if self.queue.full():
                raise IngestionError("queue_full")
        self.store.job_action(jid, action)
        if action == "resume":
            self.queue.put_nowait(jid)
        return self.status(jid)

    def _work(self):
        while True:
            jid = self.queue.get()
            try:
                if jid is None:
                    return
                if self.store.job(jid)["state"] != "pending":
                    continue
                self.store.update_job(jid, "running")
                request = json.loads(self.store.job(jid)["request_json"])
                config = self.validate(request)
                cancelled = lambda: bool(self.store.job(jid)["cancel_requested"])
                if config.mode == "import":
                    source = self.sources[request["source"]]
                    content, provenance = read_input(source["path"], source.get("member"))
                    result = import_bytes(self.store, content, config.kind, provenance,
                                          series_id=config.series_id, retrieved_at=source.get("retrieved_at"), cancelled=cancelled,run_id=jid)
                    state = result.get('status','succeeded')
                else:
                    result = run_collection(self.store, config, user_ids=request.get("user_ids", []), cancelled=cancelled,run_id=jid,credential_path=self.credential_path)
                    state = result["status"]
                if cancelled():
                    state = "cancelled"
                self.store.update_job(jid, state, result=result, run_id=result["run_id"])
            except Exception as error:
                code = error.code if isinstance(error, IngestionError) else "internal_processing_error"
                self.store.update_job(jid, "cancelled" if code == "cancelled" else "failed", error=code)
            finally:
                self.queue.task_done()

    def close(self):
        # Finish/cancel the current bounded request before closing the database.
        with self.store.transaction() as db:
            db.execute("UPDATE collection_runs SET cancel_requested=1,state=CASE WHEN state='pending' THEN 'cancelled' ELSE state END WHERE state IN ('running','pending','cancelling')")
        self.queue.put(None)
        self.worker.join()
