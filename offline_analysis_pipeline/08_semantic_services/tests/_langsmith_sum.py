"""Read-only LangSmith probe: aggregate the latest E2E batch (last 40 min)."""
from __future__ import annotations

import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

for line in Path(r"d:\Desktop\Projects\deep_agents_action\.env").read_text(
        encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        name, value = line.split("=", 1)
        if name.strip().startswith("LANGSMITH") and value.strip():
            os.environ[name.strip()] = value.strip().strip('"').strip("'")

from langsmith import Client  # noqa: E402

client = Client()
project = os.environ.get("LANGSMITH_PROJECT") or "deep-agents-action"
since = datetime.now(timezone.utc) - timedelta(minutes=40)
roots = [r for r in client.list_runs(project_name=project, is_root=True, limit=30)
         if r.start_time and r.start_time >= since]
print(f"root_runs={len(roots)}")
for run in roots:
    print(f"ROOT {run.start_time:%H:%M:%S} {str(run.name)[:30]:30s} "
          f"status={run.status} tokens={run.total_tokens} "
          f"latency={((run.end_time - run.start_time).total_seconds() if run.end_time else 0):.0f}s "
          f"err={bool(run.error)}")
sys.exit(0)
runs = [r for r in client.list_runs(project_name=project, limit=100)
        if r.start_time and r.start_time >= since]
llm = [r for r in runs if r.run_type == "llm"]
tools = [r for r in runs if r.run_type == "tool"]
total_tokens = sum(int(r.total_tokens or 0) for r in llm)
prompt_tokens = sum(int((r.prompt_tokens or 0)) for r in llm)
completion_tokens = sum(int((r.completion_tokens or 0)) for r in llm)
latencies = sorted((r.end_time - r.start_time).total_seconds()
                   for r in llm if r.end_time and r.start_time)
errors = [r for r in runs if r.error]
print(f"llm_calls={len(llm)} prompt={prompt_tokens} completion={completion_tokens} "
      f"total={total_tokens}")
if latencies:
    print(f"llm_latency_s p50={latencies[len(latencies)//2]:.1f} "
          f"p90={latencies[int(len(latencies)*0.9)]:.1f} max={latencies[-1]:.1f}")
tool_counter = Counter(str(r.name) for r in tools)
print("tool_calls:", dict(tool_counter))
tool_err = Counter(str(r.name) for r in tools if r.error)
print("tool_errors:", dict(tool_err))
for run in llm:
    if run.error:
        print("LLM ERR:", str(run.error)[:160])
        break
# gate rejections: submit_report tool outputs containing report_gate_failed
gate_first_errors = Counter()
for run in tools:
    if str(run.name) != "submit_report" or run.error:
        continue
    out = json.dumps(run.outputs or {}, ensure_ascii=False)
    if "report_gate_failed" in out:
        for match in ("数据版本", "缺少章节", "未在分析工具结果中找到的数字",
                      "品牌范围", "内部实现词"):
            if match in out:
                gate_first_errors[match] += 1
                break
        else:
            gate_first_errors["other"] += 1
print("gate_rejection_reasons:", dict(gate_first_errors))
