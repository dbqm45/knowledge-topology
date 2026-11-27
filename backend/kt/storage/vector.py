"""Vector store abstraction. The vector payload carries ACL tokens as a *pre-filter*; the
authoritative ACL check happens again in the retrieval service against PostgreSQL."""

from __future__ import annotations

import json
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from kt.config import Settings, get_settings


@dataclass
class VectorPoint:
    id: str
    vector: np.ndarray
    payload: dict = field(default_factory=dict)


@dataclass
class VectorHit:
    id: str
    score: float
    payload: dict


class VectorStore(ABC):
    @abstractmethod
    def upsert(self, points: list[VectorPoint]) -> None: ...

    @abstractmethod
    def delete_document(self, tenant_id: str, document_id: str) -> None: ...

    @abstractmethod
    def set_document_acl(self, tenant_id: str, document_id: str, principals: list[str]) -> None: ...

    @abstractmethod
    def search(
        self, tenant_id: str, vector: np.ndarray, top_k: int, access_tokens: set[str] | None,
        document_ids: set[str] | None = None,
    ) -> list[VectorHit]: ...

    @abstractmethod
    def fetch(self, ids: list[str]) -> dict[str, np.ndarray]: ...


class LocalVectorStore(VectorStore):
    """Exact (brute-force) numpy store persisted to disk. Good up to ~100k chunks on a laptop."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._ids: list[str] = []
        self._payloads: list[dict] = []
        self._matrix = np.zeros((0, 0), dtype=np.float32)
        self._mtime = 0.0
        self._load()

    def _files(self) -> tuple[Path, Path]:
        return self.path.with_suffix(".npy"), self.path.with_suffix(".json")

    def _load(self) -> None:
        npy, meta = self._files()
        if npy.exists() and meta.exists():
            self._matrix = np.load(npy)
            data = json.loads(meta.read_text(encoding="utf-8"))
            self._ids, self._payloads = data["ids"], data["payloads"]
            self._mtime = meta.stat().st_mtime

    def _maybe_reload(self) -> None:
        _, meta = self._files()
        if meta.exists() and meta.stat().st_mtime > self._mtime:
            self._load()

    def _save(self) -> None:
        npy, meta = self._files()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_npy, tmp_meta = npy.with_suffix(".tmp.npy"), meta.with_suffix(".tmp.json")
        np.save(tmp_npy, self._matrix)
        tmp_meta.write_text(json.dumps({"ids": self._ids, "payloads": self._payloads}), encoding="utf-8")
        os.replace(tmp_npy, npy)
        os.replace(tmp_meta, meta)
        self._mtime = meta.stat().st_mtime

    def upsert(self, points: list[VectorPoint]) -> None:
        if not points:
            return
        with self._lock:
            self._maybe_reload()
            index = {pid: i for i, pid in enumerate(self._ids)}
            dim = points[0].vector.shape[0]
            if self._matrix.size == 0:
                self._matrix = np.zeros((0, dim), dtype=np.float32)
            new_rows = []
            for p in points:
                if p.id in index:
                    self._matrix[index[p.id]] = p.vector
                    self._payloads[index[p.id]] = p.payload
                else:
                    self._ids.append(p.id)
                    self._payloads.append(p.payload)
                    new_rows.append(p.vector.astype(np.float32))
            if new_rows:
                self._matrix = np.vstack([self._matrix, np.stack(new_rows)])
            self._save()

    def _remove(self, predicate) -> None:
        keep = [i for i, pl in enumerate(self._payloads) if not predicate(pl)]
        if len(keep) == len(self._ids):
            return
        self._ids = [self._ids[i] for i in keep]
        self._payloads = [self._payloads[i] for i in keep]
        self._matrix = self._matrix[keep] if keep else np.zeros((0, self._matrix.shape[1]), dtype=np.float32)
        self._save()

    def delete_document(self, tenant_id: str, document_id: str) -> None:
        with self._lock:
            self._maybe_reload()
            self._remove(lambda pl: pl.get("tenant_id") == tenant_id and pl.get("document_id") == document_id)

    def set_document_acl(self, tenant_id: str, document_id: str, principals: list[str]) -> None:
        with self._lock:
            self._maybe_reload()
            for pl in self._payloads:
                if pl.get("tenant_id") == tenant_id and pl.get("document_id") == document_id:
                    pl["principals"] = list(principals)
            self._save()

    def search(self, tenant_id, vector, top_k, access_tokens, document_ids=None) -> list[VectorHit]:
        with self._lock:
            self._maybe_reload()
            if not self._ids:
                return []
            mask = np.array([
                pl.get("tenant_id") == tenant_id
                and (access_tokens is None or bool(access_tokens.intersection(pl.get("principals", []))))
                and (document_ids is None or pl.get("document_id") in document_ids)
                for pl in self._payloads
            ])
            if not mask.any():
                return []
            scores = self._matrix @ vector.astype(np.float32)
            scores[~mask] = -np.inf
            k = min(top_k, int(mask.sum()))
            top = np.argpartition(-scores, k - 1)[:k]
            top = top[np.argsort(-scores[top])]
            return [VectorHit(self._ids[i], float(scores[i]), self._payloads[i]) for i in top]

    def fetch(self, ids: list[str]) -> dict[str, np.ndarray]:
        with self._lock:
            self._maybe_reload()
            index = {pid: i for i, pid in enumerate(self._ids)}
            return {pid: self._matrix[index[pid]] for pid in ids if pid in index}


class QdrantVectorStore(VectorStore):
    def __init__(self, url: str, collection: str, dim: int, api_key: str | None = None, client=None):
        from qdrant_client import QdrantClient, models

        self.models = models
        self.client = client or QdrantClient(url=url, api_key=api_key)
        self.collection = collection
        if not self.client.collection_exists(collection):
            self.client.create_collection(
                collection, vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE)
            )
            import warnings

            for fld in ("tenant_id", "document_id", "principals"):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")  # local (embedded) mode ignores payload indexes
                    self.client.create_payload_index(collection, fld, models.PayloadSchemaType.KEYWORD)

    def _doc_filter(self, tenant_id: str, document_id: str):
        m = self.models
        return m.Filter(must=[
            m.FieldCondition(key="tenant_id", match=m.MatchValue(value=tenant_id)),
            m.FieldCondition(key="document_id", match=m.MatchValue(value=document_id)),
        ])

    def upsert(self, points: list[VectorPoint]) -> None:
        if points:
            self.client.upsert(self.collection, points=[
                self.models.PointStruct(id=p.id, vector=p.vector.tolist(), payload=p.payload) for p in points
            ])

    def delete_document(self, tenant_id: str, document_id: str) -> None:
        self.client.delete(self.collection, points_selector=self.models.FilterSelector(
            filter=self._doc_filter(tenant_id, document_id)))

    def set_document_acl(self, tenant_id: str, document_id: str, principals: list[str]) -> None:
        self.client.set_payload(self.collection, payload={"principals": list(principals)},
                                points=self.models.FilterSelector(filter=self._doc_filter(tenant_id, document_id)))

    def search(self, tenant_id, vector, top_k, access_tokens, document_ids=None) -> list[VectorHit]:
        m = self.models
        must = [m.FieldCondition(key="tenant_id", match=m.MatchValue(value=tenant_id))]
        if access_tokens is not None:
            must.append(m.FieldCondition(key="principals", match=m.MatchAny(any=sorted(access_tokens))))
        if document_ids is not None:
            must.append(m.FieldCondition(key="document_id", match=m.MatchAny(any=sorted(document_ids))))
        res = self.client.query_points(self.collection, query=vector.tolist(), limit=top_k,
                                       query_filter=m.Filter(must=must), with_payload=True)
        return [VectorHit(str(p.id), float(p.score), p.payload or {}) for p in res.points]

    def fetch(self, ids: list[str]) -> dict[str, np.ndarray]:
        out: dict[str, np.ndarray] = {}
        for i in range(0, len(ids), 256):
            for p in self.client.retrieve(self.collection, ids=ids[i : i + 256], with_vectors=True):
                out[str(p.id)] = np.asarray(p.vector, dtype=np.float32)
        return out


def build_vector_store(settings: Settings, dim: int) -> VectorStore:
    if settings.vector_backend == "qdrant":
        return QdrantVectorStore(settings.qdrant_url, settings.qdrant_collection, dim, settings.qdrant_api_key)
    return LocalVectorStore(settings.data_dir / "vectors" / settings.qdrant_collection)


@lru_cache
def get_vector_store() -> VectorStore:
    from kt.semantic.embeddings import get_embedder

    return build_vector_store(get_settings(), get_embedder().dim)
