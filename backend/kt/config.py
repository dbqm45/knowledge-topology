"""Runtime configuration (environment variables prefixed with ``KT_``)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KT_", env_file=".env", extra="ignore")

    # Storage
    data_dir: Path = Path("./data")
    database_url: str = "sqlite:///./data/kt.db"
    vector_backend: Literal["local", "qdrant"] = "local"
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "kt_chunks"

    # Dev convenience: create tables on start-up. Set to false when Alembic manages the schema.
    auto_create_schema: bool = True

    # Tenancy (the MVP runs a single default tenant, but every row carries tenant_id)
    default_tenant: str = "default"

    # Embeddings: "hashing" is dependency-free and deterministic (demo/tests),
    # "sentence-transformers" runs locally (e.g. BAAI/bge-m3), "openai" calls the API.
    embedding_provider: Literal["hashing", "sentence-transformers", "openai"] = "hashing"
    embedding_model: str = "hashing-v1"
    embedding_dim: int = 768
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"

    # Chunking (token counts are estimates: words * 1.3)
    chunk_target_tokens: int = 450
    chunk_max_tokens: int = 700
    chunk_overlap_ratio: float = 0.12

    # Retrieval
    retrieval_candidates: int = 30
    context_budget_tokens: int = 2500
    # Vector hits below max(abs floor, relative * best cosine) are dropped (avoid returning noise).
    retrieval_min_similarity: float = 0.12
    retrieval_relative_floor: float = 0.45
    # Hits supported by the vector side only (no keyword evidence) need a higher similarity.
    # Calibrate per embedding model (hashing ≈ 0.3, BGE-M3 ≈ 0.5).
    retrieval_vector_only_min: float = 0.3

    # Auth: JSON map api_key -> {"principal": "...", "groups": [...], "roles": [...]}
    api_keys: str = ""
    api_keys_file: Path | None = None
    webhook_secret: str | None = None

    # MCP: the MCP server acts as this identity (resolved from an API key, never from tool args)
    mcp_api_key: str | None = None

    # Web UI static build served by the API (optional)
    web_dist_dir: Path | None = None
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])

    def load_api_keys(self) -> dict[str, dict]:
        keys: dict[str, dict] = {}
        path = self.api_keys_file or (self.data_dir / "api-keys.json")
        if path.exists():
            keys.update(json.loads(path.read_text(encoding="utf-8")))
        if self.api_keys:
            keys.update(json.loads(self.api_keys))
        return keys


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
