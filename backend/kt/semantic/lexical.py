"""BM25 full-text index — complements vector search for identifiers, error codes, endpoints."""

from __future__ import annotations

import math
from collections import Counter

from kt.semantic.text import STOPWORDS, stem, tokenize


def lexical_terms(text: str) -> list[str]:
    out = []
    for t in tokenize(text):
        if t in STOPWORDS:
            continue
        out.append(stem(t))
        # keep compound identifiers searchable by their parts too (PAYMENT-SERVICE-03 -> payment, service, 03)
        if "-" in t or "_" in t or "." in t:
            out.extend(stem(p) for p in t.replace("_", "-").replace(".", "-").split("-") if p)
    return out


class BM25Index:
    def __init__(self, k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.doc_terms: dict[str, Counter] = {}
        self.doc_len: dict[str, int] = {}
        self.df: Counter = Counter()

    def add(self, key: str, text: str) -> None:
        terms = Counter(lexical_terms(text))
        self.doc_terms[key] = terms
        self.doc_len[key] = sum(terms.values())
        self.df.update(terms.keys())

    def search(self, query: str, top_k: int = 30, allowed: set[str] | None = None,
               min_coverage: float = 0.5) -> list[tuple[str, float]]:
        """BM25 ranking; a hit must contain at least ``min_coverage`` of the query terms (avoids matching
        only a generic word such as "days")."""
        q = set(lexical_terms(query))
        if not q or not self.doc_terms:
            return []
        n = len(self.doc_terms)
        avg = sum(self.doc_len.values()) / n
        scores: list[tuple[str, float]] = []
        for key, terms in self.doc_terms.items():
            if allowed is not None and key not in allowed:
                continue
            s = 0.0
            matched = sum(1 for t in q if t in terms)
            if matched < max(1, min_coverage * len(q)):
                continue
            for t in q:
                tf = terms.get(t)
                if not tf:
                    continue
                idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                s += idf * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * self.doc_len[key] / avg))
            if s > 0:
                scores.append((key, s))
        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]
