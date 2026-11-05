"""Path constants for the QA module."""
from __future__ import annotations

from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[2]          # .../07_qa_agent
PIPELINE = MODULE_ROOT.parent
KB_OUTPUT = PIPELINE / "06_reporting" / "agent-kb" / "output"
REPORT_MD = KB_OUTPUT / "report.md"
DATA_VERSION = KB_OUTPUT / "data-version.json"
CONFIGS = MODULE_ROOT / "configs"
OUTPUT = MODULE_ROOT / "output"
INDEX_JSON = OUTPUT / "rag-index.json"
