from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DEMO = REPO / "demo" / "corpus"
DEMO_UPDATE = REPO / "demo" / "corpus-update"
KEYS = {
    "admin": {"principal": "user:admin", "groups": [], "roles": ["admin"]},
    "eng": {"principal": "user:eva", "groups": ["group:engineering"], "roles": []},
    "hr": {"principal": "user:harry", "groups": ["group:hr"], "roles": []},
    "nobody": {"principal": "user:nobody", "groups": [], "roles": []},
}


def reset_caches() -> None:
    from kt import config
    from kt.db import session
    from kt.retrieval import rerank
    from kt.retrieval import service as retrieval
    from kt.semantic import embeddings
    from kt.storage import vector

    config.get_settings.cache_clear()
    session.get_engine.cache_clear()
    embeddings.get_embedder.cache_clear()
    vector.get_vector_store.cache_clear()
    retrieval._LEXICAL_CACHE.clear()
    if hasattr(rerank.get_reranker, "cache_clear"):  # may be monkeypatched in a test
        rerank.get_reranker.cache_clear()


def configure(monkeypatch, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("KT_DATA_DIR", str(path))
    monkeypatch.setenv("KT_DATABASE_URL", f"sqlite:///{path}/kt.db")
    monkeypatch.setenv("KT_VECTOR_BACKEND", "local")
    monkeypatch.setenv("KT_EMBEDDING_PROVIDER", "hashing")
    monkeypatch.setenv("KT_API_KEYS", json.dumps(KEYS))
    monkeypatch.setenv("KT_MCP_API_KEY", "eng")
    reset_caches()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fresh, empty environment."""
    configure(monkeypatch, tmp_path / "data")
    from kt.db.session import init_db

    init_db()
    yield tmp_path
    reset_caches()


@pytest.fixture(scope="session")
def demo_dir(tmp_path_factory):
    """Demo corpus ingested once + two snapshots (before/after update). Tests copy it per use."""
    base = tmp_path_factory.mktemp("demo")
    mp = pytest.MonkeyPatch()
    configure(mp, base / "data")
    from kt import jobs
    from kt.db.session import init_db, session_scope
    from kt.ingestion.service import IngestionService
    from kt.semantic.embeddings import get_embedder
    from kt.storage.vector import get_vector_store

    init_db()
    corpus = base / "corpus"
    shutil.copytree(DEMO, corpus)
    with session_scope() as s:
        src = IngestionService(s, get_embedder(), get_vector_store()).register_source(
            "default", "filesystem", "demo", {"path": str(corpus)})
        sid = src.id
    jobs.sync_source(sid)
    jobs.rebuild_topology()
    with session_scope() as s:
        src2 = IngestionService(s, get_embedder(), get_vector_store()).register_source(
            "default", "filesystem", "demo-update", {"path": str(DEMO_UPDATE)})
        sid2 = src2.id
    jobs.sync_source(sid2)
    jobs.rebuild_topology()
    (base / "ids.json").write_text(json.dumps({"source": sid, "update_source": sid2}))
    mp.undo()
    reset_caches()
    return base


@pytest.fixture
def demo(demo_dir, tmp_path, monkeypatch):
    """A private, writable copy of the demo environment."""
    work = tmp_path / "demo"
    shutil.copytree(demo_dir, work)
    configure(monkeypatch, work / "data")
    # The source config points to the session copy of the corpus; repoint it to this copy.
    from sqlalchemy import update

    from kt.db.orm import Source
    from kt.db.session import session_scope

    ids = json.loads((work / "ids.json").read_text())
    with session_scope() as s:
        s.execute(update(Source).where(Source.id == ids["source"]).values(config={"path": str(work / "corpus")}))
    yield {"root": work, "corpus": work / "corpus", **ids}
    reset_caches()


def service(key: str):
    from kt.db.session import session_factory
    from kt.runtime import principal_from_api_key
    from kt.semantic.embeddings import get_embedder
    from kt.services import KnowledgeService
    from kt.storage.vector import get_vector_store

    s = session_factory()()
    return KnowledgeService(s, principal_from_api_key(key), get_embedder(), get_vector_store())


def doc_id_by_title(svc, title: str) -> str:
    from kt.db.orm import Document

    return svc.s.query(Document).filter(Document.title == title).one().id
