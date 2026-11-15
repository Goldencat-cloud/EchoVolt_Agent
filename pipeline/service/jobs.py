"""In-memory async job store with phase-level progress events.

Serves two purposes: lightweight progress hints for the UI ("理解问题中…")
and an observability surface for monitoring/evaluation — every phase
transition and the final outcome (including failures) is recorded.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
MAX_JOBS = 200
MAX_ACTIVE_JOBS = 2
JOB_TTL_SECONDS = 3600.0
# D5：待审/澄清中的 job 属"等用户"状态——TTL 延长（6h，演示场景一节课/半天
# 量级），且不计入执行名额；全局待审上限约束 checkpointer 内存占用。
PENDING_TTL_SECONDS = 6 * 3600.0
MAX_PENDING_JOBS = 10
PENDING_STATUSES = ("awaiting_review", "clarifying")


def create_job(question: str, brief: dict[str, Any] | None = None,
               session_id: str | None = None) -> str | None:
    # The id is a temporary bearer token for polling a report result.
    job_id = uuid.uuid4().hex
    with _LOCK:
        active = sum(1 for job in _JOBS.values() if job["status"] == "running")
        if active >= MAX_ACTIVE_JOBS:
            return None
        pending = [job for job in _JOBS.values() if job["status"] in PENDING_STATUSES]
        if len(pending) >= MAX_PENDING_JOBS:
            return None
        if session_id and any(job.get("session_id") == session_id for job in pending):
            return None  # D5：每会话单待审 job，先完成当前审查
        # evict expired/oldest when over budget
        if len(_JOBS) >= MAX_JOBS:
            completed = sorted((key for key, job in _JOBS.items()
                                if job["status"] != "running"),
                               key=lambda key: _JOBS[key]["created_at"])
            to_remove = len(_JOBS) - MAX_JOBS + 1
            if len(completed) < to_remove:
                return None
            for key in completed[:to_remove]:
                _JOBS.pop(key, None)
        _JOBS[job_id] = {"job_id": job_id, "question": question, "status": "running",
                         "phase": "澄清中", "events": [{"phase": "澄清中",
                                                        "ts": time.time()}],
                         "brief": brief, "session_id": session_id,
                         "result": None, "error": None, "created_at": time.time()}
    return job_id


def set_phase(job_id: str, phase: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["phase"] = phase
        job["events"].append({"phase": phase, "ts": time.time()})


def finish_ok(job_id: str, result: dict[str, Any]) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["status"] = "done"
        job["phase"] = "已完成"
        job["result"] = result
        job["events"].append({"phase": "已完成", "ts": time.time()})


def finish_error(job_id: str, error: dict[str, Any]) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["status"] = "failed"
        job["phase"] = "失败"
        job["error"] = error
        job["events"].append({"phase": "失败", "ts": time.time()})


def pause_for_review(job_id: str, outline: dict[str, Any]) -> None:
    """Job paused at the outline gate (D4/D9): waiting for the user, not running.

    An awaiting job does not count against MAX_ACTIVE_JOBS (see create_job) —
    it occupies no execution slot while the graph is suspended in the
    checkpointer.
    """
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["status"] = "awaiting_review"
        job["phase"] = "待大纲审查"
        job["outline"] = outline
        job.setdefault("outline_history", []).append(outline)
        job["events"].append({"phase": "待大纲审查", "ts": time.time()})


def pause_for_clarify(job_id: str, questions: list[dict[str, Any]]) -> None:
    """Job waiting for clarification answers (D10): status `clarifying`."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["status"] = "clarifying"
        job["phase"] = "澄清中"
        job["clarify_questions"] = questions
        job["events"].append({"phase": "澄清中", "ts": time.time()})


def record_clarification(job_id: str, answer: dict[str, Any],
                         questions: list[dict[str, Any]] | None) -> None:
    """Store one clarification round; `questions` replaces the open list."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job.setdefault("clarifications", []).append(answer)
        if questions is not None:
            job["clarify_questions"] = questions
        job["events"].append({"phase": "澄清中", "ts": time.time()})


def claim_for_run(job_id: str, phase: str = "数据探索中") -> bool:
    """Atomically transition clarifying → running (start/continue agent run)."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None or job["status"] != "clarifying":
            return False
        job["status"] = "running"
        job["phase"] = phase
        job["events"].append({"phase": phase, "ts": time.time()})
        return True


def pending_exists_for(session_id: str) -> bool:
    """True when the session already has a waiting (clarifying/review) job (D5)."""
    with _LOCK:
        return any(job.get("session_id") == session_id
                   for job in _JOBS.values() if job["status"] in PENDING_STATUSES)


def claim_for_resume(job_id: str, phase: str = "编写分析代码中") -> bool:
    """Atomically transition awaiting_review → running (guards double resume)."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None or job["status"] != "awaiting_review":
            return False
        job["status"] = "running"
        job["phase"] = phase
        job["events"].append({"phase": phase, "ts": time.time()})
        return True


def record_regenerate(job_id: str) -> int:
    """Count one outline regenerate (reject→redraft) cycle; returns new count."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return 0
        job["regenerates"] = int(job.get("regenerates", 0)) + 1
        return job["regenerates"]


def record_delivery_spec(job_id: str, spec: dict[str, Any]) -> None:
    """Store the optional 重点/受众 delivery spec carried with confirm/edit (D12)."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["delivery_spec"] = spec


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return None
        return json_copy(job)


def json_copy(job: dict[str, Any]) -> dict[str, Any]:
    # Never echo the submitted question or internal timestamps from the public
    # polling endpoint. The browser needs only progress and the completed result.
    visible = {k: v for k, v in job.items() if k not in {"question", "created_at"}}
    return {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
            for k, v in visible.items()}


def run_async(job_id: str, work: Callable[[Callable[[str], None]], dict[str, Any]]) -> None:
    """Run `work(set_phase)` in a background thread; record outcome."""

    def target() -> None:
        try:
            result = work(lambda phase: set_phase(job_id, phase))
            finish_ok(job_id, result)
        except Exception as exc:  # failures must surface, never be swallowed
            finish_error(job_id, {"error": f"{type(exc).__name__}: {exc}"})

    threading.Thread(target=target, daemon=True).start()


def cleanup() -> None:
    """Drop finished jobs past JOB_TTL; waiting jobs past the longer PENDING_TTL (D5)."""
    now = time.time()
    terminal_cutoff = now - JOB_TTL_SECONDS
    pending_cutoff = now - PENDING_TTL_SECONDS
    with _LOCK:
        for key in [k for k, v in _JOBS.items()
                    if (v["status"] not in PENDING_STATUSES and v["status"] != "running"
                        and v["created_at"] < terminal_cutoff)
                    or (v["status"] in PENDING_STATUSES
                        and v["created_at"] < pending_cutoff)]:
            _JOBS.pop(key, None)
