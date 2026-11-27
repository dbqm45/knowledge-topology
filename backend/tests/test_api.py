from conftest import doc_id_by_title, service
from fastapi.testclient import TestClient


def client():
    from kt.api.main import create_app

    return TestClient(create_app())


def test_auth_and_error_model(demo):
    c = client()
    r = c.post("/api/v1/search", json={"query": "x"})
    assert r.status_code == 401
    body = r.json()["error"]
    assert body["code"] == "UNAUTHENTICATED" and body["trace_id"].startswith("trc_")
    assert r.headers["X-Trace-Id"] == body["trace_id"]


def test_search_and_topology(demo):
    c = client()
    h = {"Authorization": "Bearer eng"}
    r = c.post("/api/v1/search", headers=h, json={
        "query": "How many times are failed card payments retried?",
        "retrieval": {"top_k": 4, "max_tokens": 800}})
    assert r.status_code == 200
    data = r.json()
    assert data["results"] and data["usage"]["estimated_tokens"] <= 800
    assert any(w["type"] == "conflict" for w in data["warnings"])
    assert all(r_["uri"] for r_ in data["results"])
    topo = c.get("/api/v1/topology", headers=h).json()
    assert topo["nodes"] and all("outline" in n["geometry"] for n in topo["nodes"])
    key = topo["nodes"][0]["stable_key"]
    assert c.get(f"/api/v1/domains/{key}", headers=h).status_code == 200
    assert c.get(f"/api/v1/domains/{key}/health", headers=h).json()["metrics"]
    snaps = c.get("/api/v1/snapshots", headers=h).json()
    cmp_ = c.get("/api/v1/evolution/compare", headers=h,
                 params={"from_snapshot_id": snaps[-1]["snapshot_id"]}).json()
    assert cmp_["changes"]


def test_forbidden_equals_missing(demo):
    c = client()
    hr_doc = doc_id_by_title(service("admin"), "Leave Policy")
    denied = c.get(f"/api/v1/documents/{hr_doc}", headers={"X-API-Key": "eng"})
    missing = c.get("/api/v1/documents/does-not-exist", headers={"X-API-Key": "eng"})
    assert denied.status_code == missing.status_code == 404
    assert denied.json()["error"]["message"] == missing.json()["error"]["message"]
    assert c.get(f"/api/v1/documents/{hr_doc}", headers={"X-API-Key": "hr"}).status_code == 200


def test_issue_patch_is_audited_and_admin_endpoints_protected(demo):
    c = client()
    h = {"X-API-Key": "admin"}
    issue = c.get("/api/v1/issues", headers=h, params={"issue_type": "stale"}).json()[0]
    r = c.patch(f"/api/v1/issues/{issue['id']}", headers=h, json={"status": "investigating", "comment": "checking"})
    assert r.status_code == 200 and r.json()["status"] == "investigating"
    audit = c.get("/api/v1/audit", headers=h).json()
    assert any(a["action"] == "issue.update" and a["object_id"] == issue["id"] for a in audit)
    assert c.get("/api/v1/sources", headers={"X-API-Key": "eng"}).status_code == 403
    assert c.post("/api/v1/topology/rebuild", headers={"X-API-Key": "eng"}).status_code == 403
    assert c.patch(f"/api/v1/issues/{issue['id']}", headers=h, json={"status": "bogus"}).status_code == 422
