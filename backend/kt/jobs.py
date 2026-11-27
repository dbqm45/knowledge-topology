"""Background jobs shared by the CLI, the API (BackgroundTasks) and the worker loop.

The MVP runs jobs in-process; the same functions can be wrapped by Celery/Temporal later.
"""

from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import select

from kt.config import get_settings
from kt.db.orm import Source, Tenant
from kt.db.session import session_scope
from kt.ingestion.service import IngestionService, SyncStats
from kt.semantic.embeddings import get_embedder
from kt.storage.vector import get_vector_store
from kt.topology.engine import TopologyEngine

log = logging.getLogger(__name__)
_build_lock = threading.Lock()


def sync_source(source_id: str, full: bool = False, only_external_ids: list[str] | None = None) -> SyncStats:
    with session_scope() as s:
        src = s.get(Source, source_id)
        if src is None:
            raise ValueError(f"unknown source {source_id}")
        svc = IngestionService(s, get_embedder(), get_vector_store())
        return svc.sync(src, full=full, only_external_ids=only_external_ids)


def sync_all(tenant_id: str | None = None, full: bool = False) -> dict[str, dict]:
    tenant_id = tenant_id or get_settings().default_tenant
    with session_scope() as s:
        ids = list(s.scalars(select(Source.id).where(Source.tenant_id == tenant_id)))
    out = {}
    for sid in ids:
        try:
            out[sid] = sync_source(sid, full=full).as_dict()
        except Exception as exc:  # keep going with other sources
            log.exception("sync failed for %s", sid)
            out[sid] = {"error": str(exc)}
    return out


def rebuild_topology(tenant_id: str | None = None) -> dict:
    tenant_id = tenant_id or get_settings().default_tenant
    with _build_lock, session_scope() as s:
        snap = TopologyEngine(s, get_vector_store(), get_embedder().model_id).build(tenant_id)
        return {"snapshot_id": snap.id, "stats": snap.stats}


def topology_dirty(tenant_id: str | None = None) -> bool:
    tenant_id = tenant_id or get_settings().default_tenant
    with session_scope() as s:
        t = s.get(Tenant, tenant_id)
        return bool(t and (t.settings or {}).get("topology_dirty"))


def worker_loop(interval_seconds: int = 900, tenant_id: str | None = None) -> None:  # pragma: no cover - loop
    """Periodic incremental sync + rebuild of the topology when something changed."""
    while True:
        try:
            sync_all(tenant_id)
            if topology_dirty(tenant_id):
                log.info("topology rebuilt: %s", rebuild_topology(tenant_id))
        except Exception:
            log.exception("worker iteration failed")
        time.sleep(interval_seconds)
