"""Turns an area analysis into actionable, evidence-backed issues.

Issues are identified by a *fingerprint* so that their workflow state (investigating,
accepted, dismissed...) survives re-computation of the topology.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from kt.topology.corpus import Corpus
from kt.topology.metrics import AreaAnalysis


@dataclass
class IssueDraft:
    fingerprint: str
    issue_type: str
    metric: str
    severity: str
    confidence: float
    title: str
    description: str
    recommendation: str
    evidence: dict = field(default_factory=dict)

    @property
    def document_ids(self) -> list[str]:
        return self.evidence.get("document_ids", [])


def _fp(*parts) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:40]


def _subject(sentence: str, shared: list[str]) -> str:
    from kt.semantic.text import content_terms, stem

    ordered = []
    for tok in content_terms(sentence):
        if stem(tok) in shared and tok not in ordered:
            ordered.append(tok)
    return " ".join(ordered[:5]) or " ".join(shared[:4])


def _fmt(v: float) -> str:
    return f"{v:g}"


def detect_issues(corpus: Corpus, analysis: AreaAnalysis, area_label: str) -> list[IssueDraft]:
    out: list[IssueDraft] = []
    t = lambda d: corpus.docs[d].title  # noqa: E731

    for cf in analysis.conflicts:
        owners = sorted({o for o in (corpus.docs[cf.doc_a].owner, corpus.docs[cf.doc_b].owner) if o})
        subject = _subject(cf.sentence_a, cf.shared_terms)
        cross = area_label == "cross-area"
        out.append(IssueDraft(
            _fp("conflict", *sorted((cf.doc_a, cf.doc_b)), cf.unit, *sorted((cf.value_a, cf.value_b))),
            "conflict", "consistency", "medium" if cross else "high", cf.confidence,
            ("Cross-area conflict" if cross else "Conflicting values")
            + f" ({_fmt(cf.value_a)} vs {_fmt(cf.value_b)} {cf.unit}) about “{subject}”",
            f"“{t(cf.doc_a)}” states: {cf.sentence_a}\n“{t(cf.doc_b)}” states: {cf.sentence_b}",
            "Confirm the valid value with the owner" + (f" ({', '.join(owners)})" if owners else "")
            + ", fix the outdated document and mark it as superseded.",
            {"document_ids": [cf.doc_a, cf.doc_b], "chunk_ids": [cf.chunk_a, cf.chunk_b],
             "quotes": [{"document_id": cf.doc_a, "chunk_id": cf.chunk_a, "quote": cf.sentence_a},
                        {"document_id": cf.doc_b, "chunk_id": cf.chunk_b, "quote": cf.sentence_b}],
             "status_of_detection": "suspected"}))

    for a, b, score, method in analysis.duplicates:
        out.append(IssueDraft(
            _fp("duplicate", *sorted((a, b))), "duplicate", "duplication", "medium", min(0.95, score),
            f"Near-duplicate documents: “{t(a)}” and “{t(b)}”",
            f"The documents overlap almost entirely ({method} similarity {score:.2f}). Readers and agents cannot "
            f"tell which one is the source of truth.",
            "Merge them or keep one as the source of truth and turn the other into a link.",
            {"document_ids": [a, b], "similarity": score, "method": method}))

    for d, ratio in sorted(analysis.stale_docs.items(), key=lambda x: -x[1]):
        out.append(IssueDraft(
            _fp("stale", d), "stale", "freshness", "medium" if ratio >= 2 else "low", 0.8,
            f"Stale document: “{t(d)}”",
            f"Last updated {ratio:.1f}× its expected update cycle ago.",
            "Ask the owner to review it, or archive it if it no longer applies.",
            {"document_ids": [d], "age_to_half_life": ratio}))

    for d in analysis.isolated_docs:
        out.append(IssueDraft(
            _fp("isolated", d), "isolated", "connectivity", "low", 0.6,
            f"Isolated document in {area_label}: “{t(d)}”",
            "The document has no meaningful links or semantic neighbours inside its area.",
            "Link it from the relevant overview page, or move it to the area it belongs to.",
            {"document_ids": [d]}))

    area_size = analysis.metrics["traceability"].sample_size if "traceability" in analysis.metrics else 0
    if len(analysis.unowned_docs) >= 2 or (analysis.unowned_docs and len(analysis.unowned_docs) >= 0.3 * area_size):
        docs = sorted(analysis.unowned_docs)
        out.append(IssueDraft(
            _fp("unowned", area_label, len(docs) // 5), "unowned", "traceability", "low", 0.9,
            f"{len(docs)} documents in {area_label} have no owner",
            "Without an owner nobody is accountable for keeping the information correct.",
            "Assign an owning team or person to each document.",
            {"document_ids": docs}))
    return out


def detect_orphan_issues(corpus: Corpus, unassigned: set[str]) -> list[IssueDraft]:
    return [IssueDraft(
        _fp("orphan", d), "orphan", "connectivity", "low", 0.6, f"Orphan document: “{corpus.docs[d].title}”",
        "The document does not belong to any knowledge area: it is weakly related to everything else.",
        "Link it from the area it belongs to, expand it, or archive it.", {"document_ids": [d]})
        for d in sorted(unassigned)]


def detect_terminology_issues(corpus: Corpus, doc_ids: set[str], area_label: str) -> tuple[list[IssueDraft], list[tuple[str, str]]]:
    """Different surface names that share a core key ("Payment API" / "Payment Service" / "Payments Backend")."""
    groups: dict[str, set[str]] = {}
    for d in doc_ids:
        for e in corpus.docs[d].entities:
            ent = corpus.entities.get(e)
            if ent is None or ent.entity_type not in ("system", "concept"):
                continue
            core = (ent.meta or {}).get("core_key")
            if core and len(core) > 2 and corpus.entity_df[e] >= 1:
                groups.setdefault(core, set()).add(e)
    issues, pairs = [], []
    for _core, ents in groups.items():
        if len(ents) < 2:
            continue
        names = sorted(corpus.entities[e].canonical_name for e in ents)
        docs = sorted({d for d in doc_ids if corpus.docs[d].entities & ents})
        ent_list = sorted(ents)
        pairs.extend((ent_list[0], other) for other in ent_list[1:])
        issues.append(IssueDraft(
            _fp("terminology", *ent_list), "ambiguous_terminology", "clarity", "low", 0.5,
            f"Ambiguous naming in {area_label}: " + " / ".join(f"“{n}”" for n in names[:4]),
            "Several names that may refer to the same thing are used across documents. The engine did not merge "
            "them automatically (candidate alias).",
            "Confirm whether they are the same component; if so, agree on one canonical name and add aliases.",
            {"document_ids": docs, "entity_ids": ent_list, "names": names}))
    return issues, pairs
