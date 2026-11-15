"""Read-only LangSmith probe: list recent runs of the E2E project."""
from __future__ import annotations

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
os.environ.setdefault("LANGSMITH_TRACING", "true")

from langsmith import Client  # noqa: E402

project = os.environ.get("LANGSMITH_PROJECT") or "deep-agents-action"
client = Client()
runs = list(client.list_runs(project_name=project, limit=int(sys.argv[1]) if len(sys.argv) > 1 else 12))
print(f"project={project} runs={len(runs)}")
for run in runs:
    tokens = getattr(run, "total_tokens", None)
    error = bool(getattr(run, "error", None))
    print(f"{run.start_time:%H:%M:%S} | {run.run_type:8s} | {str(run.name)[:42]:42s} | "
          f"{run.status:8s} | tokens={tokens} | err={error}")
