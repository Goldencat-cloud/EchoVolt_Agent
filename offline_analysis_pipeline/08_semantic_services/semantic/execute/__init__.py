"""Execution layer: run a compiled plan read-only and wrap the result."""

from __future__ import annotations

from .runner import execute, execute_saved

__all__ = ["execute", "execute_saved"]
