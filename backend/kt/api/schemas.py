from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SearchScope(BaseModel):
    domain_id: str | None = None
    source_ids: list[str] = Field(default_factory=list)


class RetrievalOptions(BaseModel):
    mode: Literal["hybrid", "vector", "lexical"] = "hybrid"
    top_k: int = Field(8, ge=1, le=50)
    include_related: bool = True
    include_evidence: bool = True
    max_tokens: int | None = Field(None, ge=100, le=20000)
    rerank: bool = True  # use the configured cross-encoder (no-op when KT_RERANKER=none)


class SearchFilters(BaseModel):
    updated_after: datetime | None = None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    scope: SearchScope = Field(default_factory=SearchScope)
    retrieval: RetrievalOptions = Field(default_factory=RetrievalOptions)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class ConflictCheckRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    domain_id: str | None = None
    top_k: int = Field(10, ge=1, le=50)


class IssuePatch(BaseModel):
    status: Literal["open", "investigating", "accepted", "resolved", "dismissed"] | None = None
    assigned_to: str | None = None
    comment: str | None = Field(None, max_length=4000)


class SourceCreate(BaseModel):
    connector_type: Literal["filesystem", "confluence"]
    name: str
    config: dict
    sync_now: bool = True
