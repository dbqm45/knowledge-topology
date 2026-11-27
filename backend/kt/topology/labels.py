"""Cluster naming via class-based TF-IDF over terms + distinctive entities (deterministic).

An optional LLM namer can replace this; boundaries are never affected by naming.
"""

from __future__ import annotations

import math
from collections import Counter

from kt.topology.corpus import Corpus

GENERIC_TERMS = {"document", "page", "section", "overview", "note", "detail", "information", "team", "process",
                 "system", "service", "data", "use", "need", "include", "follow", "provide", "make", "work",
                 "step", "time", "new", "current", "example", "description", "general"}


def distinctive_terms(corpus: Corpus, doc_ids: set[str] | list[str], top: int = 6) -> list[str]:
    doc_ids = [d for d in doc_ids if d in corpus.docs]
    if not doc_ids:
        return []
    cluster_tf: Counter = Counter()
    for d in doc_ids:
        cluster_tf.update(corpus.docs[d].terms)
    df: Counter = Counter()
    for d in corpus.docs.values():
        df.update(set(d.terms))
    n = len(corpus.docs)
    total = sum(cluster_tf.values()) or 1
    in_cluster_df: Counter = Counter()
    for d in doc_ids:
        in_cluster_df.update(set(corpus.docs[d].terms))
    scored = []
    for t, c in cluster_tf.items():
        if t in GENERIC_TERMS or len(t) < 3 or in_cluster_df[t] < max(1, len(doc_ids) // 4):
            continue
        scored.append((c / total * math.log(1 + n / df[t]), t))
    return [t for _, t in sorted(scored, reverse=True)[:top]]


def distinctive_entities(corpus: Corpus, doc_ids, top: int = 4) -> list[str]:
    doc_ids = [d for d in doc_ids if d in corpus.docs]
    cnt: Counter = Counter()
    for d in doc_ids:
        cnt.update(corpus.docs[d].entities)
    n = len(corpus.docs)
    scored = []
    for e, c in cnt.items():
        ent = corpus.entities.get(e)
        if ent is None or ent.entity_type in ("identifier", "team") or c < 2:
            continue
        spread = corpus.entity_df[e] / n
        if spread > 0.5:
            continue
        scored.append((c / len(doc_ids) * math.log(1 + n / corpus.entity_df[e]), ent.canonical_name))
    return [name for _, name in sorted(scored, reverse=True)[:top]]


def label_for(corpus: Corpus, doc_ids) -> tuple[str, str]:
    ents = distinctive_entities(corpus, doc_ids, 2)
    terms = distinctive_terms(corpus, doc_ids, 5)
    if ents:
        label = " & ".join(ents)
    elif terms:
        label = " · ".join(t.title() for t in terms[:2])
    else:
        label = "Unnamed area"
    desc_terms = ", ".join(terms[:5])
    description = f"{len(list(doc_ids))} documents" + (f" about {desc_terms}" if desc_terms else "")
    return label, description
