"""Generic E2E diagnostic probe: run ONE question to a terminal state and dump the record.

用法：python tests/e2e_question_probe.py "<question>" [out_prefix]
只采集事实（timeline/status/error/report_id/report.md），不做场景判定。
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from e2e_user_sim import _run_job  # noqa: E402


def main(argv: list[str]) -> int:
    question = argv[0]
    prefix = argv[1] if len(argv) > 1 else "question"
    from app import Handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    base = f"http://127.0.0.1:{srv.server_port}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out_dir = Path(__file__).resolve().parents[1] / "data" / "e2e-runs" / time.strftime(f"%Y%m%d-%H%M%S-{prefix}")
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        print(f"[probe] server={base} question={question}", flush=True)
        record = _run_job(base, question, max_wait=600.0)
        (out_dir / "run.json").write_text(
            json.dumps(record, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
        status = record.get("final_status") or record.get("fatal") or "unknown"
        print(f"[probe] status={status} wall={record.get('wall_s')}s", flush=True)
        print("[probe] timeline=" + json.dumps(record.get("timeline"), ensure_ascii=False), flush=True)
        if record.get("error"):
            print("[probe] error=" + str(record["error"])[:2000], flush=True)
        result = record.get("result") or {}
        if result.get("report_id"):
            print(f"[probe] report_id={result['report_id']}", flush=True)
        charts = result.get("charts") or []
        print(f"[probe] charts={len(charts)} "
              + json.dumps([c.get("title", "")[:20] for c in charts], ensure_ascii=False),
              flush=True)
        if len(argv) > 2 and argv[2] == "charts":
            ok_charts = len(charts) >= 1 and all("<svg" in c.get("svg", "") for c in charts)
            print(f"[probe] charts_expectation={'PASS' if ok_charts else 'FAIL'}", flush=True)
            if not ok_charts:
                status = "failed:charts_expectation"
        report = str(result.get("report_md") or "")
        if report:
            (out_dir / "report.md").write_text(report, encoding="utf-8")
            print(f"[probe] report_chars={len(report)}", flush=True)
        print(f"[probe] artifacts: {out_dir}", flush=True)
        return 0 if status == "done" else 1
    finally:
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
