"""Authoritative access control. Every API/MCP read path goes through here, server-side.

Rules
* A document is readable when its ACL intersects the caller's access tokens ({"*", user, groups}).
* Admins/auditors (role ``admin``) see the *privileged topology*; everyone else a filtered one.
* Denied and non-existent resources are indistinguishable (both -> NotFound).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from kt.db.orm import Document, DocumentAcl
from kt.domain.models import Principal


class NotFound(Exception):
    """Raised for both missing and unauthorised resources (no existence oracle)."""


class AccessService:
    def __init__(self, session: Session, principal: Principal):
        self.s = session
        self.p = principal
        self._readable: set[str] | None = None

    @property
    def tenant_id(self) -> str:
        return self.p.tenant_id

    def readable_document_ids(self) -> set[str]:
        if self._readable is None:
            q = select(Document.id).where(Document.tenant_id == self.tenant_id, Document.status == "active")
            if not self.p.is_admin:
                q = q.join(DocumentAcl, DocumentAcl.document_id == Document.id).where(
                    DocumentAcl.principal.in_(self.p.access_tokens()))
            self._readable = set(self.s.scalars(q.distinct()))
        return self._readable

    def can_read(self, document_id: str) -> bool:
        return document_id in self.readable_document_ids()

    def get_document(self, document_id: str) -> Document:
        doc = self.s.get(Document, document_id)
        if doc is None or doc.tenant_id != self.tenant_id or not self.can_read(document_id):
            raise NotFound(document_id)
        return doc

    def vector_tokens(self) -> set[str] | None:
        """ACL pre-filter for the vector store (None = no filter for admins)."""
        return None if self.p.is_admin else self.p.access_tokens()

    def require_admin(self) -> None:
        if not self.p.is_admin:
            raise PermissionError("admin role required")
