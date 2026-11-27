from __future__ import annotations

import hmac

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from kt import jobs
from kt.api.deps import get_db, get_service, require_admin
from kt.api.schemas import SourceCreate
from kt.config import get_settings
from kt.connectors import get_connector
from kt.db.orm import AuditEvent, Source
from kt.domain.models import Principal
from kt.ingestion.service import IngestionService
from kt.semantic.embeddings import get_embedder
from kt.services import KnowledgeService
from kt.storage.vector import get_vector_store

router = APIRouter(prefix="/api/v1", tags=["admin"])


@router.get("/sources")
def list_sources(svc: KnowledgeService = Depends(get_service)) -> list[dict]:
    return svc.sources()


@router.post("/sources", status_code=201)
def create_source(body: SourceCreate, background: BackgroundTasks, db: Session = Depends(get_db),
                  admin: Principal = Depends(require_admin)) -> dict:
    get_connector(body.connector_type, body.config).validate()
    src = IngestionService(db, get_embedder(), get_vector_store()).register_source(
        admin.tenant_id, body.connector_type, body.name, body.config)
    db.add(AuditEvent(tenant_id=admin.tenant_id, actor=admin.id, action="source.create", object_type="source",
                      object_id=src.id, details={"name": body.name, "connector": body.connector_type}))
    db.commit()
    if body.sync_now:
        background.add_task(_sync_and_rebuild, src.id, True)
    return {"id": src.id, "name": src.name, "status": src.status}


def _sync_and_rebuild(source_id: str, full: bool = False, ids: list[str] | None = None) -> None:
    jobs.sync_source(source_id, full=full, only_external_ids=ids)
    if jobs.topology_dirty():
        jobs.rebuild_topology()


@router.post("/sources/{source_id}/sync", status_code=202)
def sync(source_id: str, background: BackgroundTasks, full: bool = False, db: Session = Depends(get_db),
         admin: Principal = Depends(require_admin)) -> dict:
    src = db.get(Source, source_id)
    if src is None or src.tenant_id != admin.tenant_id:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "The requested resource is unavailable."})
    background.add_task(_sync_and_rebuild, source_id, full)
    return {"accepted": True, "source_id": source_id, "full": full}


@router.post("/topology/rebuild")
def rebuild(admin: Principal = Depends(require_admin)) -> dict:
    return jobs.rebuild_topology(admin.tenant_id)


@router.get("/audit")
def audit(limit: int = 100, db: Session = Depends(get_db), admin: Principal = Depends(require_admin)) -> list[dict]:
    rows = db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == admin.tenant_id)
                      .order_by(AuditEvent.created_at.desc()).limit(min(limit, 1000)))
    return [{"id": r.id, "actor": r.actor, "action": r.action, "object_type": r.object_type, "object_id": r.object_id,
             "details": r.details, "created_at": r.created_at.isoformat()} for r in rows]


@router.post("/webhooks/confluence/{source_id}", status_code=202)
async def confluence_webhook(source_id: str, request: Request, background: BackgroundTasks,
                             x_kt_webhook_secret: str | None = Header(None), db: Session = Depends(get_db)) -> dict:
    """Confluence (or Automation for Confluence) page events. Webhooks only *trigger* a targeted sync;
    the periodic reconciliation remains the consistency guarantee."""
    secret = get_settings().webhook_secret
    if not secret or not x_kt_webhook_secret or not hmac.compare_digest(secret, x_kt_webhook_secret):
        raise HTTPException(401, {"code": "UNAUTHENTICATED", "message": "invalid webhook secret"})
    src = db.get(Source, source_id)
    if src is None or src.connector_type != "confluence":
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "The requested resource is unavailable."})
    body = await request.json()
    page = body.get("page") or body.get("content") or {}
    page_id = str(page.get("id") or body.get("page_id") or "")
    if not page_id:
        raise HTTPException(422, {"code": "INVALID_EVENT", "message": "page id missing"})
    background.add_task(_sync_and_rebuild, source_id, False, [page_id])
    return {"accepted": True, "page_id": page_id}
