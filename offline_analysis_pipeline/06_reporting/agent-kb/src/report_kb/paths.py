"""Central path constants; single place that knows the module layout."""
from __future__ import annotations

from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[2]      # .../06_reporting/agent-kb
PIPELINE_REPORTING = MODULE_ROOT.parent                 # .../06_reporting
ANALYSIS = PIPELINE_REPORTING / "analysis"              # frozen upstream data (read-only)
CONFIGS = MODULE_ROOT / "configs"                       # authored: content/template/policy
OUTPUT = MODULE_ROOT / "output"                         # generated artifacts
ASSETS = OUTPUT / "assets"
EVIDENCE = MODULE_ROOT / "evidence"

REQUIRED_ANALYSIS_FILES = ["summary.json", "profiles.json", "aspect-sentiment.csv",
                           "scope.json", "reviewed-cases.json", "verification.json"]
