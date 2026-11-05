"""Path resolution for the build.

All source locations come from the model, never from constants buried in code:
one place decides where data comes from, and moving it is a model change.
"""

from __future__ import annotations

from pathlib import Path

from ..spec import errors
from ..spec.types import SemanticModel

# 文件位置：semantic/build/paths.py -> build -> semantic -> 08_semantic_services -> 管道根
PIPELINE_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = SERVICE_ROOT / "data" / "semantic.db"
DEFAULT_FROZEN_INPUTS = PIPELINE_ROOT / "04_extraction" / "frozen_inputs"


def source_path(model: SemanticModel, key: str) -> Path:
    """Resolve one declared source path to an absolute file."""
    relative = model.snapshot.paths.get(key)
    if not relative:
        raise errors.ModelError(f"模型未声明数据源 '{key}'", where="snapshot.paths")
    path = (PIPELINE_ROOT / relative).resolve()
    if not path.is_file():
        raise errors.ModelError(
            f"数据源 '{key}' 指向的文件不存在：{path}", where="snapshot.paths")
    return path


def frozen_inputs_dir() -> Path:
    return DEFAULT_FROZEN_INPUTS
