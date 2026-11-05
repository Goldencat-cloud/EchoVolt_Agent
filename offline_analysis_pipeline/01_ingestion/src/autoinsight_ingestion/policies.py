"""仓库策略：一次性加载、可注入的规则集合。

配置位置只在此处定义，调用方（CLI、测试）可用显式路径覆盖，
避免策略读取散落在数据访问代码里。
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[2] / 'configs'
EXCLUSION_POLICY_FILE = CONFIG_DIR / 'excluded-stock-posts.json'


def load_exclusion_policy(path: Path | None = None) -> dict:
    """读取排除股票帖的策略；缺文件即报错，不静默降级为空策略。"""
    source = Path(path) if path is not None else EXCLUSION_POLICY_FILE
    return json.loads(source.read_text(encoding='utf-8'))
