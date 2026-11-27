"""Pluggable embedding providers. Changing the model requires re-indexing (the model id is
stored on every vector and snapshot)."""

from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from functools import lru_cache

import httpx
import numpy as np

from kt.config import Settings, get_settings
from kt.semantic.text import content_terms, stem


class Embedder(ABC):
    model_id: str
    dim: int

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an (n, dim) float32 array of L2-normalised vectors."""

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


def _normalise(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


class HashingEmbedder(Embedder):
    """Deterministic feature-hashing embedder (stemmed unigrams + bigrams, sublinear TF).

    Not "semantic" in the neural sense, but dependency-free, fast and stable — ideal for tests,
    demos and air-gapped smoke runs. Use BGE-M3 (sentence-transformers) for real deployments.
    """

    def __init__(self, dim: int = 768):
        self.dim = dim
        self.model_id = f"hashing-v1-{dim}"

    def _bucket(self, feature: str) -> tuple[int, float]:
        h = int.from_bytes(hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest(), "little")
        return h % self.dim, (1.0 if (h >> 63) & 1 else -1.0)

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            terms = [stem(t) for t in content_terms(text)]
            counts: dict[str, int] = {}
            for t in terms:
                counts[t] = counts.get(t, 0) + 1
            for a, b in zip(terms, terms[1:]):
                key = f"{a}_{b}"
                counts[key] = counts.get(key, 0) + 1
            for feat, c in counts.items():
                idx, sign = self._bucket(feat)
                weight = (1.0 + math.log(c)) * (0.6 if "_" in feat else 1.0)
                out[i, idx] += sign * weight
        return _normalise(out)


class SentenceTransformerEmbedder(Embedder):
    def __init__(self, model: str = "BAAI/bge-m3"):
        from sentence_transformers import SentenceTransformer  # optional dependency

        self._model = SentenceTransformer(model)
        self.dim = int(self._model.get_sentence_embedding_dimension())
        self.model_id = model

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = self._model.encode(texts, batch_size=16, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vecs, dtype=np.float32)


class OpenAIEmbedder(Embedder):
    def __init__(self, model: str, api_key: str, base_url: str, dim: int):
        self.model_id, self.dim = model, dim
        self._client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=60)

    def embed(self, texts: list[str]) -> np.ndarray:
        rows: list[list[float]] = []
        for i in range(0, len(texts), 64):
            resp = self._client.post("/embeddings", json={"model": self.model_id, "input": texts[i : i + 64]})
            resp.raise_for_status()
            rows.extend(d["embedding"] for d in sorted(resp.json()["data"], key=lambda d: d["index"]))
        return _normalise(np.asarray(rows, dtype=np.float32))


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "sentence-transformers":
        return SentenceTransformerEmbedder(settings.embedding_model)
    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("KT_OPENAI_API_KEY is required for the openai embedding provider")
        return OpenAIEmbedder(settings.embedding_model, settings.openai_api_key, settings.openai_base_url,
                              settings.embedding_dim)
    return HashingEmbedder(settings.embedding_dim)


@lru_cache
def get_embedder() -> Embedder:
    return build_embedder(get_settings())
