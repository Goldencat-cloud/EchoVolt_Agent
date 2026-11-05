# -*- coding: utf-8 -*-
"""auto-022 语料清洗模块（corpus-cleaning 能力实现）。

只读 stock 业务表；写仅限标注表 cleaning_annotations 与映射表 product_aliases。
Python 3.11+ stdlib-only；同 cleaning_version 同输入 → 同输出（幂等可重跑）。
"""

__all__ = ["contracts", "polish", "annotate", "spam", "aliases", "store", "pipeline"]
