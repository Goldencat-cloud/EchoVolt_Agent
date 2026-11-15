"""Read-only LangSmith probe: dump recent submit_report / gate tool runs."""
from __future__ import annotations

import json
import os
import sys
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
runs = list(client.list_runs(project_name=project, run_type="tool", limit=60,
                             is_root=False))
print(f"tool runs: {len(runs)}")
for run in runs:
    name = str(run.name)
    if name not in ("submit_report", "run_analysis_method", "submit_analysis_plan",
                    "search_claims", "semantic_overview", "python_analyze"):
        continue
    out = run.outputs or {}
    content = ""
    if isinstance(out, dict):
        content = str(out.get("output") or out.get("content") or out)[:600]
    err = run.error
    print(f"--- {run.start_time:%H:%M:%S} {name} err={bool(err)}")
    if err:
        print("    ERR:", str(err)[:200])
    print("   ", content.replace("\n", " ")[:600])
