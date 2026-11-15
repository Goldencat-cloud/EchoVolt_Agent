"""Errors raised while loading or checking a semantic model.

Model errors are definition errors: they must fail the build, never be caught
and turned into an empty result. Query-time errors live in ``semantic.compile``.
"""

from __future__ import annotations


class ModelError(ValueError):
    """A semantic model is structurally or semantically invalid."""

    def __init__(self, message: str, *, where: str | None = None) -> None:
        self.where = where
        super().__init__(f"{where}: {message}" if where else message)
