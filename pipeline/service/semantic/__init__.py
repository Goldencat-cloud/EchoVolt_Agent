"""Semantic layer: declarative model, build, compile, execute, catalogue.

Layering (a lower layer must never import a higher one):

    spec  <  model  <  build / compile  <  execute  <  catalog  <  adapters

`semantic` intentionally imports nothing from the legacy modules at import
time; wiring to the HTTP/MCP/agent surfaces belongs to a later change.
"""

from __future__ import annotations

__all__ = ["MODEL_SCHEMA_VERSION"]

MODEL_SCHEMA_VERSION = "autoinsight-semantic-1"
