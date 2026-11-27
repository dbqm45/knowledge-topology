"""MCP tool implementations — thin adapters over KnowledgeService (no own retrieval/ACL logic).

The caller identity is NOT a tool argument: it is resolved once from the connection's API key
(``KT_MCP_API_KEY``) and enforced by the same services the REST API uses.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime

from kt.access.service import NotFound
from kt.db.session import session_scope
from kt.domain.models import Principal
from kt.semantic.embeddings import get_embedder
from kt.services import KnowledgeService
from kt.storage.vector import get_vector_store

NOT_FOUND = {"error": {"code": "NOT_FOUND", "message": "The requested resource is unavailable."}}


class KnowledgeTools:
    def __init__(self, principal: Principal, service_factory: Callable[..., KnowledgeService] | None = None):
        self.principal = principal
        self._factory = service_factory

    @contextmanager
    def _svc(self) -> Iterator[KnowledgeService]:
        if self._factory:
            yield self._factory()
            return
        with session_scope() as s:
            yield KnowledgeService(s, self.principal, get_embedder(), get_vector_store())

    def _call(self, fn: Callable[[KnowledgeService], dict | list]) -> dict:
        try:
            with self._svc() as svc:
                out = fn(svc)
                return out if isinstance(out, dict) else {"items": out}
        except NotFound:
            return NOT_FOUND
        except (ValueError, PermissionError) as exc:
            return {"error": {"code": "BAD_REQUEST", "message": str(exc)}}

    # ---- Knowledge Retrieval
    def search_knowledge(self, query: str, domain_id: str | None = None, top_k: int = 6,
                         include_evidence: bool = True, include_related: bool = True, max_tokens: int = 2500,
                         mode: str = "hybrid") -> dict:
        return self._call(lambda s: s.search(query, top_k=min(top_k, 20), domain_id=domain_id, mode=mode,
                                             include_evidence=include_evidence, include_related=include_related,
                                             max_tokens=max_tokens))

    def get_document(self, document_id: str, max_tokens: int = 4000) -> dict:
        return self._call(lambda s: s.get_document(document_id, True, max_tokens))

    def get_document_context(self, document_id: str, chunk_id: str | None = None, window: int = 1) -> dict:
        return self._call(lambda s: s.get_document_context(document_id, chunk_id, min(window, 5)))

    def get_related_knowledge(self, document_id: str, limit: int = 8) -> dict:
        return self._call(lambda s: s.get_related(document_id, min(limit, 30)))

    # ---- Knowledge Structure
    def list_knowledge_domains(self, include_subareas: bool = False) -> dict:
        def run(s: KnowledgeService):
            return [{k: d[k] for k in ("id", "stable_key", "label", "description", "level", "parent_key",
                                       "document_count", "health", "shape_class", "visibility")}
                    for d in s.list_domains(include_subareas=include_subareas)]
        return self._call(run)

    def get_knowledge_area(self, domain_id: str, include_documents: bool = True) -> dict:
        def run(s: KnowledgeService):
            area = s.get_area(domain_id, include_documents=include_documents)
            dm = area["domain"]
            dm.pop("geometry", None)  # agents do not need drawing primitives
            if include_documents:
                area["documents"] = [{"document_id": d, "title": v["title"], "uri": v.get("uri"),
                                      "flags": v.get("flags", [])} for d, v in area["documents"].items()]
                area.pop("edges", None)
            for c in area.get("children", []):
                c.pop("geometry", None)
            return area
        return self._call(run)

    def get_entity(self, entity_id: str) -> dict:
        return self._call(lambda s: s.entity(entity_id))

    def find_entities(self, name: str, limit: int = 10) -> dict:
        return self._call(lambda s: s.search_entities(name, min(limit, 50)))

    # ---- Knowledge Intelligence
    def get_knowledge_health(self, domain_id: str) -> dict:
        def run(s: KnowledgeService):
            h = s.health(domain_id, history=5)
            h["issues"] = [{k: i[k] for k in ("id", "issue_type", "severity", "status", "title")} for i in h["issues"]]
            return h
        return self._call(run)

    def check_knowledge_conflicts(self, query: str, domain_id: str | None = None, top_k: int = 10) -> dict:
        return self._call(lambda s: s.check_conflicts(query, domain_id, min(top_k, 30)))

    def get_knowledge_gaps(self, domain_id: str) -> dict:
        return self._call(lambda s: s.gaps(domain_id))

    def get_knowledge_evidence(self, chunk_ids: list[str]) -> dict:
        return self._call(lambda s: s.evidence(chunk_ids[:20]))

    # ---- Knowledge Evolution
    def get_knowledge_changes(self, since: str, domain_id: str | None = None, limit: int = 50) -> dict:
        return self._call(lambda s: s.changes(datetime.fromisoformat(since.replace("Z", "+00:00")), domain_id,
                                              min(limit, 200)))

    def compare_knowledge_snapshots(self, from_snapshot_id: str, to_snapshot_id: str | None = None) -> dict:
        return self._call(lambda s: s.compare(from_snapshot_id, to_snapshot_id))

    def list_knowledge_snapshots(self, limit: int = 10) -> dict:
        return self._call(lambda s: s.snapshots(min(limit, 100)))
