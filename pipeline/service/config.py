"""Runtime configuration shared by every entry point.

Loads the local .env once (without overriding real environment variables) and
exposes the model-readiness check so service/app/agent_engine behave consistently
regardless of which module is imported first.
"""
from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / ".env"


def load_env(path: Path | None = None) -> None:
    """Minimal .env loader (no override of real environment)."""
    env_file = path or ENV_FILE
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def model_configured() -> bool:
    """True when a chat model is available and data transfer was authorised."""
    return bool(os.getenv("AI_BASE_URL") and os.getenv("AI_API_KEY") and os.getenv("AI_MODEL")
                and os.getenv("AI_DATA_APPROVED") == "1")


def model_configured_without_approval() -> bool:
    """Model reachable but Owner transfer approval not yet recorded."""
    return bool(os.getenv("AI_BASE_URL") and os.getenv("AI_API_KEY") and os.getenv("AI_MODEL"))


# ---- 共享硬参数（单一事实源，auto-030 D12/D13）----
# 技能、工具说明与校验器引用同一处；不在多个文档里重复数值。
REPORT_MAX_CHARS = 12_000      # 报告正文硬上限（report_gate 与技能/工具说明共用）
BRIEF_MAX_CHARS = 6_000        # 任务简报总长上限（超限按既定次序裁剪）
BRIEF_ENUM_TOP_N = 20          # 枚举列展示上限（按计数排序）
BRIEF_SAMPLE_VALUES = 3        # 自由文本列示例值个数（裁剪时最先收缩）
BASELINE_TOP_ROWS = 16         # 预置基准行数（全量口径负面占比 Top N）

# 品牌策略（Owner 2026-10-27 裁定：当前仅开放 SU7 主体分析，多品牌分支延后）。
# 置 True 后 resolve_brand_scope 启用多品牌澄清分支（D11 梯子）。
BRAND_MULTI_ENABLED = False
SUBJECT_BRAND = "小米"
SUBJECT_SERIES = "SU7"

# Embedding 相关度（auto-030 8.12 后续，Owner 2026-10-28 指示）：search_claims 可选
# 语义相关度后端。留空 = 仅关键词评分；配置模型名后走 /embeddings（复用
# AI_BASE_URL/AI_API_KEY），池向量按快照指纹落盘缓存，调用失败自动降级关键词评分。
AI_EMBEDDING_MODEL = os.getenv("AI_EMBEDDING_MODEL", "")


load_env()
