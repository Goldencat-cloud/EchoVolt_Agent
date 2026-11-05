"""Build chain: source → staging → core → metadata."""

from __future__ import annotations

from .paths import DEFAULT_DB_PATH, PIPELINE_ROOT, SERVICE_ROOT, frozen_inputs_dir, source_path
from .runner import BuildError, build, check

__all__ = [
    "BuildError",
    "DEFAULT_DB_PATH",
    "PIPELINE_ROOT",
    "SERVICE_ROOT",
    "build",
    "check",
    "frozen_inputs_dir",
    "source_path",
]
