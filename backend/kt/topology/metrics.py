"""Eight independent quality dimensions per knowledge area.

Every metric returns score (0–100), confidence (0–1), sample size, whether it is *measured*
or *estimated*, and the signals that produced it. There is deliberately no single hidden
"quality" number — the composite health index is only a summary for overview screens.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import networkx as nx
import numpy as np

from kt.entities.extraction import claims_conflict
from kt.semantic.text import stem
from kt.topology.corpus import Corpus, doc_sentence_stats
from kt.topology.graph import DocGraph

METRICS = ("cohesion", "connectivity", "coverage", "consistency", "clarity", "freshness", "duplication",
           "traceability")
COMPOSITE_WEIGHTS = {"cohesion": 1.0, "connectivity": 0.8, "coverage": 0.8, "consistency": 1.2, "clarity": 0.7,
                     "freshness": 0.9, "duplication": 0.7, "traceability": 0.6}
# Expected update cycle (half-life in days) per document type: knowledge ages at different speeds.
HALF_LIFE_DAYS = {"runbook": 180, "procedure": 180, "howto": 240, "policy": 365, "architecture": 540,
                  "adr": 900, "reference": 540, "page": 365}
DEFAULT_HALF_LIFE = 365


@dataclass
class MetricResult:
    score: float | None
    confidence: float
    sample_size: int
    measured: bool = True
    signals: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"score": None if self.score is None else round(self.score, 1), "confidence": round(self.confidence, 2),
                "sample_size": self.sample_size, "measured": self.measured, "signals": self.signals}


@dataclass
class Conflict:
    doc_a: str
    doc_b: str
    chunk_a: str
    chunk_b: str
    sentence_a: str
    sentence_b: str
    value_a: float
    value_b: float
    unit: str
    shared_terms: list[str]
    confidence: float


@dataclass
class AreaAnalysis:
    metrics: dict[str, MetricResult]
    conflicts: list[Conflict]
    duplicates: list[tuple[str, str, float, str]]
    stale_docs: dict[str, float]  # doc -> age/half-life ratio
    isolated_docs: list[str]
    stub_docs: list[str]
    unowned_docs: list[str]
    components: list[set[str]]
    external_weight: dict[str, float]  # other-area key -> weight

    @property
    def composite(self) -> float:
        num = den = 0.0
        for name, m in self.metrics.items():
            if m.score is not None:
                w = COMPOSITE_WEIGHTS[name] * (0.5 + 0.5 * m.confidence)
                num += w * m.score
                den += w
        return round(num / den, 1) if den else 0.0


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def find_conflicts(corpus: Corpus, doc_ids: list[str]) -> tuple[list[Conflict], int]:
    """Numeric claims about the same subject with different values across documents."""
    conflicts: list[Conflict] = []
    comparable = 0
    seen: set[tuple] = set()
    claims = [(d, cl, ch) for d in doc_ids for cl, ch in corpus.docs[d].claims]
    for i in range(len(claims)):
        da, ca, cha = claims[i]
        for j in range(i + 1, len(claims)):
            db, cb, chb = claims[j]
            if da == db or ca.unit != cb.unit:
                continue
            shared = ca.key_terms & cb.key_terms
            if len(shared) < 3:
                continue
            comparable += 1
            if claims_conflict(ca, cb):
                key = (min(da, db), max(da, db), ca.unit, min(ca.value, cb.value), max(ca.value, cb.value))
                if key in seen:
                    continue
                seen.add(key)
                jac = len(shared) / len(ca.key_terms | cb.key_terms)
                if ca.value > cb.value:  # deterministic orientation: lower value first
                    da, db, ca, cb, cha, chb = db, da, cb, ca, chb, cha
                conflicts.append(Conflict(da, db, cha, chb, ca.sentence, cb.sentence, ca.value, cb.value, ca.unit,
                                          sorted(shared), round(min(0.95, 0.45 + jac), 2)))
                da, ca, cha = claims[i]
    return conflicts, comparable


def analyse_area(
    corpus: Corpus, dg: DocGraph, doc_ids: set[str], area_of: dict[str, str], area_key: str,
    required_topics: list[str] | None = None, now: datetime | None = None,
) -> AreaAnalysis:
    now = now or datetime.now(timezone.utc)
    ids = sorted(doc_ids)
    n = len(ids)
    pos = {d: k for k, d in enumerate(dg.ids)}
    g = dg.graph
    metrics: dict[str, MetricResult] = {}

    # --- Cohesion: silhouette-style contrast between intra-area and nearest-other-area similarity.
    idx = [pos[d] for d in ids]
    intra = dg.sim[np.ix_(idx, idx)]
    a = float((intra.sum() - n) / max(1, n * n - n)) if n > 1 else 1.0
    others: dict[str, list[int]] = {}
    for d, k in area_of.items():
        if k != area_key and d in pos:
            others.setdefault(k, []).append(pos[d])
    b = max((float(dg.sim[np.ix_(idx, o)].mean()) for o in others.values()), default=dg.corpus_mean)
    contrast = (a - b) / max(a, b, 1e-6)
    spread = float(intra[~np.eye(n, dtype=bool)].std()) if n > 2 else 0.0
    cohesion = _clip(100 * (0.35 + 0.65 * contrast) - 40 * spread)
    metrics["cohesion"] = MetricResult(cohesion, min(1.0, 0.3 + n / 20), n, True,
                                       {"intra_similarity": round(a, 3), "nearest_other_similarity": round(b, 3),
                                        "similarity_spread": round(spread, 3)})

    # --- Connectivity: internal fragmentation, isolated documents, links to the rest of knowledge.
    sub = g.subgraph(ids)
    strong = nx.Graph()
    strong.add_nodes_from(ids)
    strong.add_edges_from((u, v) for u, v, dd in sub.edges(data=True)
                          if dd["weight"] >= 0.2 or dd["signals"]["link"])
    components = sorted((set(c) for c in nx.connected_components(strong)), key=len, reverse=True)
    isolated = [d for d in ids if g.degree(d) == 0 or strong.degree(d) == 0]
    external: dict[str, float] = {}
    for d in ids:
        for _, v, dd in g.edges(d, data=True):
            k = area_of.get(v)
            if k and k != area_key:
                external[k] = external.get(k, 0.0) + dd["weight"]
    largest = len(components[0]) / n if components else 0
    linked = sum(1 for d in ids if corpus.docs[d].links_out or any(d in corpus.docs[o].links_out for o in ids))
    connectivity = _clip(100 * (0.45 * largest + 0.25 * (1 - len(isolated) / n) + 0.15 * (linked / n)
                                + 0.15 * min(1.0, len(external) / 2)))
    metrics["connectivity"] = MetricResult(connectivity, min(1.0, 0.4 + n / 15), n, True, {
        "components": len(components), "largest_component_ratio": round(largest, 2),
        "isolated_documents": len(isolated), "explicitly_linked_ratio": round(linked / n, 2),
        "connected_areas": len(external)})

    # --- Coverage: observed (key entities with a dedicated document/section) + optional required checklist.
    ent_count: dict[str, int] = {}
    for d in ids:
        for e in corpus.docs[d].entities:
            ent_count[e] = ent_count.get(e, 0) + 1
    key_entities = [e for e, c in ent_count.items() if c >= 2 and e in corpus.entities
                    and corpus.entities[e].entity_type != "identifier"]
    titles = " ".join((corpus.docs[d].title + " " + " ".join(corpus.docs[d].headings)).lower() for d in ids)
    explained = [e for e in key_entities if corpus.entities[e].canonical_name.lower() in titles]
    observed = (len(explained) / len(key_entities)) if key_entities else 0.5
    # Shallow areas (few documents per key concept) are less likely to be complete.
    depth = min(1.0, n / max(3, len(key_entities) * 0.8))
    coverage_signals = {"key_entities": len(key_entities), "explained_entities": len(explained),
                        "unexplained": sorted(corpus.entities[e].canonical_name for e in key_entities
                                              if e not in explained)[:10], "depth": round(depth, 2)}
    score = 100 * (0.6 * observed + 0.4 * depth)
    measured = False
    if required_topics:
        text = " ".join(corpus.docs[d].text.lower() for d in ids)
        stemmed = {stem(w) for w in text.split()}
        covered = [t for t in required_topics if t.lower() in text or all(stem(w) in stemmed for w in t.lower().split())]
        req = len(covered) / len(required_topics)
        coverage_signals["required_topics"] = len(required_topics)
        coverage_signals["missing_required"] = [t for t in required_topics if t not in covered]
        score = 100 * (0.4 * observed + 0.6 * req)
        measured = True
    metrics["coverage"] = MetricResult(_clip(score), 0.7 if measured else 0.35, len(key_entities), measured,
                                       {**coverage_signals, "mode": "required" if measured else "observed"})

    # --- Consistency: conflicting numeric claims among comparable claims.
    conflicts, comparable = find_conflicts(corpus, ids)
    if comparable:
        cons = 100 * (1 - min(1.0, len(conflicts) / comparable))
        cons_conf = min(0.9, 0.3 + comparable / 10)
    else:
        cons, cons_conf = 100.0, 0.15
    conflict_docs = {c.doc_a for c in conflicts} | {c.doc_b for c in conflicts}
    cons = min(cons, 100 * (1 - 0.8 * len(conflict_docs) / n))
    metrics["consistency"] = MetricResult(_clip(cons), cons_conf, comparable, True, {
        "comparable_claim_pairs": comparable, "conflicts": len(conflicts),
        "documents_in_conflict": len(conflict_docs)})

    # --- Clarity: structure, sentence length, stubs.
    stubs, per_doc = [], []
    for d in ids:
        doc = corpus.docs[d]
        avg_len, n_sent = doc_sentence_stats(doc.text)
        structured = 1.0 if doc.headings else 0.3
        length_score = 1.0 if 8 <= avg_len <= 24 else max(0.0, 1 - abs(avg_len - 16) / 30)
        stub = doc.token_count < 60
        if stub:
            stubs.append(d)
        per_doc.append(0.45 * structured + 0.35 * length_score + 0.2 * (0.0 if stub else 1.0))
    clarity = 100 * float(np.mean(per_doc))
    metrics["clarity"] = MetricResult(_clip(clarity), 0.5, n, False, {
        "unstructured_documents": sum(1 for d in ids if not corpus.docs[d].headings), "stub_documents": len(stubs)})

    # --- Freshness: weighted exponential decay, half-life per document type.
    fresh_vals, stale = [], {}
    for d in ids:
        doc = corpus.docs[d]
        hl = HALF_LIFE_DAYS.get((doc.document_type or "").lower(), DEFAULT_HALF_LIFE)
        if doc.updated_at is None:
            fresh_vals.append(0.5)
            continue
        upd = doc.updated_at if doc.updated_at.tzinfo else doc.updated_at.replace(tzinfo=timezone.utc)
        age = max(0.0, (now - upd).days)
        fresh_vals.append(math.exp(-math.log(2) * age / hl))
        if age > hl:
            stale[d] = round(age / hl, 2)
    metrics["freshness"] = MetricResult(_clip(100 * float(np.mean(fresh_vals))), 0.8, n, True, {
        "stale_documents": len(stale), "median_age_days": _median_age(corpus, ids, now)})

    # --- Duplication.
    dups = [t for t in dg.duplicates if t[0] in doc_ids and t[1] in doc_ids]
    dup_docs = {x for a_, b_, _, _ in dups for x in (a_, b_)}
    metrics["duplication"] = MetricResult(_clip(100 * (1 - len(dup_docs) / n) ** 1.3), 0.8, n, True, {
        "duplicate_pairs": len(dups), "documents_involved": len(dup_docs)})

    # --- Traceability: owner, source URL, version, modification date.
    unowned = [d for d in ids if not corpus.docs[d].owner]
    trace = [0.4 * bool(corpus.docs[d].owner) + 0.2 * bool(corpus.docs[d].uri) + 0.2 * corpus.docs[d].has_version
             + 0.2 * bool(corpus.docs[d].updated_at) for d in ids]
    metrics["traceability"] = MetricResult(_clip(100 * float(np.mean(trace))), 0.9, n, True,
                                           {"documents_without_owner": len(unowned)})

    return AreaAnalysis(metrics, conflicts, dups, stale, isolated, stubs, unowned, components, external)


def _median_age(corpus: Corpus, ids: list[str], now: datetime) -> int | None:
    ages = []
    for d in ids:
        u = corpus.docs[d].updated_at
        if u:
            u = u if u.tzinfo else u.replace(tzinfo=timezone.utc)
            ages.append((now - u).days)
    return int(np.median(ages)) if ages else None
