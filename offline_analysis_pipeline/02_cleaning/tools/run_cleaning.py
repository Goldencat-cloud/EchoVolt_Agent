# -*- coding: utf-8 -*-
"""一条命令完成清洗标注与校验（委托 corpus_cleaning.cli）。

用法（仓库根目录）：
  python offline_analysis_pipeline/02_cleaning/tools/run_cleaning.py \
      --db offline_analysis_pipeline/data/stock/db/ingestion.sqlite3 [--dry-run] [--version clean-v1]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from corpus_cleaning.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
