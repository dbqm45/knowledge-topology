from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from kt.api.deps import get_principal, get_service
from kt.api.schemas import ConflictCheckRequest, SearchRequest
from kt.domain.models import Principal
from kt.services import KnowledgeService

router = APIRouter(prefix="/api/v1", tags=["knowledge"])


@router.get("/me")
def me(principal: Principal = Depends(get_principal)) -> dict:
    return principal.model_dump()


@router.post("/search")
def search(req: SearchRequest, svc: KnowledgeService = Depends(get_service)) -> dict:
    return svc.search(req.query, top_k=req.retrieval.top_k, domain_id=req.scope.domain_id,
                      source_ids=req.scope.source_ids or None, mode=req.retrieval.mode,
                      include_related=req.retrieval.include_related, include_evidence=req.retrieval.include_evidence,
                      updated_after=req.filters.updated_after, max_tokens=req.retrieval.max_tokens,
                      rerank=req.retrieval.rerank)


@router.get("/documents/{document_id}")
def get_document(document_id: str, include_content: bool = True, max_tokens: int | None = None,
                 svc: KnowledgeService = Depends(get_service)) -> dict:
    return svc.get_document(document_id, include_content, max_tokens)


@router.get("/documents/{document_id}/context")
def document_context(document_id: str, chunk_id: str | None = None, window: int = Query(1, ge=0, le=5),
                     svc: KnowledgeService = Depends(get_service)) -> dict:
    return svc.get_document_context(document_id, chunk_id, window)


@router.get("/documents/{document_id}/related")
def related(document_id: str, limit: int = Query(8, ge=1, le=50), svc: KnowledgeService = Depends(get_service)) -> dict:
    return svc.get_related(document_id, limit)


@router.get("/entities")
def entities(q: str = Query("", max_length=200), limit: int = Query(20, ge=1, le=100),
             svc: KnowledgeService = Depends(get_service)) -> list[dict]:
    return svc.search_entities(q, limit)


@router.get("/entities/{entity_id}")
def entity(entity_id: str, svc: KnowledgeService = Depends(get_service)) -> dict:
    return svc.entity(entity_id)


@router.post("/conflicts/check")
def check_conflicts(req: ConflictCheckRequest, svc: KnowledgeService = Depends(get_service)) -> dict:
    return svc.check_conflicts(req.query, req.domain_id, req.top_k)


@router.post("/evidence")
def evidence(chunk_ids: list[str], svc: KnowledgeService = Depends(get_service)) -> list[dict]:
    return svc.evidence(chunk_ids[:50])
