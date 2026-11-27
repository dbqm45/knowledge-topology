from pathlib import Path

from sqlalchemy import select

from kt.db.orm import Chunk, Document, DocumentAcl, DocumentVersion
from kt.db.session import session_scope
from kt.ingestion.service import IngestionService
from kt.semantic.embeddings import get_embedder
from kt.storage.vector import get_vector_store


def _write(p: Path, body: str, groups: str = "") -> None:
    p.write_text(("---\ngroups: [" + groups + "]\n---\n" if groups else "") + body, encoding="utf-8")


def _sync(src_id):
    with session_scope() as s:
        from kt.db.orm import Source

        return IngestionService(s, get_embedder(), get_vector_store()).sync(s.get(Source, src_id))


def test_incremental_sync_lifecycle(env):
    root = env / "wiki"
    root.mkdir()
    _write(root / "a.md", "# Alpha\nThe Alpha Service stores orders. Timeout is 30 seconds.\n")
    _write(root / "b.md", "# Beta\nThe Beta Service sends invoices. [alpha](a.md)\n")
    with session_scope() as s:
        src_id = IngestionService(s, get_embedder(), get_vector_store()).register_source(
            "default", "filesystem", "wiki", {"path": str(root)}).id

    st = _sync(src_id)
    assert (st.created, st.updated, st.deleted) == (2, 0, 0)
    with session_scope() as s:
        b = s.scalar(select(Document).where(Document.external_id == "b.md"))
        a = s.scalar(select(Document).where(Document.external_id == "a.md"))
        from kt.db.orm import DocumentLink

        assert s.scalar(select(DocumentLink.to_document_id).where(DocumentLink.from_document_id == b.id)) == a.id

    # Nothing changed -> nothing re-processed.
    st = _sync(src_id)
    assert (st.created, st.updated, st.chunks_embedded) == (0, 0, 0)

    # Content change -> new version, old chunks no longer current.
    _write(root / "a.md", "# Alpha\nThe Alpha Service stores orders. Timeout is 45 seconds.\n")
    st = _sync(src_id)
    assert st.updated == 1 and st.chunks_embedded >= 1
    with session_scope() as s:
        a = s.scalar(select(Document).where(Document.external_id == "a.md"))
        assert s.query(DocumentVersion).filter_by(document_id=a.id).count() == 2
        current = s.scalars(select(Chunk).where(Chunk.document_id == a.id, Chunk.is_current.is_(True))).all()
        assert all("45 seconds" in c.content for c in current)

    # ACL-only change -> no re-embedding, ACL + vector payload updated.
    _write(root / "a.md", "# Alpha\nThe Alpha Service stores orders. Timeout is 45 seconds.\n", "group:ops")
    st = _sync(src_id)
    assert st.acl_changed == 1 and st.chunks_embedded == 0
    with session_scope() as s:
        a = s.scalar(select(Document).where(Document.external_id == "a.md"))
        assert set(s.scalars(select(DocumentAcl.principal).where(DocumentAcl.document_id == a.id))) == {"group:ops"}
        chunk_ids = [c.id for c in s.scalars(select(Chunk).where(Chunk.document_id == a.id, Chunk.is_current.is_(True)))]
    vs = get_vector_store()
    hits = vs.search("default", get_embedder().embed_one("Alpha Service orders"), 10, {"*"})
    assert not any(h.id in chunk_ids for h in hits)  # vector pre-filter sees the new ACL
    hits = vs.search("default", get_embedder().embed_one("Alpha Service orders"), 10, {"group:ops"})
    assert any(h.id in chunk_ids for h in hits)

    # Delete -> document marked deleted, vectors removed, history kept.
    (root / "a.md").unlink()
    st = _sync(src_id)
    assert st.deleted == 1
    with session_scope() as s:
        a = s.scalar(select(Document).where(Document.external_id == "a.md"))
        assert a.status == "deleted" and a.deleted_at is not None
        assert s.query(DocumentVersion).filter_by(document_id=a.id).count() == 2
    assert not vs.fetch(chunk_ids)


def test_one_broken_document_does_not_stop_sync(env, monkeypatch):
    root = env / "wiki"
    root.mkdir()
    _write(root / "ok.md", "# Fine\nAll good here with enough words.\n")
    _write(root / "bad.md", "# Bad\nwill fail\n")
    from kt.connectors.filesystem import FilesystemConnector

    original = FilesystemConnector.fetch_document

    def flaky(self, external_id):
        if external_id == "bad.md":
            raise RuntimeError("boom")
        return original(self, external_id)

    monkeypatch.setattr(FilesystemConnector, "fetch_document", flaky)
    with session_scope() as s:
        src = IngestionService(s, get_embedder(), get_vector_store()).register_source(
            "default", "filesystem", "wiki", {"path": str(root)})
        st = IngestionService(s, get_embedder(), get_vector_store()).sync(src)
        assert st.created == 1 and len(st.errors) == 1 and src.status == "partial"
