"""Topology quality tests on the labelled demo corpus (see demo/corpus/*)."""

from conftest import doc_id_by_title, service

from kt.topology.geometry import area_geometry
from kt.topology.metrics import METRICS


def _areas(svc):
    snap_view = svc.topology(snapshot_id=svc.snapshots()[-1]["snapshot_id"], include_geometry=True)  # first snapshot
    return snap_view["nodes"]


def _area_of(svc, nodes, title):
    did = doc_id_by_title(svc, title)
    for n in nodes:
        area = svc.get_area(n["stable_key"], snapshot_id=svc.snapshots()[-1]["snapshot_id"])
        if did in area["documents"]:
            return n
    return None


def test_clusters_match_ground_truth(demo):
    svc = service("admin")
    nodes = _areas(svc)
    assert len(nodes) == 5
    groups = {
        "identity": ["Identity Platform Overview", "JWT Token Validation", "OAuth2 Authorization Flow"],
        "payments": ["Payment Retry Policy", "Payment Operations Runbook", "Refunds"],
        "legacy": ["ERP Synchronisation", "Integration Bus", "Mainframe Batch Export"],
        "platform": ["Kubernetes Clusters", "Deployment Pipeline", "Incident Management"],
        "people": ["Leave Policy", "Compensation Bands", "Employee Onboarding"],
    }
    keys = {}
    for name, titles in groups.items():
        found = {(_area_of(svc, nodes, t) or {}).get("stable_key") for t in titles}
        assert len(found) == 1 and None not in found, (name, found)
        keys[name] = found.pop()
    assert len(set(keys.values())) == 5  # no two ground-truth areas merged


def test_shapes_reflect_quality(demo):
    svc = service("admin")
    nodes = _areas(svc)
    shape = {n["stable_key"]: n["shape_class"] for n in nodes}
    identity = _area_of(svc, nodes, "JWT Token Validation")
    payments = _area_of(svc, nodes, "Payment Retry Policy")
    legacy = _area_of(svc, nodes, "ERP Synchronisation")
    assert shape[identity["stable_key"]] == "regular"
    assert shape[payments["stable_key"]] == "deformed"
    assert shape[legacy["stable_key"]] == "tangled"
    assert identity["health"] > payments["health"] > legacy["health"]
    assert legacy["geometry"]["chaos"] > payments["geometry"]["chaos"] > identity["geometry"]["chaos"]
    assert len(legacy["geometry"]["strands"]) > len(identity["geometry"]["strands"])
    # Size encodes scale, not quality: radius depends on document count only.
    assert set(identity["metrics"]) == set(METRICS)
    for n in nodes:
        assert all(0 <= m["score"] <= 100 and 0 <= m["confidence"] <= 1 for m in n["metrics"].values())


def test_issues_detected_with_evidence(demo):
    svc = service("admin")
    issues = svc.list_issues(status=None)
    types = {i["issue_type"] for i in issues}
    assert {"conflict", "duplicate", "stale", "orphan", "unowned"} <= types
    retry = [i for i in issues if i["issue_type"] == "conflict" and "3 vs 5" in i["title"] and "payments" in i["title"]]
    assert retry, [i["title"] for i in issues if i["issue_type"] == "conflict"]
    detail = svc.get_issue(retry[0]["id"])
    assert len(detail["evidence_chunks"]) == 2 and detail["recommendation"]
    dup = next(i for i in issues if i["issue_type"] == "duplicate")
    titles = {d["title"] for d in svc.get_issue(dup["id"])["documents"]}
    assert titles == {"ERP Synchronisation", "ERP Synchronisation (copy)"}
    orphan = next(i for i in issues if i["issue_type"] == "orphan")
    assert "Fraud Checks" in orphan["title"]
    # Cross-area conflict between the old retry policy (3) and the new Retry Orchestrator (4).
    assert any(i["title"].startswith("Cross-area conflict (3 vs 4") for i in issues)


def test_explainable_geometry(demo):
    svc = service("admin")
    legacy = _area_of(svc, _areas(svc), "ERP Synchronisation")
    feats = {e["feature"] for e in legacy["geometry"]["explanations"]}
    assert {"tangle", "jagged_zone", "dent"} <= feats
    jag = next(e for e in legacy["geometry"]["explanations"] if e["feature"] == "jagged_zone")
    assert jag["document_ids"] and jag["issue_ids"]


def test_stable_identity_and_evolution(demo):
    from kt import jobs

    svc = service("admin")
    snaps = svc.snapshots()
    assert len(snaps) == 2
    first, second = snaps[1]["snapshot_id"], snaps[0]["snapshot_id"]
    diff = svc.compare(first, second)
    added = [c for c in diff["changes"] if c["type"] == "area_added"]
    assert len(added) == 1 and "Orchestrator" in added[0]["label"]
    assert not [c for c in diff["changes"] if c["type"] == "area_removed"]
    before = {n["stable_key"]: n["position"] for n in svc.topology(snapshot_id=second)["nodes"]}
    # Rebuild without changes: same identities, (almost) same positions, no new issues.
    jobs.rebuild_topology()
    svc = service("admin")
    after = {n["stable_key"]: n["position"] for n in svc.topology()["nodes"]}
    assert set(after) == set(before)
    for k in after:
        assert abs(after[k][0] - before[k][0]) < 1.0 and abs(after[k][1] - before[k][1]) < 1.0


def test_geometry_is_deterministic(demo):
    svc = service("admin")
    from kt.topology.metrics import AreaAnalysis, MetricResult

    an = AreaAnalysis({m: MetricResult(60.0, 0.5, 5) for m in METRICS}, [], [], {}, [], [], [], [], {})
    pos = {"a": (0.1, 0.2), "b": (-0.3, 0.1)}
    assert area_geometry("dom_x", 5, an, pos, {}) == area_geometry("dom_x", 5, an, pos, {})
    assert area_geometry("dom_x", 5, an, pos, {})["outline"] != area_geometry("dom_y", 5, an, pos, {})["outline"]
    svc.s.close()


def test_issue_workflow_survives_rebuild(demo):
    from kt import jobs

    svc = service("admin")
    issue = svc.list_issues(issue_type="duplicate")[0]
    svc.update_issue(issue["id"], status="accepted", assigned_to="user:anna", comment="merging")
    svc.s.commit()
    jobs.rebuild_topology()
    svc = service("admin")
    again = svc.get_issue(issue["id"])
    assert again["status"] == "accepted" and again["assigned_to"] == "user:anna"
