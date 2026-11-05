"""E2E probe: a question that forces the agent to write its own code (auto-033 复查后验证).

问题设计：加权平均 vs 简单平均的组合统计，白名单方法不直接提供，
计划须 use_python=true 且 Agent 须用 python_analyze 完成计算。
判定：终态 done；已保存 provenance 含 kind=python 的已验证步骤；
报告含加权整体占比（0~1 之间或百分比形式）与简单平均的对比表述。
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from e2e_user_sim import _report_of, _run_job  # noqa: E402

QUESTION = ("SU7 各议题的负面观点占比差异很大。请以各议题的观点条数为权重，"
            "计算全量口径下的整体负面观点占比（加权平均），并与各议题占比的简单平均值比较，"
            "给出两者数值与差异，说明哪个更能代表整体。这个组合统计白名单方法不直接提供，"
            "需要你按计划授权自己写代码计算。")

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?")


def main() -> int:
    from app import Handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    base = f"http://127.0.0.1:{srv.server_port}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out_dir = Path(__file__).resolve().parents[1] / "data" / "e2e-runs" / time.strftime("%Y%m%d-%H%M%S-code")
    out_dir.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    ok = True
    try:
        print(f"[code-probe] server={base}", flush=True)
        record = _run_job(base, QUESTION, max_wait=600.0)
        (out_dir / "run.json").write_text(
            json.dumps(record, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
        status = record.get("final_status") or record.get("fatal") or "unknown"
        print(f"[code-probe] status={status} wall={record.get('wall_s')}s", flush=True)
        print("[code-probe] timeline=" + json.dumps(record.get("timeline"), ensure_ascii=False),
              flush=True)
        report = _report_of(record)
        (out_dir / "report.md").write_text(report, encoding="utf-8")

        def require(cond: bool, msg: str) -> None:
            nonlocal ok
            ok = ok and cond
            notes.append(("ok: " if cond else "FAIL: ") + msg)

        require(status == "done", f"终态 done（实际 {status}）")
        if record.get("error"):
            print("[code-probe] error=" + str(record["error"])[:800], flush=True)
        # 找到本次保存的报告目录，检查 provenance 中是否有已验证的 python 步骤
        report_id = (record.get("result") or {}).get("report_id") or ""
        provenance: dict = {}
        if report_id:
            prov_path = Path(__file__).resolve().parents[1] / "reports" / "agent" / report_id / "provenance.json"
            if prov_path.is_file():
                provenance = json.loads(prov_path.read_text(encoding="utf-8"))
        py_steps = [s for s in provenance.get("verified_steps", [])
                    if s.get("kind") == "python" and (s.get("result") or {}).get("ok")]
        require(bool(py_steps), "provenance 含已验证成功的 python 代码步骤"
                 f"（实际 {len(py_steps)} 个）")
        if py_steps:
            code_chars = sum(len(str(s.get("code") or "")) for s in py_steps)
            print(f"[code-probe] python_steps={len(py_steps)} code_chars={code_chars}", flush=True)
        # 报告应包含加权整体占比与简单平均的对比（两个不同的百分数/小数）
        nums = [n for n in NUMBER_RE.findall(report)]
        require(len(nums) >= 4, f"报告含足够数字支撑对比（实际 {len(nums)} 个数字）")
        contrast = any(k in report for k in ("加权", "简单平均", "整体"))
        require(contrast, "报告出现加权/简单平均/整体的对比表述")
        py_codes = [str(s.get("code") or "") for s in py_steps]
        print("[code-probe] code_head=" + (py_codes[0][:300].replace("\n", "\\n") if py_codes else "-"),
              flush=True)
    finally:
        srv.shutdown()
    print("\n===== VERDICT =====")
    for note in notes:
        print("  " + note)
    print(f"[code-probe] artifacts: {out_dir}")
    (out_dir / "verdict.json").write_text(json.dumps(
        {"ok": ok, "notes": notes}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
