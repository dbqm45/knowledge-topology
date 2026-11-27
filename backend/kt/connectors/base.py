"""Connector contract. A connector knows its source system and nothing about graphs, embeddings or topology."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from kt.domain.models import ChangeBatch, NormalizedDocument

_REGISTRY: dict[str, type["KnowledgeConnector"]] = {}


class KnowledgeConnector(ABC):
    type: ClassVar[str]

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @abstractmethod
    def validate(self) -> None:
        """Raise if the configuration/credentials are unusable."""

    @abstractmethod
    def list_changes(self, cursor: dict[str, Any] | None) -> ChangeBatch:
        """Changes since ``cursor``. ``cursor=None`` means a full enumeration (``complete=True``)."""

    @abstractmethod
    def fetch_document(self, external_id: str) -> NormalizedDocument | None:
        """Fetch and normalise one document (including effective read principals). None if gone."""

    def fetch_permissions(self, external_id: str) -> list[str]:
        doc = self.fetch_document(external_id)
        return doc.principals if doc else []

    def close(self) -> None:  # noqa: B027 - optional hook, intentionally not abstract
        """Release resources (HTTP clients...). Optional."""


def register_connector(cls: type[KnowledgeConnector]) -> type[KnowledgeConnector]:
    _REGISTRY[cls.type] = cls
    return cls


def get_connector(connector_type: str, config: dict[str, Any]) -> KnowledgeConnector:
    try:
        return _REGISTRY[connector_type](config)
    except KeyError:
        raise ValueError(f"Unknown connector type '{connector_type}'. Known: {sorted(_REGISTRY)}") from None
