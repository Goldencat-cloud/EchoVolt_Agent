"""One-off e2e probe for a medium-complexity question (skills + semantic layer).

Drives the real pipeline in-process (fresh code, real LLM), auto-answers
clarification, auto-confirms the outline gate, and records the full timeline,
plan, tool log and report so skill usage and semantic-layer behaviour can be
inspected afterwards.

Usage: python tests/e2e_medium_probe.py "<question>"
Artifacts: data/e2e-runs/<timestamp>-medium/run-medium.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from e2e_design_probe import _clarify_answer, _request  # noqa: E402
import app  # noqa: E402
import threading  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

QUESTION = (sys.argv[1] if len(sys.argv) > 1 else
            "SU7 在充电补能和智能座舱这两个议题上，负面反馈占比差多少？"
            "各自最主要的负面集中在什么问题，各给 1 条车主原话。")


def run(base: str, question: str, max_wait: float = 720.0) -> dict:
    record: dict = {"question": question, "timeline": [], "clarify_count": 0,
                    "outline": None, "fatal": None}
    started = time.time()
    code, payload = _request(base + "/api/agent/report", {"question": question})
    record["start_http"] = code
    if code != 202:
        record["fatal"] = "start_failed"
        record["start_payload"] = payload
        return record
    job_id = payload["job_id"]
    record["job_id"] = job_id
    print(f"[probe] job={job_id} http={code}", flush=True)
    last, answered = None, None
    while True:
        time.sleep(3)
        elapsed = time.time() - started
        if elapsed > max_wait:
            record["fatal"] = "timeout"
            break
        code, job = _request(f"{base}/api/agent/report/{job_id}")
        sig = (job.get("status"), job.get("phase"))
        if sig != last:
            record["timeline"].append({"t": round(elapsed, 1), "status": job.get("status"),
                                       "phase": job.get("phase")})
            print(f"[probe] t={elapsed:6.1f}s status={job.get('status')} "
                  f"phase={job.get('phase')}", flush=True)
            last = sig
        status = job.get("status")
        if status == "clarifying":
            questions = job.get("clarify_questions") or []
            record.setdefault("clarify_questions", questions)
            qsig = json.dumps([q.get("question") for q in questions], ensure_ascii=False)
            if qsig == answered:
                continue
            answered = qsig
            print(f"[probe] clarify: {qsig}", flush=True)
            if record["clarify_count"] < 3:
                answer, field = _clarify_answer(questions)
                ccode, _ = _request(f"{base}/api/agent/report/{job_id}/clarify",
                                    {"answer": answer, "field": field})
                record["clarify_count"] += 1
                record.setdefault("clarify_answers", []).append(
                    {"http": ccode, "answer": answer, "field": field})
                print(f"[probe] clarify answered http={ccode}: {answer[:120]}", flush=True)
            else:
                record["fatal"] = "clarify_loop_no_cap"
                break
            continue
        if status == "awaiting_review":
            record["outline"] = {"outline": job.get("outline"),
                                 "plan_json": job.get("plan_json"),
                                 "history_len": len(job.get("outline_history") or [])}
            record.setdefault("outlines", []).append(
                {"t": round(elapsed, 1), "plan_json": job.get("plan_json"),
                 "history_len": len(job.get("outline_history") or [])})
            print("[probe] outline arrived; confirming", flush=True)
            ocode, _ = _request(f"{base}/api/agent/report/{job_id}/outline",
                                {"action": "confirm"})
            record["outline_http"] = ocode
            if ocode != 202:
                record["fatal"] = f"outline_http_{ocode}"
                break
            continue
        if status in ("done", "failed"):
            record["final_status"] = status
            record["result"] = job.get("result")
            record["error"] = job.get("error")
            break
    record["wall_s"] = round(time.time() - started, 1)
    return record


def main() -> int:
    out_dir = HERE / "data" / "e2e-runs" / (time.strftime("%Y%m%d-%H%M%S") + "-medium")
    out_dir.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    srv.daemon_threads = True
    base = f"http://127.0.0.1:{srv.server_port}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"[probe] server={base}", flush=True)
    try:
        record = run(base, QUESTION)
    finally:
        srv.shutdown()
    path = out_dir / "run-medium.json"
    path.write_text(json.dumps(record, ensure_ascii=False, default=str, indent=1),
                    encoding="utf-8")
    result = record.get("result") or {}
    metrics = result.get("metrics") or {}
    print(f"[probe] status={record.get('final_status') or record.get('fatal')} "
          f"wall={record.get('wall_s')}s clarify={record.get('clarify_count')} "
          f"tools={metrics.get('successful_tool_calls')} errors={metrics.get('tool_errors')}",
          flush=True)
    print(f"[probe] artifact: {path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
