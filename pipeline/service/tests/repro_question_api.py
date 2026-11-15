"""Repro: POST the screenshot's message to /api/question and record what happens.

采集事实：HTTP 状态、耗时、响应体头部、服务端日志中的 agent_failure 事件。
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

QUESTION = "发起深度分析：su7从22-26年的一个需求变化趋势图"


def main() -> int:
    from app import Handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    base = f"http://127.0.0.1:{srv.server_port}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        body = json.dumps({"question": QUESTION, "session_id": "repro-bug"}).encode()
        req = urllib.request.Request(base + "/api/question", data=body,
                                     headers={"Content-Type": "application/json"})
        started = time.time()
        try:
            with urllib.request.urlopen(req, timeout=420) as resp:
                status, payload = resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            status, payload = exc.code, exc.read().decode("utf-8", "replace")
        elapsed = round(time.time() - started, 1)
        print(f"[repro] status={status} elapsed={elapsed}s", flush=True)
        print(f"[repro] body_head={payload[:500]}", flush=True)
        try:
            data = json.loads(payload)
            answer = str(data.get("answer") or data.get("message") or "")
            print(f"[repro] answer_head={answer[:400]}", flush=True)
        except json.JSONDecodeError:
            print("[repro] NON-JSON RESPONSE（前端 r.json() 会抛异常 → 通用 catch 文案）", flush=True)
        return 0
    finally:
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
