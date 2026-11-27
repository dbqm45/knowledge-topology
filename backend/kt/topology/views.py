"""Caller-specific views of a topology snapshot (the *visualization authorization* layer).

* Areas with no readable documents are invisible (their existence is not revealed).
* Areas the caller sees only partially get a neutral circle, no metrics, a label derived only from
  readable documents, and no issues — metrics and shapes computed over hidden documents could leak them.
* Admins/auditors get the privileged (unfiltered) topology.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from kt.access.service import AccessService, NotFound
from kt.db.orm import Issue, TopologySnapshot
from kt.topology.engine import latest_snapshot
from kt.topology.geometry import neutral_geometry


def get_snapshot(session: Session, tenant_id: str, snapshot_id: str | None) -> TopologySnapshot:
    if snapshot_id:
        snap = session.get(TopologySnapshot, snapshot_id)
        if snap is None or snap.tenant_id != tenant_id or snap.status != "ok":
            raise NotFound(snapshot_id)
        return snap
    snap = latest_snapshot(session, tenant_id)
    if snap is None:
        raise NotFound("snapshot")
    return snap


def _partial_label(payload_docs: dict, visible: list[str]) -> str:
    cnt: Counter = Counter()
    for d in visible:
        cnt.update(payload_docs[d].get("entities", [])[:6])
    if cnt:
        return " & ".join(n for n, _ in cnt.most_common(2))
    return payload_docs[visible[0]]["title"] if visible else "Area"


def visible_issue_ids(session: Session, access: AccessService, issue_ids: list[str]) -> list[str]:
    if not issue_ids:
        return []
    readable = access.readable_document_ids()
    out = []
    for issue in session.scalars(select(Issue).where(Issue.id.in_(issue_ids))):
        if access.p.is_admin or set((issue.evidence or {}).get("document_ids", [])) <= readable:
            out.append(issue.id)
    return sorted(out)


def view_domain(session: Session, access: AccessService, dm: dict, payload_docs: dict,
                include_geometry: bool = True) -> dict | None:
    readable = access.readable_document_ids()
    docs = dm["document_ids"]
    visible = docs if access.p.is_admin else [d for d in docs if d in readable]
    if not visible:
        return None
    full = len(visible) == len(docs)
    out = {
        "id": dm["id"], "stable_key": dm["stable_key"], "level": dm["level"], "parent_key": dm["parent_key"],
        "label": dm["label"] if full else _partial_label(payload_docs, visible),
        "description": dm["description"] if full else f"{len(visible)} visible documents",
        "document_count": len(visible), "visibility": "full" if full else "partial",
        "confidence": dm["confidence"] if full else None,
        "health": dm["health"] if full else None,
        "metrics": dm["metrics"] if full else None,
        "shape_class": dm["geometry"]["shape_class"] if full else "restricted",
        "position": dm.get("position"), "center_in_parent": dm.get("center_in_parent"),
        "children": dm.get("children", []),
        "issue_ids": visible_issue_ids(session, access, dm.get("issue_ids", [])) if full else [],
        "lineage": dm.get("lineage") if full else None,
    }
    if include_geometry:
        out["geometry"] = dm["geometry"] if full else neutral_geometry(len(visible))
    return out


def topology_view(session: Session, access: AccessService, snapshot_id: str | None = None,
                  include_geometry: bool = True, include_documents: bool = False, level: int | None = 1) -> dict:
    snap = get_snapshot(session, access.tenant_id, snapshot_id)
    p = snap.payload
    domains = []
    for dm in p.get("domains", []):
        if level is not None and dm["level"] != level:
            continue
        v = view_domain(session, access, dm, p["documents"], include_geometry)
        if v:
            domains.append(v)
    keys = {d["stable_key"]: d for d in domains}
    edges = []
    for e in p.get("edges", []):
        if e["source"] in keys and e["target"] in keys:
            full = keys[e["source"]]["visibility"] == "full" and keys[e["target"]]["visibility"] == "full"
            edges.append({**e, "weight": e["weight"] if full else None, "edge_count": e["edge_count"] if full else None})
    out = {"snapshot_id": snap.id, "created_at": snap.created_at.isoformat(), "algorithm_version": snap.algorithm_version,
           "embedding_model": snap.embedding_model, "scope": {"type": "global", "id": None},
           "privileged": access.p.is_admin, "nodes": domains, "edges": edges}
    readable = access.readable_document_ids()
    if include_documents:
        out["documents"] = {d: v for d, v in p["documents"].items() if access.p.is_admin or d in readable}
    out["summary"] = {"documents": sum(1 for d in p["documents"] if access.p.is_admin or d in readable),
                      "areas": len(domains),
                      "unassigned": sum(1 for d in p.get("unassigned", []) if access.p.is_admin or d in readable)}
    return out


def domain_map_view(session: Session, access: AccessService, domain_ref: str, snapshot_id: str | None = None) -> dict:
    snap = get_snapshot(session, access.tenant_id, snapshot_id)
    p = snap.payload
    dm = next((d for d in p.get("domains", []) if domain_ref in (d["id"], d["stable_key"])), None)
    if dm is None:
        raise NotFound(domain_ref)
    v = view_domain(session, access, dm, p["documents"], True)
    if v is None:
        raise NotFound(domain_ref)
    readable = access.readable_document_ids()
    visible = [d for d in dm["document_ids"] if access.p.is_admin or d in readable]
    vis_set = set(visible)
    docs = {}
    for d in visible:
        info = dict(p["documents"][d])
        if v["visibility"] != "full":
            info["flags"] = [f for f in info.get("flags", []) if f in ("stale", "stub")]
            info["issue_ids"] = visible_issue_ids(session, access, info.get("issue_ids", []))
        docs[d] = info
    children = [view_domain(session, access, c, p["documents"], True)
                for c in p["domains"] if c.get("parent_key") == dm["stable_key"]]
    edges = [e for e in p.get("doc_edges", []) if e["source"] in vis_set and e["target"] in vis_set]
    # Neighbouring documents outside the area, if readable (for "related knowledge" context).
    external = []
    for e in p.get("doc_edges", []):
        a, b = e["source"], e["target"]
        if (a in vis_set) != (b in vis_set):
            other = b if a in vis_set else a
            if access.p.is_admin or other in readable:
                external.append({"from": a if a in vis_set else b, "document_id": other,
                                 "title": p["documents"][other]["title"],
                                 "domain": p["documents"][other].get("domain"), "weight": e["weight"]})
    return {"snapshot_id": snap.id, "domain": v, "documents": docs, "edges": edges,
            "children": [c for c in children if c], "external_links": external[:40]}
