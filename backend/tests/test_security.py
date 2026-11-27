"""Mandatory ACL scenarios: search, graph/map, metrics, issues, entities, MCP, ACL change, deletion, known IDs."""

import pytest
from conftest import doc_id_by_title, service

from kt.access.service import NotFound

HR_TITLES = {"Leave Policy", "Compensation Bands", "Employee Onboarding", "Performance Reviews"}


def test_search_respects_acl(demo):
    eng, hr = service("eng"), service("hr")
    assert {r["title"] for r in eng.search("compensation bands salary review", top_k=10)["results"]} & HR_TITLES == set()
    assert "Compensation Bands" in {r["title"] for r in hr.search("compensation bands salary review")["results"]}
    for mode in ("vector", "lexical", "hybrid"):
        res = eng.search("annual leave carried over until March", mode=mode, top_k=20)
        assert not {r["title"] for r in res["results"]} & HR_TITLES, mode
    # Response never reveals how many documents were hidden.
    assert "hidden" not in str(eng.search("leave policy")).lower()


def test_hidden_area_invisible_in_topology(demo):
    eng, admin = service("eng"), service("admin")
    hr_doc = doc_id_by_title(admin, "Leave Policy")
    eng_view = eng.topology(include_documents=True)
    assert hr_doc not in eng_view["documents"]
    labels = {n["label"] for n in eng_view["nodes"]}
    admin_labels = {n["label"] for n in admin.topology()["nodes"]}
    assert len(admin_labels) == len(labels) + 1  # the People area simply does not exist for eng
    assert all(hr_doc not in (e["source"], e["target"]) for e in eng.get_area(eng_view["nodes"][0]["stable_key"])["edges"])
    people_key = next(n["stable_key"] for n in admin.topology()["nodes"] if n["label"] not in labels)
    with pytest.raises(NotFound):
        eng.get_area(people_key)
    with pytest.raises(NotFound):
        eng.health(people_key)


def test_known_document_id_is_not_an_oracle(demo):
    eng, admin = service("eng"), service("admin")
    hr_doc = doc_id_by_title(admin, "Compensation Bands")
    for fn in (eng.get_document, eng.get_document_context, eng.get_related):
        with pytest.raises(NotFound):
            fn(hr_doc)
    with pytest.raises(NotFound):
        eng.get_document("00000000-0000-0000-0000-000000000000")
    assert eng.evidence([c["chunk_id"] for c in admin.get_document(hr_doc)["sections"]]) == []


def test_issues_and_entities_filtered(demo):
    eng, admin = service("eng"), service("admin")
    hr_ids = {doc_id_by_title(admin, t) for t in HR_TITLES}
    for issue in eng.list_issues(status=None):
        assert not set(issue["evidence"].get("document_ids", [])) & hr_ids
    assert eng.search_entities("People Operations") == []
    ent = admin.search_entities("People Operations")[0]
    with pytest.raises(NotFound):
        eng.entity(ent["id"])


def test_partial_visibility_leaks_no_metrics(demo):
    """Restrict one Payments document to HR: engineering then sees Payments only partially."""
    from kt import jobs
    from kt.db.orm import DocumentAcl

    admin = service("admin")
    restricted = doc_id_by_title(admin, "Refunds")
    admin.s.query(DocumentAcl).filter_by(document_id=restricted).update({"principal": "group:finance"})
    admin.s.commit()
    eng = service("eng")
    node = next(n for n in eng.topology()["nodes"] if n["visibility"] == "partial")
    assert node["metrics"] is None and node["health"] is None and node["issue_ids"] == []
    assert node["geometry"]["shape_class"] == "restricted" and node["geometry"]["strands"] == []
    area = eng.get_area(node["stable_key"])
    assert restricted not in area["documents"]
    jobs.rebuild_topology()  # rebuilding keeps enforcing the same rule
    assert any(n["visibility"] == "partial" for n in service("eng").topology()["nodes"])


def test_agents_scoped_by_identity(demo):
    from kt.mcp.tools import KnowledgeTools
    from kt.runtime import principal_from_api_key

    eng_tools = KnowledgeTools(principal_from_api_key("eng"))
    hr_tools = KnowledgeTools(principal_from_api_key("hr"))
    assert not {r["title"] for r in eng_tools.search_knowledge("leave policy annual leave")["results"]} & HR_TITLES
    assert "Leave Policy" in {r["title"] for r in hr_tools.search_knowledge("leave policy annual leave")["results"]}
    hr_areas = {d["label"] for d in hr_tools.list_knowledge_domains()["items"]}
    eng_areas = {d["label"] for d in eng_tools.list_knowledge_domains()["items"]}
    assert "People Operations" in hr_areas and "People Operations" not in eng_areas
    assert len(hr_areas) == len(eng_areas) + 1  # everything else in the demo is public
    admin = service("admin")
    assert eng_tools.get_document(doc_id_by_title(admin, "Leave Policy"))["error"]["code"] == "NOT_FOUND"


def test_acl_change_and_deletion_take_effect(demo):
    from kt import jobs

    corpus = demo["corpus"]
    eng = service("eng")
    assert "API Gateway Authentication" in {r["title"] for r in eng.search("gateway authentication filter")["results"]}
    path = corpus / "identity" / "gateway-authentication.md"
    path.write_text(path.read_text().replace("owner: team:identity", "owner: team:identity\ngroups: [group:security]"))
    st = jobs.sync_source(demo["source"])
    assert st.acl_changed == 1 and st.chunks_embedded == 0
    eng = service("eng")
    assert "API Gateway Authentication" not in {r["title"] for r in eng.search("gateway authentication filter")["results"]}

    (corpus / "identity" / "jwt-token-validation.md").unlink()
    st = jobs.sync_source(demo["source"])
    assert st.deleted == 1
    admin = service("admin")
    assert "JWT Token Validation" not in {r["title"] for r in admin.search("JWT validation signature JWKS")["results"]}
