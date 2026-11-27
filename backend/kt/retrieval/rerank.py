"""Second-stage rerankers.

Hybrid retrieval (vector + BM25 + RRF) is cheap and has good recall; a cross-encoder reads the query
and each candidate passage *together*, which gives much better precision for the top results.
It only runs on the few dozen fused candidates that already passed the ACL filter.

Providers (``KT_RERANKER``):
* ``none``           — keep the fused RRF order (default; no extra dependency);
* ``cross-encoder``  — local sentence-transformers CrossEncoder (default model
  ``BAAI/bge-reranker-v2-m3``, multilingual incl. Polish; lighter English alternative:
  ``cross-encoder/ms-marco-MiniLM-L-6-v2``). Runs locally: no document text leaves your infrastructure.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from functools import lru_cache

from kt.config import Settings, get_settings


class Reranker(ABC):
    model_id: str

    @abstractmethod
    def score(self, query: str, passages: list[str]) -> list[float]:
        """Relevance of each passage to the query, as probabilities in [0, 1] (same order as input)."""


def _to_probabilities(raw: list[float]) -> list[float]:
    """Models differ: some return logits, some already apply a sigmoid. Normalise to [0, 1]."""
    if all(0.0 <= x <= 1.0 for x in raw):
        return [float(x) for x in raw]
    return [1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, float(x))))) for x in raw]


class CrossEncoderReranker(Reranker):
    def __init__(self, model: str = "BAAI/bge-reranker-v2-m3", max_length: int = 512, batch_size: int = 16,
                 device: str | None = None):
        from sentence_transformers import CrossEncoder  # optional dependency: pip install .[rerank]

        self._model = CrossEncoder(model, max_length=max_length, device=device)
        self.model_id = model
        self.batch_size = batch_size

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        raw = self._model.predict([(query, p) for p in passages], batch_size=self.batch_size,
                                  show_progress_bar=False)
        return _to_probabilities([float(x) for x in raw])


def build_reranker(settings: Settings) -> Reranker | None:
    if settings.reranker == "cross-encoder":
        return CrossEncoderReranker(settings.reranker_model, settings.reranker_max_length,
                                    device=settings.reranker_device)
    return None


@lru_cache
def get_reranker() -> Reranker | None:
    return build_reranker(get_settings())
