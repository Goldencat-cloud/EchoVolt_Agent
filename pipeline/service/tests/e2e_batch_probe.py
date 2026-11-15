"""批量端到端探针：连续跑多个问题，逐个落盘并汇总稳定性指标。

复用 e2e_medium_probe 的单次流程（进程内真实服务 + 真实模型 + 自动澄清/确认大纲），
每个问题单独一个 job，产物写到 data/e2e-runs/<时间戳>-batch/。
用法：python tests/e2e_batch_probe.py
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import app  # noqa: E402
from e2e_medium_probe import run as probe_run  # noqa: E402

QUESTIONS = [
    ("baseline-repeat", "SU7在充电补能上的负面反馈占比是多少？主要集中什么问题？给2条车主原话。"),
    ("cross-aspect", "SU7在智能座舱和空间舒适性上，哪个负面占比更高？用柱状图展示主要议题的负面占比排序。"),
    ("trend", "SU7的负面反馈随时间怎么变化？哪几个月的负面观点最集中？"),
    ("ownership", "车主和潜在用户的负面关注点有什么差异？分别给1条有代表性的原话。"),
]


def summarise(name: str, record: dict) -> dict:
    result = record.get("result") or {}
    metrics = result.get("metrics") or {}
    return {
        "name": name,
        "question": record.get("question"),
        "status": record.get("final_status") or record.get("fatal"),
        "wall_s": record.get("wall_s"),
        "clarify": record.get("clarify_count"),
        "tools": metrics.get("successful_tool_calls"),
        "tool_errors": metrics.get("tool_errors"),
        "code_failures": metrics.get("code_failures"),
        "submit_attempts": metrics.get("submit_attempts"),
        "gate_rejections": metrics.get("gate_rejections"),
        "report_chars": len(result.get("report_md") or ""),
        "evidence": len(result.get("evidence_index") or []),
        "charts": len(result.get("charts") or []),
        "error": str(result.get("error") or record.get("error") or "")[:220] or None,
    }


def main() -> int:
    selected = [item for item in QUESTIONS
                if len(sys.argv) == 1 or item[0] in sys.argv[1:]]
    if not selected:
        print("[batch] no question selected", flush=True)
        return 2
    out_dir = HERE / "data" / "e2e-runs" / (time.strftime("%Y%m%d-%H%M%S") + "-batch")
    out_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    server.daemon_threads = True
    base = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[batch] server={base} out={out_dir}", flush=True)
    rows = []
    try:
        for index, (name, question) in enumerate(selected, start=1):
            print(f"[batch] ({index}/{len(selected)}) {name} start", flush=True)
            record = probe_run(base, question, max_wait=600.0)
            (out_dir / f"{index:02d}-{name}.json").write_text(
                json.dumps(record, ensure_ascii=False, default=str, indent=1),
                encoding="utf-8")
            row = summarise(name, record)
            rows.append(row)
            print(f"[batch] {row['status']} wall={row['wall_s']} tools={row['tools']} "
                  f"errors={row['tool_errors']} gates={row['gate_rejections']} "
                  f"report={row['report_chars']}", flush=True)
    finally:
        server.shutdown()
    (out_dir / "summary.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for row in rows if row["status"] == "done")
    print(f"[batch] done {ok}/{len(rows)} -> {out_dir / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
