"""Weighted multi-signal document graph.

    W_ij = α·S_semantic + β·S_entity + γ·S_link + δ·S_context

Typed sub-signals are preserved on every edge (``signals``), so the clustering projection
(the weight) never erases *why* two documents are connected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import networkx as nx
import numpy as np

from kt.topology.corpus import Corpus


@dataclass
class GraphParams:
    alpha: float = 0.55  # semantic similarity
    beta: float = 0.20  # shared entities
    gamma: float = 0.15  # explicit links
    delta: float = 0.10  # organisational context (same space/folder)
    knn: int = 8
    min_weight: float = 0.12
    duplicate_cosine: float = 0.95
    duplicate_shingle: float = 0.6


@dataclass
class DocGraph:
    graph: nx.Graph
    ids: list[str]
    sim: np.ndarray  # cosine matrix aligned with ids
    sem_norm: np.ndarray  # normalised semantic signal
    corpus_mean: float
    duplicates: list[tuple[str, str, float, str]] = field(default_factory=list)


def _entity_similarity(corpus: Corpus, a: str, b: str, n_docs: int) -> float:
    ea, eb = corpus.docs[a].entities, corpus.docs[b].entities
    if not ea or not eb:
        return 0.0
    def idf(e):
        return math.log(1 + n_docs / (1 + corpus.entity_df[e]))
    inter = sum(idf(e) for e in ea & eb)
    union = sum(idf(e) for e in ea | eb)
    return inter / union if union else 0.0


def _context_similarity(corpus: Corpus, a: str, b: str) -> float:
    da, db = corpus.docs[a], corpus.docs[b]
    if da.source_id != db.source_id:
        return 0.0
    pa, pb = da.path, db.path
    if not pa or not pb:
        return 0.3
    common = 0
    for x, y in zip(pa, pb):
        if x != y:
            break
        common += 1
    return min(1.0, common / max(len(pa), len(pb)))


def build_document_graph(corpus: Corpus, params: GraphParams | None = None) -> DocGraph:
    p = params or GraphParams()
    ids = corpus.ids
    n = len(ids)
    g = nx.Graph()
    g.add_nodes_from(ids)
    if n == 0:
        return DocGraph(g, ids, np.zeros((0, 0)), np.zeros((0, 0)), 0.0)
    m = corpus.matrix(ids)
    sim = np.clip(m @ m.T, -1.0, 1.0)
    off = sim[~np.eye(n, dtype=bool)]
    mu = float(off.mean()) if off.size else 0.0
    sd = float(off.std()) if off.size else 0.0
    # Semantic signal relative to the corpus background similarity (scale-free across embedders).
    floor = mu + 0.5 * sd
    sem = np.clip((sim - floor) / max(1e-6, 1 - floor), 0, 1)
    np.fill_diagonal(sem, 0)
    pos = {i: k for k, i in enumerate(ids)}

    candidates: set[tuple[int, int]] = set()
    k = min(p.knn, n - 1)
    if k > 0:
        nn = np.argsort(-sem, axis=1)[:, :k]
        for i in range(n):
            for j in nn[i]:
                if sem[i, j] > 0:
                    candidates.add((min(i, int(j)), max(i, int(j))))
    for a in ids:
        for b in corpus.docs[a].links_out:
            if b in pos:
                i, j = pos[a], pos[b]
                candidates.add((min(i, j), max(i, j)))

    duplicates: list[tuple[str, str, float, str]] = []
    for i, j in candidates:
        a, b = ids[i], ids[j]
        s_sem = float(sem[i, j])
        s_ent = _entity_similarity(corpus, a, b, n)
        s_link = 1.0 if (b in corpus.docs[a].links_out or a in corpus.docs[b].links_out) else 0.0
        s_ctx = _context_similarity(corpus, a, b)
        w = p.alpha * s_sem + p.beta * s_ent + p.gamma * s_link + p.delta * s_ctx
        if w >= p.min_weight or s_link:
            g.add_edge(a, b, weight=round(w, 4), signals={
                "semantic": round(s_sem, 3), "entity": round(s_ent, 3), "link": s_link,
                "context": round(s_ctx, 3), "cosine": round(float(sim[i, j]), 3)})
    # Near-duplicates (checked over all pairs with high cosine, not only kNN).
    hi = np.argwhere(np.triu(sim, 1) >= min(p.duplicate_cosine, 0.8))
    for i, j in hi:
        a, b = ids[int(i)], ids[int(j)]
        sa, sb = corpus.docs[a].shingles, corpus.docs[b].shingles
        jac = len(sa & sb) / len(sa | sb) if sa and sb else 0.0
        if sim[i, j] >= p.duplicate_cosine or jac >= p.duplicate_shingle:
            duplicates.append((a, b, round(float(max(jac, sim[i, j])), 3), "shingle" if jac >= p.duplicate_shingle
                               else "cosine"))
    return DocGraph(g, ids, sim, sem, mu, duplicates)
