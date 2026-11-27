"""Ingestion: connector changes -> canonical documents, versions, ACL, chunks, vectors, entity mentions.

Idempotent and incremental:
* unchanged content (same hash) -> only metadata/ACL are refreshed, nothing is re-embedded;
* ACL change -> DB ACL + vector payload updated immediately, no re-embedding;
* delete -> document marked deleted (history kept), vectors and mentions removed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from kt.config import Settings, get_settings
from kt.connectors.base import KnowledgeConnector, get_connector
from kt.db.orm import (
    AuditEvent,
    Chunk,
    Document,
    DocumentAcl,
    DocumentLink,
    DocumentVersion,
    Entity,
    EntityMention,
    Source,
    SyncJob,
    Tenant,
)
from kt.domain.models import NormalizedDocument
from kt.entities.extraction import extract_mentions
from kt.semantic.chunking import chunk_document
from kt.semantic.embeddings import Embedder
from kt.storage.vector import VectorPoint, VectorStore

log = logging.getLogger(__name__)


@dataclass
class SyncStats:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    acl_changed: int = 0
    deleted: int = 0
    chunks_embedded: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class IngestionService:
    def __init__(self, session: Session, embedder: Embedder, vectors: VectorStore, settings: Settings | None = None):
        self.s = session
        self.embedder = embedder
        self.vectors = vectors
        self.settings = settings or get_settings()

    # -- public API -----------------------------------------------------------
    def register_source(self, tenant_id: str, connector_type: str, name: str, config: dict,
                        external_id: str | None = None) -> Source:
        external_id = external_id or config.get("path") or config.get("base_url") or name
        src = self.s.scalar(select(Source).where(Source.tenant_id == tenant_id,
                                                 Source.connector_type == connector_type,
                                                 Source.external_id == str(external_id)))
        if src is None:
            src = Source(tenant_id=tenant_id, connector_type=connector_type, external_id=str(external_id),
                         name=name, config=config)
            self.s.add(src)
        else:
            src.config, src.name = config, name
        self.s.flush()
        return src

    def sync(self, source: Source, connector: KnowledgeConnector | None = None, full: bool = False,
             only_external_ids: list[str] | None = None) -> SyncStats:
        connector = connector or get_connector(source.connector_type, source.config)
        stats = SyncStats()
        job = SyncJob(tenant_id=source.tenant_id, source_id=source.id,
                      mode="webhook" if only_external_ids else ("full" if full or not source.sync_cursor else "incremental"))
        self.s.add(job)
        self.s.flush()
        try:
            connector.validate()
            if only_external_ids:
                events_ids = [(eid, "upsert") for eid in only_external_ids]
                next_cursor, complete = source.sync_cursor, False
            else:
                cursor = None if full else source.sync_cursor
                batch = connector.list_changes(cursor)
                events_ids = [(e.external_id, e.type) for e in batch.events]
                next_cursor, complete = batch.next_cursor, batch.complete and cursor is None
            touched: list[str] = []
            for external_id, etype in events_ids:
                try:
                    if etype == "delete":
                        if self._delete(source, external_id):
                            stats.deleted += 1
                        continue
                    doc = connector.fetch_document(external_id)
                    if doc is None:
                        if self._delete(source, external_id):
                            stats.deleted += 1
                        continue
                    touched.append(self._upsert(source, doc, stats))
                except Exception as exc:  # one bad page must not stop the sync
                    log.exception("Failed to ingest %s", external_id)
                    stats.errors.append(f"{external_id}: {exc}")
            if complete:
                listed = {eid for eid, t in events_ids if t != "delete"}
                for doc in self.s.scalars(select(Document).where(Document.source_id == source.id,
                                                                 Document.status == "active")):
                    if doc.external_id not in listed:
                        self._delete(source, doc.external_id)
                        stats.deleted += 1
            self._resolve_links(source.tenant_id)
            source.sync_cursor = next_cursor
            source.last_synced_at = datetime.now(timezone.utc)
            source.status = "ok" if not stats.errors else "partial"
            source.last_error = "; ".join(stats.errors[:5]) or None
            job.status = "ok" if not stats.errors else "partial"
            if stats.created or stats.updated or stats.deleted or stats.acl_changed:
                self._mark_topology_dirty(source.tenant_id)
        except Exception as exc:
            source.status, source.last_error = "error", str(exc)
            job.status, job.error = "error", str(exc)
            raise
        finally:
            job.stats = stats.as_dict()
            job.finished_at = datetime.now(timezone.utc)
            self.s.add(AuditEvent(tenant_id=source.tenant_id, actor="system:ingestion", action="source.sync",
                                  object_type="source", object_id=source.id, details=stats.as_dict()))
            self.s.flush()
        return stats

    # -- internals ------------------------------------------------------------
    def _mark_topology_dirty(self, tenant_id: str) -> None:
        tenant = self.s.get(Tenant, tenant_id)
        if tenant:
            tenant.settings = {**(tenant.settings or {}), "topology_dirty": True}

    def _set_acl(self, doc: Document, principals: list[str]) -> bool:
        current = set(self.s.scalars(select(DocumentAcl.principal).where(DocumentAcl.document_id == doc.id)))
        wanted = set(principals)
        if current == wanted:
            return False
        self.s.execute(delete(DocumentAcl).where(DocumentAcl.document_id == doc.id))
        for p in sorted(wanted):
            self.s.add(DocumentAcl(tenant_id=doc.tenant_id, document_id=doc.id, principal=p))
        return True

    def _upsert(self, source: Source, nd: NormalizedDocument, stats: SyncStats) -> str:
        tenant_id = source.tenant_id
        doc = self.s.scalar(select(Document).where(Document.source_id == source.id,
                                                   Document.external_id == nd.external_id))
        created = doc is None
        if created:
            doc = Document(tenant_id=tenant_id, source_id=source.id, external_id=nd.external_id, title=nd.title)
            self.s.add(doc)
            self.s.flush()
        doc.title, doc.canonical_uri, doc.document_type = nd.title, nd.url, nd.document_type
        doc.language, doc.parent_external_id, doc.path = nd.language, nd.parent_external_id, nd.path
        doc.owner, doc.author = nd.owner, nd.author
        doc.created_at_source, doc.updated_at_source = _utc(nd.created_at), _utc(nd.updated_at)
        doc.status, doc.deleted_at = "active", None
        doc.updated_at = datetime.now(timezone.utc)

        acl_changed = self._set_acl(doc, nd.principals)
        content_hash = nd.content_hash()
        current = self.s.get(DocumentVersion, doc.current_version_id) if doc.current_version_id else None
        if current is not None and current.content_hash == content_hash:
            if acl_changed:
                self.vectors.set_document_acl(tenant_id, doc.id, nd.principals)
                stats.acl_changed += 1
            else:
                stats.unchanged += 1
            self._replace_links(doc, nd.links)
            return doc.id

        version = self.s.scalar(select(DocumentVersion).where(DocumentVersion.document_id == doc.id,
                                                              DocumentVersion.content_hash == content_hash))
        if version is None:
            version = DocumentVersion(tenant_id=tenant_id, document_id=doc.id, source_version=nd.source_version,
                                      content_hash=content_hash, sections=[s.model_dump() for s in nd.sections],
                                      extracted_metadata=nd.raw_metadata)
            self.s.add(version)
            self.s.flush()
        doc.current_version_id = version.id

        # Replace current chunks, vectors and mentions.
        self.s.execute(update(Chunk).where(Chunk.document_id == doc.id, Chunk.is_current.is_(True))
                       .values(is_current=False))
        self.s.execute(delete(EntityMention).where(EntityMention.document_id == doc.id))
        self.vectors.delete_document(tenant_id, doc.id)

        drafts = chunk_document(nd, self.settings.chunk_target_tokens, self.settings.chunk_max_tokens,
                                self.settings.chunk_overlap_ratio)
        vectors = self.embedder.embed([d.embedding_text(nd.title) for d in drafts]) if drafts else []
        points: list[VectorPoint] = []
        entity_cache: dict[str, Entity] = {}
        for draft, vec in zip(drafts, vectors):
            chunk = Chunk(tenant_id=tenant_id, document_id=doc.id, document_version_id=version.id,
                          ordinal=draft.ordinal, heading_path=draft.heading_path, kind=draft.kind,
                          content=draft.content, content_hash=draft.content_hash, token_count=draft.token_count)
            self.s.add(chunk)
            self.s.flush()
            points.append(VectorPoint(chunk.id, vec, {
                "tenant_id": tenant_id, "document_id": doc.id, "document_version_id": version.id,
                "source_id": source.id, "principals": list(nd.principals), "language": nd.language,
                "embedding_model": self.embedder.model_id, "content_hash": draft.content_hash,
            }))
            for m in extract_mentions(draft.embedding_text(nd.title) if draft.ordinal == 0 else draft.content):
                ent = entity_cache.get(m.normalized_key) or self.s.scalar(
                    select(Entity).where(Entity.tenant_id == tenant_id, Entity.normalized_key == m.normalized_key))
                if ent is None:
                    ent = Entity(tenant_id=tenant_id, canonical_name=m.surface, normalized_key=m.normalized_key,
                                 entity_type=m.entity_type, aliases=[m.surface], meta={"core_key": m.core_key})
                    self.s.add(ent)
                    self.s.flush()
                elif m.surface not in (ent.aliases or []):
                    ent.aliases = [*(ent.aliases or []), m.surface]
                entity_cache[m.normalized_key] = ent
                self.s.add(EntityMention(tenant_id=tenant_id, entity_id=ent.id, document_id=doc.id,
                                         chunk_id=chunk.id, surface=m.surface))
        self.vectors.upsert(points)
        stats.chunks_embedded += len(points)
        self._replace_links(doc, nd.links)
        if created:
            stats.created += 1
        else:
            stats.updated += 1
        return doc.id

    def _replace_links(self, doc: Document, links: list[str]) -> None:
        self.s.execute(delete(DocumentLink).where(DocumentLink.from_document_id == doc.id))
        for ref in dict.fromkeys(links):
            self.s.add(DocumentLink(tenant_id=doc.tenant_id, from_document_id=doc.id, target_ref=ref))

    def _resolve_links(self, tenant_id: str) -> None:
        docs = list(self.s.scalars(select(Document).where(Document.tenant_id == tenant_id,
                                                          Document.status == "active")))
        by_ext = {(d.source_id, d.external_id): d.id for d in docs}
        by_title = {d.title.strip().lower(): d.id for d in docs}
        by_uri = {d.canonical_uri: d.id for d in docs if d.canonical_uri}
        src_of = {d.id: d.source_id for d in docs}
        for link in self.s.scalars(select(DocumentLink).where(DocumentLink.tenant_id == tenant_id)):
            ref = link.target_ref
            target = None
            if ref.startswith("title:"):
                target = by_title.get(ref[6:].strip().lower())
            elif ref in by_uri:
                target = by_uri[ref]
            else:
                target = by_ext.get((src_of.get(link.from_document_id), ref))
                if target is None and "/pages/" in ref:  # Confluence URL -> page id
                    page_id = ref.split("/pages/")[1].split("/")[0]
                    target = by_ext.get((src_of.get(link.from_document_id), page_id))
            link.to_document_id = target if target != link.from_document_id else None

    def _delete(self, source: Source, external_id: str) -> bool:
        doc = self.s.scalar(select(Document).where(Document.source_id == source.id,
                                                   Document.external_id == external_id))
        if doc is None or doc.status == "deleted":
            return False
        doc.status, doc.deleted_at = "deleted", datetime.now(timezone.utc)
        self.s.execute(update(Chunk).where(Chunk.document_id == doc.id).values(is_current=False))
        self.s.execute(delete(EntityMention).where(EntityMention.document_id == doc.id))
        self.vectors.delete_document(source.tenant_id, doc.id)
        return True
