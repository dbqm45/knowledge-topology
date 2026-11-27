"""Loads the analysable corpus (active documents + current chunks + vectors) into memory."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from kt.db.orm import Chunk, Document, DocumentLink, Entity, EntityMention
from kt.entities.extraction import Claim, extract_claims
from kt.semantic.text import content_terms, sentences, stem
from kt.storage.vector import VectorStore


@dataclass
class DocInfo:
    id: str
    title: str
    uri: str | None
    source_id: str
    path: list[str]
    owner: str | None
    document_type: str | None
    updated_at: datetime | None
    has_version: bool
    chunks: list[Chunk] = field(default_factory=list)
    vector: np.ndarray | None = None
    entities: set[str] = field(default_factory=set)  # entity ids
    terms: Counter = field(default_factory=Counter)
    claims: list[tuple[Claim, str]] = field(default_factory=list)  # (claim, chunk_id)
    links_out: set[str] = field(default_factory=set)
    shingles: set[int] = field(default_factory=set)

    @property
    def text(self) -> str:
        return "\n\n".join(c.content for c in self.chunks)

    @property
    def token_count(self) -> int:
        return sum(c.token_count for c in self.chunks)

    @property
    def headings(self) -> set[str]:
        return {h for c in self.chunks for h in (c.heading_path or [])}


@dataclass
class Corpus:
    docs: dict[str, DocInfo]
    entities: dict[str, Entity]
    entity_df: Counter

    @property
    def ids(self) -> list[str]:
        return sorted(self.docs)

    def matrix(self, ids: list[str]) -> np.ndarray:
        return np.stack([self.docs[i].vector for i in ids]) if ids else np.zeros((0, 0))


def _shingles(text: str, n: int = 5) -> set[int]:
    words = [w for w in content_terms(text)]
    return {hash(" ".join(words[i : i + n])) for i in range(max(0, len(words) - n + 1))}


def load_corpus(session: Session, tenant_id: str, vectors: VectorStore) -> Corpus:
    docs: dict[str, DocInfo] = {}
    for d in session.scalars(select(Document).where(Document.tenant_id == tenant_id, Document.status == "active")):
        docs[d.id] = DocInfo(d.id, d.title, d.canonical_uri, d.source_id, list(d.path or []), d.owner,
                             d.document_type, d.updated_at_source, d.current_version_id is not None)
    for c in session.scalars(select(Chunk).where(Chunk.tenant_id == tenant_id, Chunk.is_current.is_(True))
                             .order_by(Chunk.document_id, Chunk.ordinal)):
        if c.document_id in docs:
            docs[c.document_id].chunks.append(c)
    # Document vector = token-weighted mean of chunk vectors (re-normalised).
    all_chunk_ids = [c.id for d in docs.values() for c in d.chunks]
    vecs = vectors.fetch(all_chunk_ids)
    for d in docs.values():
        rows = [(vecs[c.id], max(c.token_count, 1)) for c in d.chunks if c.id in vecs]
        if rows:
            m = np.average(np.stack([r for r, _ in rows]), axis=0, weights=[w for _, w in rows])
            n = np.linalg.norm(m)
            d.vector = (m / n if n else m).astype(np.float32)
    docs = {k: v for k, v in docs.items() if v.vector is not None}
    for doc_id, ent_id in session.execute(select(EntityMention.document_id, EntityMention.entity_id)
                                          .where(EntityMention.tenant_id == tenant_id)):
        if doc_id in docs:
            docs[doc_id].entities.add(ent_id)
    for link in session.scalars(select(DocumentLink).where(DocumentLink.tenant_id == tenant_id,
                                                           DocumentLink.to_document_id.is_not(None))):
        if link.from_document_id in docs and link.to_document_id in docs:
            docs[link.from_document_id].links_out.add(link.to_document_id)
    for d in docs.values():
        d.terms = Counter()
        for _ in range(3):
            d.terms.update(stem(t) for t in content_terms(d.title))
        for h in d.headings:
            d.terms.update(stem(t) for t in content_terms(h))
        d.terms.update(stem(t) for t in content_terms(d.text))
        for c in d.chunks:
            if c.kind != "code":
                d.claims.extend((cl, c.id) for cl in extract_claims(c.content))
        d.shingles = _shingles(d.text)
    entity_df: Counter = Counter()
    for d in docs.values():
        entity_df.update(d.entities)
    used = set(entity_df)
    entities = {e.id: e for e in session.scalars(select(Entity).where(Entity.tenant_id == tenant_id))
                if e.id in used}
    return Corpus(docs, entities, entity_df)


def doc_sentence_stats(text: str) -> tuple[float, int]:
    sents = [s for s in sentences(text) if len(s.split()) > 2]
    if not sents:
        return 0.0, 0
    return sum(len(s.split()) for s in sents) / len(sents), len(sents)


def group_by(items, key):
    out = defaultdict(list)
    for it in items:
        out[key(it)].append(it)
    return out
