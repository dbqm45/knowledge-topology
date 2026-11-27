from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from kt.db.session import session_factory
from kt.domain.models import Principal
from kt.runtime import AuthError, principal_from_api_key
from kt.semantic.embeddings import get_embedder
from kt.services import KnowledgeService
from kt.storage.vector import get_vector_store


def get_db() -> Iterator[Session]:
    s = session_factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_principal(authorization: str | None = Header(None), x_api_key: str | None = Header(None),
                  api_key: str | None = Query(None, include_in_schema=False)) -> Principal:
    token = x_api_key or api_key
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    try:
        return principal_from_api_key(token)
    except AuthError as exc:
        raise HTTPException(401, {"code": "UNAUTHENTICATED", "message": str(exc)}) from None


def get_service(db: Session = Depends(get_db), principal: Principal = Depends(get_principal)) -> KnowledgeService:
    return KnowledgeService(db, principal, get_embedder(), get_vector_store())


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(403, {"code": "FORBIDDEN", "message": "admin role required"})
    return principal
