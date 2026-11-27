"""Relational source of truth (PostgreSQL in production, SQLite for local/dev/tests).

Embeddings live in the vector store (Qdrant / local file); everything else lives here.
All rows carry ``tenant_id`` — queries must always filter on it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonType = JSON().with_variant(JSONB(), "postgresql")


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    deployment_mode: Mapped[str] = mapped_column(String(32), default="hybrid_standard")
    settings: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("tenant_id", "connector_type", "external_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    connector_type: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(512))
    name: Mapped[str] = mapped_column(String(255))
    config: Mapped[dict] = mapped_column(JsonType, default=dict)
    sync_cursor: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id"),
        Index("ix_documents_tenant_status", "tenant_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(512))
    canonical_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text)
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    parent_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    path: Mapped[list] = mapped_column(JsonType, default=list)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "content_hash"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(80))
    sections: Mapped[list] = mapped_column(JsonType, default=list)
    extracted_metadata: Mapped[dict] = mapped_column(JsonType, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_doc_current", "document_id", "is_current"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"))
    ordinal: Mapped[int] = mapped_column(Integer)
    heading_path: Mapped[list] = mapped_column(JsonType, default=list)
    kind: Mapped[str] = mapped_column(String(16), default="text")
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(80))
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class DocumentAcl(Base):
    __tablename__ = "document_acl"
    __table_args__ = (UniqueConstraint("document_id", "principal"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    principal: Mapped[str] = mapped_column(String(255), index=True)


class DocumentLink(Base):
    __tablename__ = "document_links"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    from_document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    target_ref: Mapped[str] = mapped_column(Text)
    to_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("tenant_id", "normalized_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    canonical_name: Mapped[str] = mapped_column(String(512))
    normalized_key: Mapped[str] = mapped_column(String(512))
    entity_type: Mapped[str] = mapped_column(String(32))
    aliases: Mapped[list] = mapped_column(JsonType, default=list)
    status: Mapped[str] = mapped_column(String(16), default="canonical")  # canonical|candidate|rejected
    meta: Mapped[dict] = mapped_column("metadata", JsonType, default=dict)


class EntityMention(Base):
    __tablename__ = "entity_mentions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    chunk_id: Mapped[str] = mapped_column(String(36))
    surface: Mapped[str] = mapped_column(String(512))


class Relation(Base):
    """Typed, weighted, evidence-backed edge. Endpoints are (type, id) pairs so the same table
    holds document–document, document–entity, entity–entity and domain–domain edges."""

    __tablename__ = "relations"
    __table_args__ = (Index("ix_relations_from", "tenant_id", "from_type", "from_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    relation_type: Mapped[str] = mapped_column(String(48))
    from_type: Mapped[str] = mapped_column(String(16))
    from_id: Mapped[str] = mapped_column(String(36))
    to_type: Mapped[str] = mapped_column(String(16))
    to_id: Mapped[str] = mapped_column(String(36))
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    provenance: Mapped[str] = mapped_column(String(48))
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeDomain(Base):
    __tablename__ = "knowledge_domains"
    __table_args__ = (UniqueConstraint("tenant_id", "stable_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    stable_key: Mapped[str] = mapped_column(String(64))
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    last_seen_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClusterMembership(Base):
    __tablename__ = "cluster_memberships"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "domain_id", "document_id"),
        Index("ix_membership_snapshot_doc", "snapshot_id", "document_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("topology_snapshots.id"))
    domain_id: Mapped[str] = mapped_column(ForeignKey("knowledge_domains.id"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    membership_weight: Mapped[float] = mapped_column(Float)
    membership_type: Mapped[str] = mapped_column(String(24))  # core|peripheral|low_confidence


class TopologySnapshot(Base):
    __tablename__ = "topology_snapshots"
    __table_args__ = (Index("ix_snapshots_tenant_created", "tenant_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    scope_type: Mapped[str] = mapped_column(String(16), default="global")
    algorithm_version: Mapped[str] = mapped_column(String(32))
    embedding_model: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="running")
    params: Mapped[dict] = mapped_column(JsonType, default=dict)
    # Full computed topology (domains, geometry, edges, layout). Object storage in large deployments.
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    stats: Mapped[dict] = mapped_column(JsonType, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QualityMetric(Base):
    __tablename__ = "quality_metrics"
    __table_args__ = (UniqueConstraint("snapshot_id", "domain_id", "metric_name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("topology_snapshots.id"), index=True)
    domain_id: Mapped[str] = mapped_column(ForeignKey("knowledge_domains.id"))
    metric_name: Mapped[str] = mapped_column(String(32))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    measured: Mapped[bool] = mapped_column(Boolean, default=True)
    signals: Mapped[dict] = mapped_column(JsonType, default=dict)


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (UniqueConstraint("tenant_id", "fingerprint"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    fingerprint: Mapped[str] = mapped_column(String(80))
    snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    domain_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    issue_type: Mapped[str] = mapped_column(String(32))
    metric: Mapped[str | None] = mapped_column(String(32), nullable=True)
    severity: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="open")
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_detected_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SnapshotClusterLineage(Base):
    __tablename__ = "snapshot_cluster_lineage"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("topology_snapshots.id"), index=True)
    domain_id: Mapped[str] = mapped_column(ForeignKey("knowledge_domains.id"))
    previous_domain_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    relation: Mapped[str] = mapped_column(String(16))  # new|continued|split_from|merged_from
    overlap: Mapped[float] = mapped_column(Float, default=0.0)


class SyncJob(Base):
    __tablename__ = "sync_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    mode: Mapped[str] = mapped_column(String(16))  # full|incremental|webhook
    status: Mapped[str] = mapped_column(String(16), default="running")
    stats: Mapped[dict] = mapped_column(JsonType, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_tenant_created", "tenant_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(64))
    object_type: Mapped[str] = mapped_column(String(32))
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
