"""pytest 路径引导：把 src/ 加入 sys.path，使 `from mcp_server import ...` 可用。

工具根目录执行 `python -m pytest tests -q` 即可，无需手工设置 PYTHONPATH。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
