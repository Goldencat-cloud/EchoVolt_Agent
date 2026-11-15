"""E2E design probe: drive the deep-analysis pipeline over HTTP with real LLM.

Enables LangSmith tracing (keys read from d:/Desktop/Projects/deep_agents_action/.env,
never printed), runs several representative questions end to end, auto-answers
clarification, auto-confirms the outline gate, and records the full status
timeline + plan + metrics + report for later design analysis.

Usage: python tests/e2e_design_probe.py [scenario ...]
Artifacts: data/e2e-runs/<timestamp>/run-<name>.json (+ summary.json)
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
try:  # Windows console may default to cp936/cp1252; artifacts are UTF-8 anyway
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

KEY_FILE = Path(r"d:\Desktop\Projects\deep_agents_action\.env")


def _load_langsmith() -> dict[str, str]:
    """Read LangSmith settings from the external .env and export to os.environ."""
    values: dict[str, str] = {}
    if not KEY_FILE.is_file():
        return values
    for line in KEY_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if name.startswith("LANGSMITH") and value:
            values[name] = value
    if values.get("LANGSMITH_API_KEY"):
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGSMITH_API_KEY"] = values["LANGSMITH_API_KEY"]
        os.environ["LANGSMITH_PROJECT"] = values.get(
            "LANGSMITH_PROJECT") or f"autoinsight-e2e-{time.strftime('%Y%m%d')}"
        os.environ["LANGCHAIN_PROJECT"] = os.environ["LANGSMITH_PROJECT"]
    return values


LS = _load_langsmith()

import app  # noqa: E402  (after tracing env is set)
import jobs  # noqa: E402


def _request(url: str, payload: dict | None = None, timeout: float = 120.0) -> tuple[int, dict]:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body or "{}")
        except ValueError:
            return exc.code, {"raw": body[:800]}


def _clarify_answer(questions: list[dict]) -> tuple[str, str]:
    """Compose one specific answer covering every asked clarification."""
    parts: list[str] = []
    field = "other"
    for question in questions:
        if question.get("field"):
            field = question["field"]
        options = question.get("options") or []
        labels = [o.get("label") if isinstance(o, dict) else str(o) for o in options]
        labels = [str(x) for x in labels if x]
        if labels:
            parts.append("选择：" + "、".join(labels[:2]))
    if not parts:
        parts.append("覆盖公共快充与家充场景，限中国地区车主真实体验，"
                     "按现有议题分类统计频次与占比即可，全文共 3 条原文佐证并附链接。")
    return "；".join(parts)[:800], field


def _brief_for(name: str) -> dict | None:
    if name != "detail":
        return None
    import task_brief
    options = task_brief.form_options()
    window = next((w for w in options["time_windows"] if w["key"] == "all"), None)
    if window is None:
        return None
    return {"topic": "充电与补能", "brand": "小米", "compare": None,
            "time_window": f"{window['start']} ~ {window['end']}"}


SCENARIOS = {
    "detail": "SU7 充电补能体验的负面反馈集中在哪些议题？请给出 3 条原文佐证。",
    "vague": "分析一下 SU7 怎么样",
    "compare": "充电补能和空间舒适性相比，哪个议题的负面反馈更多？",
    "trap": "用数据证明 SU7 是同级别加速最快的车",
}


def run_scenario(name: str, question: str, base: str, out_dir: Path,
                 max_wait: float = 600.0) -> dict:
    started = time.time()
    code, payload = _request(base + "/api/agent/report",
                             {"question": question, "brief": _brief_for(name)})
    record: dict = {"scenario": name, "question": question, "start_http": code,
                    "start_payload": payload, "timeline": [], "clarify_count": 0,
                    "outline": None, "regenerate_used": 0}
    if code != 202:
        record["fatal"] = "start_failed"
        (out_dir / f"run-{name}.json").write_text(
            json.dumps(record, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
        return record
    job_id = payload["job_id"]
    record["job_id"] = job_id
    last = None
    answered_sig: str | None = None
    while True:
        time.sleep(3)
        elapsed = time.time() - started
        if elapsed > max_wait:
            record["fatal"] = "timeout"
            break
        code, job = _request(f"{base}/api/agent/report/{job_id}")
        signature = (job.get("status"), job.get("phase"))
        if signature != last:
            record["timeline"].append({"t": round(elapsed, 1), "status": job.get("status"),
                                       "phase": job.get("phase")})
            last = signature
        status = job.get("status")
        if status == "clarifying":
            questions = job.get("clarify_questions") or []
            record.setdefault("clarify_questions", questions)
            sig = json.dumps([q.get("question") for q in questions], ensure_ascii=False)
            if sig == answered_sig:
                continue  # 重评估未完成，等下一轮轮询，避免重复作答
            answered_sig = sig
            if record["clarify_count"] < 4:
                answer, field = _clarify_answer(questions)
                code, resp = _request(f"{base}/api/agent/report/{job_id}/clarify",
                                      {"answer": answer, "field": field})
                record["clarify_count"] += 1
                record.setdefault("clarify_responses", []).append(
                    {"http": code, "answer": answer, "field": field})
            else:
                record["fatal"] = "clarify_loop_no_cap"
                break
            continue
        if status == "awaiting_review":
            record["outline"] = {"outline": job.get("outline"),
                                 "plan": job.get("plan"),
                                 "history_len": len(job.get("outline_history") or [])}
            decision: dict = {"action": "confirm"}
            if name == "detail":
                decision.update({"focus": "充电排队与补能", "audience": "售后负责人"})
            code, resp = _request(f"{base}/api/agent/report/{job_id}/outline", decision)
            record.setdefault("outline_decisions", []).append({"http": code, "body": decision,
                                                               "resp": resp})
            if code != 202:
                record["fatal"] = f"outline_http_{code}"
                break
            continue
        if status in ("done", "failed"):
            record["final_status"] = status
            record["result"] = job.get("result")
            record["error"] = job.get("error")
            record["job"] = {k: v for k, v in job.items()
                             if k in ("status", "phase", "regenerates", "delivery_spec")}
            break
    record["wall_s"] = round(time.time() - started, 1)
    (out_dir / f"run-{name}.json").write_text(
        json.dumps(record, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
    return record


def _summary(records: list[dict]) -> dict:
    rows = []
    for record in records:
        result = record.get("result") or {}
        metrics = result.get("metrics") or {}
        rows.append({
            "scenario": record["scenario"],
            "status": record.get("final_status") or record.get("fatal") or "unknown",
            "wall_s": record.get("wall_s"),
            "clarify": record.get("clarify_count"),
            "outline_steps": len((record.get("outline") or {}).get("outline") or []),
            "regenerates": (record.get("job") or {}).get("regenerates"),
            "tool_calls": metrics.get("successful_tool_calls"),
            "tool_errors": metrics.get("tool_errors"),
            "code_failures": metrics.get("code_failures"),
            "gate_rejections": metrics.get("gate_rejections"),
            "elapsed_ms": result.get("elapsed_ms"),
            "error": record.get("error"),
        })
    return {"langsmith_project": os.environ.get("LANGSMITH_PROJECT", "(off)"),
            "tracing": bool(os.environ.get("LANGSMITH_API_KEY")), "runs": rows}


def main(argv: list[str]) -> int:
    names = [n for n in argv if n in SCENARIOS] or list(SCENARIOS)
    out_dir = HERE / "data" / "e2e-runs" / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    server.daemon_threads = True
    base = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[e2e] server={base} project={os.environ.get('LANGSMITH_PROJECT')} "
          f"tracing={bool(os.environ.get('LANGSMITH_API_KEY'))}", flush=True)
    records = []
    try:
        for name in names:
            print(f"[e2e] ---- scenario {name} ----", flush=True)
            record = run_scenario(name, SCENARIOS[name], base, out_dir)
            records.append(record)
            print(f"[e2e] {name}: status={record.get('final_status') or record.get('fatal')} "
                  f"wall={record.get('wall_s')}s clarify={record.get('clarify_count')}",
                  flush=True)
    finally:
        server.shutdown()
    summary = _summary(records)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)
    print(f"[e2e] artifacts: {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

