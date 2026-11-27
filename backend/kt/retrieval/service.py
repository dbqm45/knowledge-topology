"""Hybrid retrieval (vector + BM25, reciprocal rank fusion) with server-side ACL and a token budget.

The agent receives only the minimal evidence needed: a few chunks per document, deduplicated,
within ``max_tokens``, with source links, versions, related entities and quality warnings
(suspected conflicts, stale sources) taken from the knowledge topology.
"""

from __future__ import annotations

import threading
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kt.access.service import AccessService
from kt.config import Settings, get_settings
from kt.db.orm import (
    Chunk,
    ClusterMembership,
    Document,
    DocumentVersion,
    Entity,
    EntityMention,
    Issue,
    KnowledgeDomain,
)
from kt.entities.extraction import extract_mentions
from kt.semantic.embeddings import Embedder
from kt.semantic.lexical import BM25Index
from kt.storage.vector import VectorStore
from kt.topology.engine import latest_snapshot

RRF_K = 60
_LEXICAL_CACHE: dict[str, tuple[tuple, BM25Index, dict[str, str]]] = {}
_LOCK = threading.Lock()


def _lexical_index(session: Session, tenant_id: str) -> tuple[BM25Index, dict[str, str]]:
    signature = tuple(session.execute(
        select(func.count(Chunk.id), func.max(DocumentVersion.ingested_at))
        .select_from(Chunk).join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
        .where(Chunk.tenant_id == tenant_id, Chunk.is_current.is_(True))).one())
    deleted = session.scalar(select(func.count(Document.id)).where(Document.tenant_id == tenant_id,
                                                                  Document.status == "deleted"))
    signature = (*signature, deleted)
    with _LOCK:
        cached = _LEXICAL_CACHE.get(tenant_id)
        if cached and cached[0] == signature:
            return cached[1], cached[2]
        index, chunk_doc = BM25Index(), {}
        rows = session.execute(select(Chunk.id, Chunk.document_id, Chunk.content, Chunk.heading_path, Document.title)
                               .join(Document, Document.id == Chunk.document_id)
                               .where(Chunk.tenant_id == tenant_id, Chunk.is_current.is_(True),
                                      Document.status == "active"))
        for cid, did, content, path, title in rows:
            index.add(cid, " ".join([title, *(path or [])]) + "\n" + content)
            chunk_doc[cid] = did
        _LEXICAL_CACHE[tenant_id] = (signature, index, chunk_doc)
        return index, chunk_doc


def resolve_domain_id(session: Session, tenant_id: str, ref: str) -> str | None:
    row = session.scalar(select(KnowledgeDomain).where(KnowledgeDomain.tenant_id == tenant_id,
                                                       (KnowledgeDomain.id == ref) | (KnowledgeDomain.stable_key == ref)))
    return row.id if row else None


def domain_documents(session: Session, tenant_id: str, domain_ref: str) -> set[str]:
    snap = latest_snapshot(session, tenant_id)
    domain_id = resolve_domain_id(session, tenant_id, domain_ref)
    if not snap or not domain_id:
        return set()
    child_ids = set(session.scalars(select(KnowledgeDomain.id).where(KnowledgeDomain.parent_id == domain_id)))
    return set(session.scalars(select(ClusterMembership.document_id).where(
        ClusterMembership.snapshot_id == snap.id, ClusterMembership.domain_id.in_({domain_id, *child_ids}))))


class RetrievalService:
    def __init__(self, session: Session, access: AccessService, embedder: Embedder, vectors: VectorStore,
                 settings: Settings | None = None):
        self.s, self.access, self.embedder, self.vectors = session, access, embedder, vectors
        self.settings = settings or get_settings()

    def search(self, query: str, top_k: int = 8, domain_id: str | None = None, source_ids: list[str] | None = None,
               mode: str = "hybrid", include_related: bool = True, include_evidence: bool = True,
               updated_after: datetime | None = None, max_tokens: int | None = None,
               chunks_per_document: int = 2) -> dict:
        tenant = self.access.tenant_id
        max_tokens = max_tokens or self.settings.context_budget_tokens
        allowed = set(self.access.readable_document_ids())
        scoped = False
        if domain_id:
            allowed &= domain_documents(self.s, tenant, domain_id)
            scoped = True
        if source_ids:
            allowed &= set(self.s.scalars(select(Document.id).where(Document.source_id.in_(source_ids))))
            scoped = True
        if updated_after:
            ua = updated_after if updated_after.tzinfo else updated_after.replace(tzinfo=timezone.utc)
            allowed &= {d.id for d in self.s.scalars(select(Document).where(Document.id.in_(allowed)))
                        if d.updated_at_source and (d.updated_at_source if d.updated_at_source.tzinfo
                                                    else d.updated_at_source.replace(tzinfo=timezone.utc)) >= ua}
            scoped = True
        result = {"query": query, "results": [], "related_entities": [], "related_areas": [], "warnings": [],
                  "usage": {"candidates": 0, "returned_chunks": 0, "estimated_tokens": 0, "budget_tokens": max_tokens}}
        if not allowed or not query.strip():
            return result

        n = self.settings.retrieval_candidates
        ranked: dict[str, dict] = {}
        if mode in ("hybrid", "vector"):
            hits = self.vectors.search(tenant, self.embedder.embed_one(query), n, self.access.vector_tokens(),
                                       allowed if scoped else None)
            hits = [h for h in hits if h.payload.get("document_id") in allowed]  # authoritative ACL re-check
            if hits:
                floor = max(self.settings.retrieval_min_similarity, self.settings.retrieval_relative_floor * hits[0].score)
                hits = [h for h in hits if h.score >= floor]
            for rank, h in enumerate(hits):
                e = ranked.setdefault(h.id, {"score": 0.0, "reasons": set(), "doc": h.payload["document_id"]})
                e["score"] += 1 / (RRF_K + rank)
                e["reasons"].add("semantic_match")
                e["cosine"] = round(h.score, 4)
        if mode in ("hybrid", "lexical"):
            index, chunk_doc = _lexical_index(self.s, tenant)
            allowed_chunks = {c for c, d in chunk_doc.items() if d in allowed}
            for rank, (cid, _) in enumerate(index.search(query, n, allowed_chunks)):
                e = ranked.setdefault(cid, {"score": 0.0, "reasons": set(), "doc": chunk_doc[cid]})
                e["score"] += 1 / (RRF_K + rank)
                e["reasons"].add("lexical_match")
        result["usage"]["candidates"] = len(ranked)
        if not ranked:
            return result

        chunks = {c.id: c for c in self.s.scalars(select(Chunk).where(Chunk.id.in_(ranked), Chunk.is_current.is_(True)))}
        query_entities = {m.normalized_key for m in extract_mentions(query)}
        doc_entities: dict[str, set[str]] = {}
        if query_entities:
            for did, key in self.s.execute(select(EntityMention.document_id, Entity.normalized_key)
                                           .join(Entity, Entity.id == EntityMention.entity_id)
                                           .where(EntityMention.document_id.in_({e["doc"] for e in ranked.values()}))):
                doc_entities.setdefault(did, set()).add(key)
        by_doc: dict[str, list[tuple[str, dict]]] = {}
        for cid, e in sorted(ranked.items(), key=lambda x: -x[1]["score"]):
            if cid not in chunks:
                continue
            if e["reasons"] == {"semantic_match"} and e.get("cosine", 1.0) < self.settings.retrieval_vector_only_min:
                continue
            if query_entities & doc_entities.get(e["doc"], set()):
                e["reasons"].add("entity_match")
                e["score"] *= 1.15
            if scoped:
                e["reasons"].add("scope_match")
            by_doc.setdefault(e["doc"], []).append((cid, e))
        if not by_doc:
            return result
        doc_order = sorted(by_doc, key=lambda d: -max(e["score"] for _, e in by_doc[d]))[:top_k]
        docs = {d.id: d for d in self.s.scalars(select(Document).where(Document.id.in_(doc_order)))}
        versions = {v.id: v for v in self.s.scalars(select(DocumentVersion).where(
            DocumentVersion.id.in_([d.current_version_id for d in docs.values() if d.current_version_id])))}
        best = max(e["score"] for v in by_doc.values() for _, e in v)
        used_tokens, used_hashes, returned = 0, set(), 0
        for did in doc_order:
            doc = docs[did]
            evidence = []
            for cid, e in sorted(by_doc[did], key=lambda x: -x[1]["score"])[:chunks_per_document]:
                c = chunks[cid]
                if c.content_hash in used_hashes:
                    continue  # identical content already returned (e.g. a copied page)
                if used_tokens + c.token_count > max_tokens and returned > 0:
                    continue
                used_hashes.add(c.content_hash)
                used_tokens += c.token_count
                returned += 1
                evidence.append({"chunk_id": cid, "section": " > ".join(c.heading_path or []) or None,
                                 "quote": c.content if include_evidence else None,
                                 "relevance": round(e["score"] / best, 3), "tokens": c.token_count})
            if not evidence:
                continue
            top = max(by_doc[did], key=lambda x: x[1]["score"])[1]
            version = versions.get(doc.current_version_id)
            result["results"].append({
                "document_id": did, "title": doc.title, "uri": doc.canonical_uri,
                "score": round(top["score"] / best, 3),
                "retrieval_reasons": sorted(set().union(*(e["reasons"] for _, e in by_doc[did]))),
                "evidence": evidence, "version": version.source_version if version else None,
                "updated_at": doc.updated_at_source.isoformat() if doc.updated_at_source else None,
                "owner": doc.owner,
            })
        result["usage"].update(returned_chunks=returned, estimated_tokens=used_tokens)
        result_docs = [r["document_id"] for r in result["results"]]
        if include_related and result_docs:
            result["related_entities"] = self._related_entities(result_docs)
            result["related_areas"] = self._related_areas(result_docs)
        result["warnings"] = self._warnings(result_docs)
        return result

    def _related_entities(self, doc_ids: list[str], limit: int = 8) -> list[dict]:
        cnt: Counter = Counter()
        for (eid,) in self.s.execute(select(EntityMention.entity_id).where(EntityMention.document_id.in_(doc_ids))):
            cnt[eid] += 1
        ents = {e.id: e for e in self.s.scalars(select(Entity).where(Entity.id.in_(list(cnt))))}
        return [{"id": e, "name": ents[e].canonical_name, "type": ents[e].entity_type, "mentions": c}
                for e, c in cnt.most_common(limit * 2) if e in ents and ents[e].entity_type != "identifier"][:limit]

    def _related_areas(self, doc_ids: list[str]) -> list[dict]:
        snap = latest_snapshot(self.s, self.access.tenant_id)
        if not snap:
            return []
        readable = self.access.readable_document_ids()
        out = []
        for dm in snap.payload.get("domains", []):
            if dm["level"] == 1 and set(dm["document_ids"]) & set(doc_ids):
                full = self.access.p.is_admin or set(dm["document_ids"]) <= readable
                out.append({"domain_id": dm["id"], "stable_key": dm["stable_key"],
                            "label": dm["label"] if full else None, "health": dm["health"] if full else None})
        return out

    def _warnings(self, doc_ids: list[str]) -> list[dict]:
        if not doc_ids:
            return []
        readable = self.access.readable_document_ids()
        warnings = []
        for issue in self.s.scalars(select(Issue).where(Issue.tenant_id == self.access.tenant_id,
                                                        Issue.status.in_(("open", "investigating", "accepted")),
                                                        Issue.issue_type.in_(("conflict", "stale", "duplicate")))):
            ev_docs = set((issue.evidence or {}).get("document_ids", []))
            if ev_docs & set(doc_ids) and ev_docs <= readable:
                warnings.append({"type": issue.issue_type, "issue_id": issue.id, "severity": issue.severity,
                                 "message": issue.title, "document_ids": sorted(ev_docs)})
        order = {"conflict": 0, "duplicate": 1, "stale": 2}
        return sorted(warnings, key=lambda w: order[w["type"]])[:8]
