"""Canonical, connector-independent knowledge models.

Every connector converts its native objects into :class:`NormalizedDocument`.
The rest of the platform (semantic, topology, intelligence, retrieval) only
ever sees these models — never Confluence/Notion/etc. specifics.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SectionKind = Literal["text", "table", "code", "list"]


class Section(BaseModel):
    heading_path: list[str] = Field(default_factory=list)
    text: str
    kind: SectionKind = "text"


class NormalizedDocument(BaseModel):
    external_id: str
    title: str
    url: str | None = None
    parent_external_id: str | None = None
    path: list[str] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    source_format: str = "text"
    language: str = "en"
    author: str | None = None
    owner: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source_version: str | None = None
    document_type: str | None = None
    # Outgoing references: external ids, titles ("title:...") or URLs.
    links: list[str] = Field(default_factory=list)
    # Effective read principals: "*" (everyone in tenant), "group:x", "user:y".
    principals: list[str] = Field(default_factory=lambda: ["*"])
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def body_text(self) -> str:
        return "\n\n".join(s.text for s in self.sections)

    def content_hash(self) -> str:
        """Hash of the meaningful content (title + structure). ACL/metadata are excluded on purpose:
        an ACL change must not trigger re-embedding."""
        payload = json.dumps(
            {"title": self.title, "sections": [s.model_dump() for s in self.sections]},
            sort_keys=True,
            ensure_ascii=False,
        )
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


ChangeType = Literal["upsert", "delete", "access_changed"]


class ChangeEvent(BaseModel):
    type: ChangeType
    external_id: str
    source_version: str | None = None


class ChangeBatch(BaseModel):
    events: list[ChangeEvent]
    next_cursor: dict[str, Any] | None = None
    # True when the batch enumerates the complete source (enables delete reconciliation).
    complete: bool = False


class Principal(BaseModel):
    """Authenticated caller (human user, service account or agent)."""

    id: str
    groups: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    tenant_id: str = "default"

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    def access_tokens(self) -> set[str]:
        return {"*", self.id, *self.groups}
