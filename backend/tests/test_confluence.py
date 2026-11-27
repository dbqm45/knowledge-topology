"""Confluence Cloud connector against a mocked REST API (v2 pages/spaces/ancestors, v1 restrictions + CQL)."""

import json

import httpx

from kt.connectors.confluence import ConfluenceConnector

PAGES = {
    "100": {"id": "100", "title": "Payments Home", "spaceId": "9", "parentId": None, "status": "current",
            "authorId": "a1", "ownerId": "o1", "createdAt": "2026-01-01T10:00:00Z",
            "version": {"number": 3, "createdAt": "2026-10-01T10:00:00Z"},
            "body": {"storage": {"value": "<h1>Home</h1><p>Payments overview. See "
                                          "<ac:link><ri:page ri:content-title=\"Retry Policy\"/></ac:link></p>"}},
            "_links": {"webui": "/spaces/PAY/pages/100/Payments+Home"}},
    "101": {"id": "101", "title": "Retry Policy", "spaceId": "9", "parentId": "100", "status": "current",
            "version": {"number": 7, "createdAt": "2026-11-01T10:00:00Z"},
            "body": {"storage": {"value": "<h2>Retries</h2><p>Retried up to 3 times.</p>"}},
            "_links": {"webui": "/spaces/PAY/pages/101"}},
    "102": {"id": "102", "title": "Secret Pricing", "spaceId": "9", "parentId": "100", "status": "current",
            "version": {"number": 1, "createdAt": "2026-11-02T10:00:00Z"},
            "body": {"storage": {"value": "<p>Confidential.</p>"}}, "_links": {"webui": "/spaces/PAY/pages/102"}},
}
RESTRICTIONS = {"102": {"group": ["finance", "payments"], "user": []}, "100": {"group": ["payments"], "user": ["u9"]}}


def handler(request: httpx.Request) -> httpx.Response:
    path, q = request.url.path, dict(request.url.params)
    if path == "/wiki/api/v2/spaces":
        return httpx.Response(200, json={"results": [{"id": "9", "key": "PAY"}], "_links": {}})
    if path == "/wiki/api/v2/spaces/9/pages":
        if q.get("cursor") == "c2":
            return httpx.Response(200, json={"results": [{"id": "102", "version": {"number": 1}}], "_links": {}})
        return httpx.Response(200, json={"results": [{"id": "100", "version": {"number": 3}},
                                                     {"id": "101", "version": {"number": 7}}],
                                         "_links": {"next": "/wiki/api/v2/spaces/9/pages?cursor=c2&limit=250"}})
    if path.startswith("/wiki/api/v2/pages/") and path.endswith("/ancestors"):
        pid = path.split("/")[5]
        anc = [] if pid == "100" else [{"id": "100", "type": "page"}]
        return httpx.Response(200, json={"results": anc, "_links": {}})
    if path.startswith("/wiki/api/v2/pages/"):
        pid = path.split("/")[5]
        return httpx.Response(200, json=PAGES[pid]) if pid in PAGES else httpx.Response(404)
    if path.startswith("/wiki/rest/api/content/") and path.endswith("/restriction/byOperation/read"):
        pid = path.split("/")[5]
        r = RESTRICTIONS.get(pid, {"group": [], "user": []})
        return httpx.Response(200, json={"restrictions": {
            "group": {"results": [{"name": g} for g in r["group"]]},
            "user": {"results": [{"accountId": u} for u in r["user"]]}}})
    if path == "/wiki/rest/api/search":
        assert "lastmodified" in q["cql"] and 'space in ("PAY")' in q["cql"]
        return httpx.Response(200, json={"results": [{"content": {"id": "101"}}], "_links": {}})
    return httpx.Response(404)


def make():
    return ConfluenceConnector({"base_url": "https://acme.atlassian.net", "email": "bot@acme.test", "api_token": "t",
                                "spaces": ["PAY"], "space_principals": {"PAY": ["group:engineering", "group:payments",
                                                                                "group:finance"]}},
                               transport=httpx.MockTransport(handler))


def test_full_listing_follows_cursor_pagination():
    batch = make().list_changes(None)
    assert batch.complete and {e.external_id for e in batch.events} == {"100", "101", "102"}
    assert batch.next_cursor["versions"] == {"100": "3", "101": "7", "102": "1"}


def test_incremental_uses_cql_and_detects_nothing_deleted():
    c = make()
    cursor = c.list_changes(None).next_cursor
    inc = c.list_changes(cursor)
    assert not inc.complete and [e.external_id for e in inc.events] == ["101"]


def test_document_normalisation_and_inherited_restrictions():
    c = make()
    home = c.fetch_document("100")
    assert home.url == "https://acme.atlassian.net/wiki/spaces/PAY/pages/100/Payments+Home"
    assert home.owner == "user:o1" and home.source_version == "3" and "title:Retry Policy" in home.links
    assert set(home.principals) == {"group:payments", "user:u9"}
    child = c.fetch_document("101")  # unrestricted itself, inherits parent restriction
    assert set(child.principals) == {"group:payments", "user:u9"}
    assert child.sections[0].heading_path == ["Retries"]
    secret = c.fetch_document("102")  # intersection of its own and its parent's restriction
    assert secret.principals == ["group:payments"]
    assert c.fetch_document("999") is None


def test_webhook_endpoint_triggers_targeted_sync(env, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("KT_WEBHOOK_SECRET", "s3cret")
    from conftest import reset_caches

    reset_caches()
    from kt.api import main
    from kt.api.routes import admin
    from kt.db.session import init_db, session_scope
    from kt.ingestion.service import IngestionService
    from kt.semantic.embeddings import get_embedder
    from kt.storage.vector import get_vector_store

    init_db()
    with session_scope() as s:
        src = IngestionService(s, get_embedder(), get_vector_store()).register_source(
            "default", "confluence", "PAY", {"base_url": "https://acme.atlassian.net", "spaces": ["PAY"]})
        sid = src.id
    calls = []
    monkeypatch.setattr(admin, "_sync_and_rebuild", lambda *a: calls.append(a))
    c = TestClient(main.create_app())
    assert c.post(f"/api/v1/webhooks/confluence/{sid}", json={"page": {"id": 1}}).status_code == 401
    r = c.post(f"/api/v1/webhooks/confluence/{sid}", json={"page": {"id": 101}},
               headers={"X-KT-Webhook-Secret": "s3cret"})
    assert r.status_code == 202 and calls == [(sid, False, ["101"])]
    json.dumps(r.json())
