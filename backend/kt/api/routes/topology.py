from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from kt.api.deps import get_service
from kt.api.schemas import IssuePatch
from kt.services import KnowledgeService

router = APIRouter(prefix="/api/v1", tags=["topology"])


@router.get("/topology")
def topology(snapshot_id: str | None = None, include_geometry: bool = True, include_documents: bool = False,
             level: int | None = Query(1, ge=1, le=2), svc: KnowledgeService = Depends(get_service)) -> dict:
    return svc.topology(snapshot_id, include_geometry, include_documents, level)


@router.get("/snapshots")
def snapshots(limit: int = Query(50, ge=1, le=500), svc: KnowledgeService = Depends(get_service)) -> list[dict]:
    return svc.snapshots(limit)


@router.get("/domains")
def domains(snapshot_id: str | None = None, include_subareas: bool = True,
            svc: KnowledgeService = Depends(get_service)) -> list[dict]:
    return svc.list_domains(snapshot_id, include_subareas)


@router.get("/domains/{domain_id}")
def domain(domain_id: str, snapshot_id: str | None = None, include_documents: bool = True,
           svc: KnowledgeService = Depends(get_service)) -> dict:
    return svc.get_area(domain_id, snapshot_id, include_documents)


@router.get("/domains/{domain_id}/health")
def domain_health(domain_id: str, svc: KnowledgeService = Depends(get_service)) -> dict:
    return svc.health(domain_id)


@router.get("/domains/{domain_id}/gaps")
def domain_gaps(domain_id: str, svc: KnowledgeService = Depends(get_service)) -> dict:
    return svc.gaps(domain_id)


@router.get("/issues")
def issues(domain_id: str | None = None, status: str | None = "open", severity: str | None = None,
           issue_type: str | None = None, limit: int = Query(200, ge=1, le=1000),
           svc: KnowledgeService = Depends(get_service)) -> list[dict]:
    return svc.list_issues(domain_id, status or None, severity, issue_type, limit)


@router.get("/issues/{issue_id}")
def issue(issue_id: str, svc: KnowledgeService = Depends(get_service)) -> dict:
    return svc.get_issue(issue_id)


@router.patch("/issues/{issue_id}")
def patch_issue(issue_id: str, patch: IssuePatch, svc: KnowledgeService = Depends(get_service)) -> dict:
    return svc.update_issue(issue_id, patch.status, patch.assigned_to, patch.comment)


@router.get("/evolution/compare")
def compare(from_snapshot_id: str, to_snapshot_id: str | None = None,
            svc: KnowledgeService = Depends(get_service)) -> dict:
    return svc.compare(from_snapshot_id, to_snapshot_id)


@router.get("/changes")
def changes(since: datetime, domain_id: str | None = None, limit: int = Query(100, ge=1, le=1000),
            svc: KnowledgeService = Depends(get_service)) -> dict:
    return svc.changes(since, domain_id, limit)
