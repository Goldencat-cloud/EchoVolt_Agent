"""文本向量化（task 2.6）。

优先 OpenAI 兼容 /embeddings 端点（EMBEDDING_MODEL 配置）；不可用或缺省时
回退为本地字符 n-gram TF 余弦——确定性、零依赖，对共享实体词的同事件报道足够有效。
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter

import httpx
from dotenv import load_dotenv

from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _ngram_vector(text: str) -> list[float]:
    """字符 2/3-gram TF 向量（L2 归一化）。确定性、无外部依赖。"""
    s = re.sub(r"\s+", "", (text or "").lower())
    grams: Counter[str] = Counter()
    for n in (2, 3):
        for i in range(max(0, len(s) - n + 1)):
            grams[s[i:i + n]] += 1
    if not grams:
        return []
    norm = math.sqrt(sum(v * v for v in grams.values()))
    return [v / norm for v in grams.values()]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return dot  # 各自已 L2 归一化


class Vectorizer:
    """可注入的向量化器：API embeddings 优先，失败自动回退 n-gram。

    配置优先级：EMBEDDING_BASE_URL/EMBEDDING_API_KEY/EMBEDDING_MODEL
    → 回退 OPENAI_BASE_URL/OPENAI_API_KEY + EMBEDDING_MODEL → 缺省 n-gram。
    """

    def __init__(self, model: str | None = None, base_url: str | None = None,
                 api_key: str | None = None):
        self.model = model or os.getenv("EMBEDDING_MODEL")
        self.base_url = (base_url or os.getenv("EMBEDDING_BASE_URL")
                         or os.getenv("OPENAI_BASE_URL") or "").rstrip("/")
        self.api_key = (api_key or os.getenv("EMBEDDING_API_KEY")
                        or os.getenv("OPENAI_API_KEY"))
        self.api_ok = bool(self.model and self.base_url and self.api_key)

    def _api_embed(self, texts: list[str]) -> list[list[float]] | None:
        try:
            resp = httpx.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": texts},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=60, trust_env=False,
            )
            if resp.status_code != 200:
                return None
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            vecs = [d["embedding"] for d in data]
            normed = []
            for v in vecs:
                n = math.sqrt(sum(x * x for x in v)) or 1.0
                normed.append([x / n for x in v])
            return normed
        except (httpx.HTTPError, KeyError, ValueError):
            return None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.api_ok:
            vecs = self._api_embed(texts)
            if vecs is not None:
                return vecs
        return [_ngram_vector(t) for t in texts]
