"""Optional embedding relevance backend for search_claims (auto-030 8.12 follow-up).

Uses the OpenAI-compatible ``/embeddings`` endpoint (reuses AI_BASE_URL /
AI_API_KEY, model from config.AI_EMBEDDING_MODEL). Pool vectors are cached on
disk keyed by snapshot fingerprint + model so repeated jobs never re-embed the
whole curated pool. Every entry point degrades to ``None`` on failure —
embedding is an enhancement, never a hard dependency: callers fall back to
keyword scoring.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

import config

HERE = Path(__file__).resolve().parents[1]
CACHE_DIR = HERE / "data" / "embedding-cache"
BATCH_SIZE = 64
_VECTOR_DECIMALS = 6


def embedding_model() -> str:
    return str(getattr(config, "AI_EMBEDDING_MODEL", "") or "").strip()


def backend_ready() -> bool:
    """True only when endpoint, key and model are all configured."""
    return bool(os.getenv("AI_BASE_URL") and os.getenv("AI_API_KEY") and embedding_model())


def _client():
    import llm  # 统一客户端入口

    return llm.embeddings_client()


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Embed texts in batches; ``None`` on any failure (caller degrades)."""
    if not texts or not backend_ready():
        return None
    vectors: list[list[float]] = []
    try:
        client = _client()
        for start in range(0, len(texts), BATCH_SIZE):
            batch = [t[:4_000] for t in texts[start:start + BATCH_SIZE]]
            resp = client.embeddings.create(model=embedding_model(), input=batch)
            vectors.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
    except Exception:  # noqa: BLE001 — any backend failure must degrade, not raise
        return None
    if len(vectors) != len(texts):
        return None
    return vectors


def _prune_cache(model: str, keep: int = 3) -> None:
    """Keep only the newest ``keep`` cache files per model (snapshot rollover)."""
    prefix = f"{model.replace('/', '_')}-"
    try:
        files = sorted((p for p in CACHE_DIR.glob(prefix + "*.json")),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in files[keep:]:
            stale.unlink(missing_ok=True)
    except OSError:
        pass


def pool_vectors(snapshot: str, ids: list[str],
                 texts: list[str]) -> dict[str, list[float]] | None:
    """claim_id → vector, disk-cached per snapshot fingerprint + model.

    Missing ids are embedded in batches and appended to the cache; a cache
    write failure is non-fatal. Returns ``None`` when the backend is not
    configured or an embedding call fails.
    """
    if len(ids) != len(texts) or not backend_ready():
        return None
    model = embedding_model()
    cache_file = CACHE_DIR / f"{model.replace('/', '_')}-{snapshot}.json"
    data: dict[str, list[float]] = {}
    try:
        if cache_file.is_file():
            loaded = json.loads(cache_file.read_text(encoding="utf-8"))
            if loaded.get("model") == model:
                data = {str(k): v for k, v in loaded.get("vectors", {}).items()}
    except (OSError, ValueError):
        data = {}
    missing = [(cid, text) for cid, text in zip(ids, texts) if cid not in data]
    if missing:
        vectors = embed_texts([text for _, text in missing])
        if vectors is None:
            return None
        for (cid, _), vec in zip(missing, vectors):
            data[cid] = [round(float(x), _VECTOR_DECIMALS) for x in vec]
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {"model": model, "snapshot": snapshot, "vectors": data}
            tmp = cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(cache_file)
            _prune_cache(model)
        except OSError:
            pass  # cache write failure is non-fatal; vectors stay in memory
    return {cid: data[cid] for cid in ids if cid in data}


def cosine(a: list[float], b: list[float]) -> float:
    """Deterministic cosine similarity in [-1, 1]; 0.0 for degenerate inputs."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
