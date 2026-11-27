"""KnowledgeService — the one facade both REST and MCP call. No transport-specific logic lives here,
and no transport implements its own retrieval or authorization."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from kt.access.service import AccessService, NotFound
from kt.config import Settings, get_settings
from kt.db.orm import (
    AuditEvent,
    Chunk,
    Document,
    DocumentAcl,
    Entity,
    EntityMention,
    Issue,
    QualityMetric,
    Relation,
    Source,
    TopologySnapshot,
)
from kt.domain.models import Principal
from kt.retrieval.service import RetrievalService, resolve_domain_id
from kt.semantic.embeddings import Embedder
from kt.storage.vector import VectorStore
from kt.topology.views import domain_map_view, get_snapshot, topology_view, view_domain, visible_issue_ids

ISSUE_STATUSES = ("open", "investigating", "accepted", "resolved", "dismissed")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


class KnowledgeService:
    def __init__(self, session: Session, principal: Principal, embedder: Embedder, vectors: VectorStore,
                 settings: Settings | None = None):
        self.s = session
        self.p = principal
        self.access = AccessService(session, principal)
        self.embedder, self.vectors = embedder, vectors
        self.settings = settings or get_settings()
        self.retrieval = RetrievalService(session, self.access, embedder, vectors, self.settings)

    # ---------------------------------------------------------------- retrieval
    def search(self, query: str, **kwargs) -> dict:
        return self.retrieval.search(query, **kwargs)

    def get_document(self, document_id: str, include_content: bool = True, max_tokens: int | None = None) -> dict:
        doc = self.access.get_document(document_id)
        chunks = list(self.s.scalars(select(Chunk).where(Chunk.document_id == doc.id, Chunk.is_current.is_(True))
                                     .order_by(Chunk.ordinal)))
        budget = max_tokens or 100_000
        sections, used, truncated = [], 0, False
        for c in chunks:
            if used + c.token_count > budget and sections:
                truncated = True
                break
            used += c.token_count
            sections.append({"chunk_id": c.id, "section": " > ".join(c.heading_path or []) or None, "kind": c.kind,
                             "content": c.content if include_content else None})
        snap_doc = self._snapshot_doc(doc.id)
        return {"document_id": doc.id, "title": doc.title, "uri": doc.canonical_uri, "owner": doc.owner,
                "document_type": doc.document_type, "path": doc.path, "updated_at": _iso(doc.updated_at_source),
                "domain": snap_doc.get("domain"), "flags": snap_doc.get("flags", []),
                "issue_ids": visible_issue_ids(self.s, self.access, snap_doc.get("issue_ids", [])),
                "sections": sections, "estimated_tokens": used, "truncated": truncated}

    def get_document_context(self, document_id: str, chunk_id: str | None = None, window: int = 1) -> dict:
        """A chunk with its neighbouring chunks (cheap context expansion instead of the full page)."""
        doc = self.access.get_document(document_id)
        chunks = list(self.s.scalars(select(Chunk).where(Chunk.document_id == doc.id, Chunk.is_current.is_(True))
                                     .order_by(Chunk.ordinal)))
        idx = next((i for i, c in enumerate(chunks) if c.id == chunk_id), 0)
        sel = chunks[max(0, idx - window): idx + window + 1]
        return {"document_id": doc.id, "title": doc.title, "uri": doc.canonical_uri,
                "chunks": [{"chunk_id": c.id, "ordinal": c.ordinal, "section": " > ".join(c.heading_path or []),
                            "content": c.content} for c in sel]}

    def get_related(self, document_id: str, limit: int = 8) -> dict:
        self.access.get_document(document_id)
        readable = self.access.readable_document_ids()
        rels = self.s.scalars(select(Relation).where(
            Relation.tenant_id == self.p.tenant_id, Relation.from_type == "document", Relation.to_type == "document",
            (Relation.from_id == document_id) | (Relation.to_id == document_id)))
        best: dict[str, dict] = {}
        for r in rels:
            other = r.to_id if r.from_id == document_id else r.from_id
            if other not in readable:
                continue
            e = best.setdefault(other, {"document_id": other, "relations": [], "weight": 0.0})
            e["relations"].append(r.relation_type)
            e["weight"] = max(e["weight"], r.weight)
        docs = {d.id: d for d in self.s.scalars(select(Document).where(Document.id.in_(list(best))))}
        items = sorted(best.values(), key=lambda x: -x["weight"])[:limit]
        for it in items:
            it["title"], it["uri"] = docs[it["document_id"]].title, docs[it["document_id"]].canonical_uri
            it["relations"] = sorted(set(it["relations"]))
        ents = self.s.execute(select(Entity.id, Entity.canonical_name, Entity.entity_type)
                              .join(EntityMention, EntityMention.entity_id == Entity.id)
                              .where(EntityMention.document_id == document_id).distinct())
        return {"document_id": document_id, "related_documents": items,
                "entities": [{"id": i, "name": n, "type": t} for i, n, t in ents][:20]}

    # ---------------------------------------------------------------- structure
    def topology(self, snapshot_id: str | None = None, include_geometry: bool = True,
                 include_documents: bool = False, level: int | None = 1) -> dict:
        return topology_view(self.s, self.access, snapshot_id, include_geometry, include_documents, level)

    def list_domains(self, snapshot_id: str | None = None, include_subareas: bool = True) -> list[dict]:
        view = topology_view(self.s, self.access, snapshot_id, include_geometry=False,
                             level=None if include_subareas else 1)
        return view["nodes"]

    def get_area(self, domain_ref: str, snapshot_id: str | None = None, include_documents: bool = True) -> dict:
        m = domain_map_view(self.s, self.access, domain_ref, snapshot_id)
        if not include_documents:
            m.pop("documents", None)
            m.pop("edges", None)
        return m

    def entity(self, entity_id: str) -> dict:
        ent = self.s.get(Entity, entity_id)
        if ent is None or ent.tenant_id != self.p.tenant_id:
            raise NotFound(entity_id)
        readable = self.access.readable_document_ids()
        doc_ids = {d for (d,) in self.s.execute(select(EntityMention.document_id).where(EntityMention.entity_id == ent.id))}
        doc_ids &= readable
        if not doc_ids:
            raise NotFound(entity_id)  # entities only exist for the caller through readable documents
        docs = self.s.scalars(select(Document).where(Document.id.in_(doc_ids)))
        return {"id": ent.id, "name": ent.canonical_name, "type": ent.entity_type, "aliases": ent.aliases,
                "status": ent.status, "documents": [{"document_id": d.id, "title": d.title, "uri": d.canonical_uri}
                                                    for d in docs]}

    def search_entities(self, q: str, limit: int = 20) -> list[dict]:
        readable = self.access.readable_document_ids()
        rows = self.s.execute(select(Entity.id, Entity.canonical_name, Entity.entity_type, EntityMention.document_id)
                              .join(EntityMention, EntityMention.entity_id == Entity.id)
                              .where(Entity.tenant_id == self.p.tenant_id, Entity.canonical_name.ilike(f"%{q}%")))
        out: dict[str, dict] = {}
        for eid, name, etype, did in rows:
            if did in readable:
                e = out.setdefault(eid, {"id": eid, "name": name, "type": etype, "documents": 0})
                e["documents"] += 1
        return sorted(out.values(), key=lambda e: -e["documents"])[:limit]

    # ---------------------------------------------------------------- intelligence
    def health(self, domain_ref: str, history: int = 10) -> dict:
        snap = get_snapshot(self.s, self.p.tenant_id, None)
        dm = next((d for d in snap.payload.get("domains", []) if domain_ref in (d["id"], d["stable_key"])), None)
        if dm is None:
            raise NotFound(domain_ref)
        v = view_domain(self.s, self.access, dm, snap.payload["documents"], include_geometry=True)
        if v is None:
            raise NotFound(domain_ref)
        out = {"domain_id": dm["id"], "stable_key": dm["stable_key"], "label": v["label"], "visibility": v["visibility"],
               "health": v["health"], "metrics": v["metrics"], "trend": [], "issues": [],
               "explanations": v["geometry"]["explanations"]}
        if v["visibility"] == "full":
            rows = self.s.execute(select(TopologySnapshot.id, TopologySnapshot.created_at, QualityMetric.metric_name,
                                         QualityMetric.score)
                                  .join(QualityMetric, QualityMetric.snapshot_id == TopologySnapshot.id)
                                  .where(QualityMetric.domain_id == dm["id"]).order_by(TopologySnapshot.created_at))
            trend: dict[str, dict] = {}
            for sid, created, name, score in rows:
                trend.setdefault(sid, {"snapshot_id": sid, "created_at": created.isoformat()})[name] = score
            out["trend"] = list(trend.values())[-history:]
            out["issues"] = self.list_issues(domain_id=dm["id"], status=None)
        return out

    def _issue_dict(self, i: Issue) -> dict:
        return {"id": i.id, "issue_type": i.issue_type, "metric": i.metric, "severity": i.severity,
                "confidence": i.confidence, "status": i.status, "title": i.title, "description": i.description,
                "recommendation": i.recommendation, "evidence": i.evidence, "domain_id": i.domain_id,
                "assigned_to": i.assigned_to, "created_at": _iso(i.created_at), "updated_at": _iso(i.updated_at),
                "resolved_at": _iso(i.resolved_at)}

    def list_issues(self, domain_id: str | None = None, status: str | None = "open", severity: str | None = None,
                    issue_type: str | None = None, limit: int = 200) -> list[dict]:
        q = select(Issue).where(Issue.tenant_id == self.p.tenant_id)
        if domain_id:
            rid = resolve_domain_id(self.s, self.p.tenant_id, domain_id)
            q = q.where(Issue.domain_id == rid)
        if status:
            q = q.where(Issue.status.in_(status.split(",")))
        if severity:
            q = q.where(Issue.severity.in_(severity.split(",")))
        if issue_type:
            q = q.where(Issue.issue_type.in_(issue_type.split(",")))
        readable = self.access.readable_document_ids()
        order = {"high": 0, "medium": 1, "low": 2}
        items = [self._issue_dict(i) for i in self.s.scalars(q)
                 if self.p.is_admin or set((i.evidence or {}).get("document_ids", [])) <= readable]
        return sorted(items, key=lambda x: (order.get(x["severity"], 3), -x["confidence"]))[:limit]

    def get_issue(self, issue_id: str) -> dict:
        i = self.s.get(Issue, issue_id)
        if i is None or i.tenant_id != self.p.tenant_id or not (
                self.p.is_admin or set((i.evidence or {}).get("document_ids", [])) <= self.access.readable_document_ids()):
            raise NotFound(issue_id)
        out = self._issue_dict(i)
        chunk_ids = (i.evidence or {}).get("chunk_ids", [])
        if chunk_ids:
            out["evidence_chunks"] = [{"chunk_id": c.id, "document_id": c.document_id, "content": c.content}
                                      for c in self.s.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids)))]
        docs = self.s.scalars(select(Document).where(Document.id.in_((i.evidence or {}).get("document_ids", []))))
        out["documents"] = [{"document_id": d.id, "title": d.title, "uri": d.canonical_uri, "owner": d.owner,
                             "updated_at": _iso(d.updated_at_source)} for d in docs]
        return out

    def update_issue(self, issue_id: str, status: str | None = None, assigned_to: str | None = None,
                     comment: str | None = None) -> dict:
        self.get_issue(issue_id)  # visibility check
        i = self.s.get(Issue, issue_id)
        changes = {}
        if status:
            if status not in ISSUE_STATUSES:
                raise ValueError(f"status must be one of {ISSUE_STATUSES}")
            changes["status"] = [i.status, status]
            i.status = status
            i.resolved_at = datetime.now(timezone.utc) if status in ("resolved", "dismissed") else None
        if assigned_to is not None:
            changes["assigned_to"] = [i.assigned_to, assigned_to]
            i.assigned_to = assigned_to or None
        i.updated_at = datetime.now(timezone.utc)
        self.s.add(AuditEvent(tenant_id=self.p.tenant_id, actor=self.p.id, action="issue.update", object_type="issue",
                              object_id=i.id, details={"changes": changes, "comment": comment}))
        self.s.flush()
        return self._issue_dict(i)

    def check_conflicts(self, query: str, domain_id: str | None = None, top_k: int = 10) -> dict:
        """Suspected contradictions among the documents relevant to ``query`` (visible ones only)."""
        res = self.search(query, top_k=top_k, domain_id=domain_id, include_related=False, include_evidence=False)
        doc_ids = {r["document_id"] for r in res["results"]}
        readable = self.access.readable_document_ids()
        conflicts = []
        for i in self.s.scalars(select(Issue).where(Issue.tenant_id == self.p.tenant_id, Issue.issue_type == "conflict",
                                                    Issue.status.not_in(("dismissed",)))):
            ev = set((i.evidence or {}).get("document_ids", []))
            if ev & doc_ids and ev <= readable:
                conflicts.append({"issue_id": i.id, "status": i.status, "confidence": i.confidence, "title": i.title,
                                  "claims": (i.evidence or {}).get("quotes", []),
                                  "confirmed": i.status == "accepted",
                                  "detection": "confirmed" if i.status == "accepted" else "suspected"})
        return {"query": query, "documents_checked": len(doc_ids), "conflicts": conflicts}

    def gaps(self, domain_ref: str) -> dict:
        h = self.health(domain_ref)
        if h["visibility"] != "full":
            return {"domain_id": h["domain_id"], "visibility": "partial", "gaps": []}
        cov = (h["metrics"] or {}).get("coverage", {})
        gaps = [{"type": "unexplained_concept", "name": n} for n in cov.get("signals", {}).get("unexplained", [])]
        gaps += [{"type": "missing_required_topic", "name": n} for n in cov.get("signals", {}).get("missing_required", [])]
        gaps += [{"type": i["issue_type"], "issue_id": i["id"], "title": i["title"]} for i in h["issues"]
                 if i["issue_type"] in ("stale", "orphan", "isolated") and i["status"] == "open"]
        return {"domain_id": h["domain_id"], "label": h["label"], "coverage": cov, "gaps": gaps,
                "note": "Observed coverage only reflects concepts found in the documents; configure coverage "
                        "templates for required-knowledge checks."}

    def evidence(self, chunk_ids: list[str]) -> list[dict]:
        out = []
        for c in self.s.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids))):
            if self.access.can_read(c.document_id):
                doc = self.s.get(Document, c.document_id)
                out.append({"chunk_id": c.id, "document_id": c.document_id, "title": doc.title, "uri": doc.canonical_uri,
                            "section": " > ".join(c.heading_path or []), "content": c.content,
                            "current": c.is_current})
        return out

    # ---------------------------------------------------------------- evolution
    def snapshots(self, limit: int = 50) -> list[dict]:
        rows = self.s.scalars(select(TopologySnapshot).where(TopologySnapshot.tenant_id == self.p.tenant_id,
                                                             TopologySnapshot.status == "ok")
                              .order_by(TopologySnapshot.created_at.desc()).limit(limit))
        return [{"snapshot_id": r.id, "created_at": _iso(r.created_at), "algorithm_version": r.algorithm_version,
                 "embedding_model": r.embedding_model,
                 "stats": r.stats if self.p.is_admin else {"domains": r.stats.get("domains")}} for r in rows]

    def compare(self, from_snapshot_id: str, to_snapshot_id: str | None = None) -> dict:
        a = topology_view(self.s, self.access, from_snapshot_id, include_geometry=False, level=None)
        b = topology_view(self.s, self.access, to_snapshot_id, include_geometry=False, level=None)
        ka = {d["stable_key"]: d for d in a["nodes"]}
        kb = {d["stable_key"]: d for d in b["nodes"]}
        changes = []
        for key, d in kb.items():
            lin = d.get("lineage") or {}
            if key not in ka:
                rel = lin.get("relation", "new")
                changes.append({"type": {"split_from": "area_split", "merged_from": "area_merged"}.get(rel, "area_added"),
                                "stable_key": key, "label": d["label"], "level": d["level"],
                                "previous_keys": lin.get("previous_keys", [])})
            else:
                old = ka[key]
                if lin.get("relation") == "merged_from":
                    changes.append({"type": "area_merged", "stable_key": key, "label": d["label"],
                                    "previous_keys": lin.get("previous_keys", [])})
                delta = {}
                if old.get("metrics") and d.get("metrics"):
                    for m, val in d["metrics"].items():
                        before = old["metrics"].get(m, {}).get("score")
                        if before is not None and val["score"] is not None and abs(val["score"] - before) >= 5:
                            delta[m] = {"from": before, "to": val["score"], "delta": round(val["score"] - before, 1)}
                size_delta = d["document_count"] - old["document_count"]
                if delta or size_delta or d["label"] != old["label"]:
                    changes.append({"type": "area_changed", "stable_key": key, "label": d["label"],
                                    "previous_label": old["label"], "document_delta": size_delta, "metric_delta": delta,
                                    "health": {"from": old.get("health"), "to": d.get("health")}})
        for key, d in ka.items():
            if key not in kb:
                changes.append({"type": "area_removed", "stable_key": key, "label": d["label"], "level": d["level"]})
        return {"from_snapshot_id": a["snapshot_id"], "to_snapshot_id": b["snapshot_id"],
                "from_created_at": a["created_at"], "to_created_at": b["created_at"], "changes": changes,
                "summary": {"from": a["summary"], "to": b["summary"]}}

    def changes(self, since: datetime, domain_id: str | None = None, limit: int = 100) -> dict:
        since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        tokens = self.p.access_tokens()
        q = select(Document).where(Document.tenant_id == self.p.tenant_id,
                                   (Document.updated_at >= since) | (Document.deleted_at >= since))
        if not self.p.is_admin:
            q = q.join(DocumentAcl, DocumentAcl.document_id == Document.id).where(DocumentAcl.principal.in_(tokens))
        scope = None
        if domain_id:
            from kt.retrieval.service import domain_documents

            scope = domain_documents(self.s, self.p.tenant_id, domain_id)
        events = []
        for d in self.s.scalars(q.distinct()):
            if scope is not None and d.id not in scope:
                continue
            created = d.created_at and d.created_at >= since
            etype = "document_deleted" if d.status == "deleted" else ("document_added" if created else "document_updated")
            events.append({"type": etype, "document_id": d.id, "title": d.title, "uri": d.canonical_uri,
                           "at": _iso(d.deleted_at or d.updated_at)})
        for s in self.snapshots(limit=20):
            created = datetime.fromisoformat(s["created_at"])
            if (created if created.tzinfo else created.replace(tzinfo=timezone.utc)) >= since:
                events.append({"type": "topology_snapshot", "snapshot_id": s["snapshot_id"], "at": s["created_at"]})
        events.sort(key=lambda e: e["at"] or "", reverse=True)
        return {"since": since.isoformat(), "events": events[:limit]}

    # ---------------------------------------------------------------- sources (admin)
    def sources(self) -> list[dict]:
        self.access.require_admin()
        return [{"id": s.id, "name": s.name, "connector_type": s.connector_type, "status": s.status,
                 "last_synced_at": _iso(s.last_synced_at), "last_error": s.last_error,
                 "config": {k: v for k, v in (s.config or {}).items() if "token" not in k and "secret" not in k
                            and "password" not in k},
                 "documents": self.s.query(Document).filter(Document.source_id == s.id,
                                                            Document.status == "active").count()}
                for s in self.s.scalars(select(Source).where(Source.tenant_id == self.p.tenant_id))]

    def _snapshot_doc(self, document_id: str) -> dict:
        try:
            snap = get_snapshot(self.s, self.p.tenant_id, None)
        except NotFound:
            return {}
        return snap.payload.get("documents", {}).get(document_id, {})
