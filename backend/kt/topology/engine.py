"""Knowledge Topology Engine — builds a versioned, explainable snapshot of the knowledge map.

Pipeline: corpus -> multi-signal graph -> hybrid clustering (+ sub-areas) -> lineage (stable ids)
-> quality metrics -> issues -> geometry -> stable layout -> persistence.
Each run records algorithm + embedding model versions and parameters, so a map is reproducible.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from kt import ALGORITHM_VERSION
from kt.db.orm import (
    AuditEvent,
    ClusterMembership,
    Issue,
    KnowledgeDomain,
    QualityMetric,
    Relation,
    SnapshotClusterLineage,
    Tenant,
    TopologySnapshot,
)
from kt.intelligence.issues import IssueDraft, detect_issues, detect_orphan_issues, detect_terminology_issues
from kt.storage.vector import VectorStore
from kt.topology.clustering import ClusterParams, hybrid_clustering, membership_type
from kt.topology.corpus import Corpus, load_corpus
from kt.topology.geometry import area_geometry
from kt.topology.graph import DocGraph, GraphParams, build_document_graph
from kt.topology.labels import distinctive_terms, label_for
from kt.topology.layout import global_layout, local_layout
from kt.topology.lineage import match_clusters
from kt.topology.metrics import AreaAnalysis, analyse_area

log = logging.getLogger(__name__)
COMPUTED_PROVENANCE = ("topology_engine",)


def latest_snapshot(session: Session, tenant_id: str) -> TopologySnapshot | None:
    return session.scalar(select(TopologySnapshot).where(TopologySnapshot.tenant_id == tenant_id,
                                                         TopologySnapshot.status == "ok")
                          .order_by(TopologySnapshot.created_at.desc()).limit(1))


class TopologyEngine:
    def __init__(self, session: Session, vectors: VectorStore, embedding_model: str,
                 graph_params: GraphParams | None = None, cluster_params: ClusterParams | None = None,
                 now: datetime | None = None):
        self.s = session
        self.vectors = vectors
        self.embedding_model = embedding_model
        self.gp = graph_params or GraphParams()
        self.cp = cluster_params or ClusterParams()
        self.now = now or datetime.now(timezone.utc)

    # ------------------------------------------------------------------------------------------------------
    def build(self, tenant_id: str) -> TopologySnapshot:
        prev = latest_snapshot(self.s, tenant_id)
        snap = TopologySnapshot(tenant_id=tenant_id, algorithm_version=ALGORITHM_VERSION,
                                embedding_model=self.embedding_model, status="running",
                                params={"graph": self.gp.__dict__, "clustering": self.cp.__dict__})
        self.s.add(snap)
        self.s.flush()
        try:
            payload, stats = self._run(tenant_id, snap, prev)
            snap.payload, snap.stats, snap.status = payload, stats, "ok"
            tenant = self.s.get(Tenant, tenant_id)
            if tenant:
                tenant.settings = {**(tenant.settings or {}), "topology_dirty": False}
            self.s.add(AuditEvent(tenant_id=tenant_id, actor="system:topology", action="topology.build",
                                  object_type="snapshot", object_id=snap.id, details=stats))
        except Exception as exc:
            log.exception("Topology build failed")
            snap.status, snap.error = "error", str(exc)
            raise
        finally:
            snap.finished_at = datetime.now(timezone.utc)
            self.s.flush()
        return snap

    # ------------------------------------------------------------------------------------------------------
    def _run(self, tenant_id: str, snap: TopologySnapshot, prev: TopologySnapshot | None) -> tuple[dict, dict]:
        corpus = load_corpus(self.s, tenant_id, self.vectors)
        if not corpus.docs:
            return {"documents": {}, "domains": [], "edges": [], "doc_edges": [], "unassigned": []}, {"documents": 0}
        dg = build_document_graph(corpus, self.gp)
        clusters, unassigned = hybrid_clustering(dg, self.cp)
        prev_payload = prev.payload if prev else {}
        prev_domains = {d["stable_key"]: d for d in prev_payload.get("domains", [])}
        prev_docs = prev_payload.get("documents", {})
        tenant = self.s.get(Tenant, tenant_id)
        templates: dict[str, list[str]] = (tenant.settings or {}).get("coverage_templates", {}) if tenant else {}

        # ---- identities (lineage) -------------------------------------------------------------------
        prev_top = {k: set(d["document_ids"]) for k, d in prev_domains.items() if d.get("level") == 1}
        top_lineage = match_clusters([c.doc_ids for c in clusters], prev_top)
        areas: list[dict] = []  # flattened, top-level first
        for cl, lin in zip(clusters, top_lineage):
            areas.append({"key": lin.key, "cluster": cl, "level": 1, "parent": None, "lineage": lin})
            if cl.children:
                prev_children = {k: set(d["document_ids"]) for k, d in prev_domains.items()
                                 if d.get("parent_key") == lin.key}
                for ch, ch_lin in zip(cl.children, match_clusters([c.doc_ids for c in cl.children], prev_children)):
                    areas.append({"key": ch_lin.key, "cluster": ch, "level": 2, "parent": lin.key, "lineage": ch_lin})

        top_area_of = {d: a["key"] for a in areas if a["level"] == 1 for d in a["cluster"].members}

        # ---- labels + analysis ----------------------------------------------------------------------
        issue_drafts: dict[str, list[IssueDraft]] = {}
        alias_pairs: list[tuple[str, str]] = []
        for a in areas:
            ids = a["cluster"].doc_ids
            a["label"], a["description"] = label_for(corpus, ids)
            if a["level"] == 1:
                area_of = top_area_of
            else:
                area_of = {d: s["key"] for s in areas if s["parent"] == a["parent"] for d in s["cluster"].members}
            terms = distinctive_terms(corpus, ids, 10)
            required = None
            for keyword, topics in templates.items():
                if keyword.lower() in a["label"].lower() or keyword.lower() in terms:
                    required = topics
                    break
            a["analysis"] = analyse_area(corpus, dg, ids, area_of, a["key"], required, self.now)
            if a["level"] == 1:
                drafts = detect_issues(corpus, a["analysis"], a["label"])
                term_issues, pairs = detect_terminology_issues(corpus, ids, a["label"])
                alias_pairs.extend(pairs)
                issue_drafts[a["key"]] = drafts + term_issues

        orphan_drafts = detect_orphan_issues(corpus, unassigned)
        cross_conflicts = self._cross_area_conflicts(corpus, dg, top_area_of)
        for cf in cross_conflicts:
            issue_drafts.setdefault(top_area_of[cf.doc_a], []).extend(
                detect_issues(corpus, AreaAnalysis({}, [cf], [], {}, [], [], [], [], {}), "cross-area"))

        # ---- persistence: domains -------------------------------------------------------------------
        domain_rows: dict[str, KnowledgeDomain] = {}
        for a in areas:
            row = self.s.scalar(select(KnowledgeDomain).where(KnowledgeDomain.tenant_id == tenant_id,
                                                              KnowledgeDomain.stable_key == a["key"]))
            if row is None:
                row = KnowledgeDomain(tenant_id=tenant_id, stable_key=a["key"], level=a["level"], name=a["label"])
                self.s.add(row)
                self.s.flush()
            row.name, row.description, row.level, row.status = a["label"], a["description"], a["level"], "active"
            row.last_seen_snapshot_id = snap.id
            domain_rows[a["key"]] = row
        for a in areas:
            domain_rows[a["key"]].parent_id = domain_rows[a["parent"]].id if a["parent"] else None
        seen_ids = {r.id for r in domain_rows.values()}
        for row in self.s.scalars(select(KnowledgeDomain).where(KnowledgeDomain.tenant_id == tenant_id,
                                                                KnowledgeDomain.status == "active")):
            if row.id not in seen_ids:
                row.status = "inactive"

        # ---- issues (upsert by fingerprint) --------------------------------------------------------
        issue_ids_by_doc: dict[str, list[str]] = {}
        detected: set[str] = set()
        issues_by_area: dict[str, list[str]] = {}
        for key, drafts in [*issue_drafts.items(), (None, orphan_drafts)]:
            for dr in drafts:
                row = self.s.scalar(select(Issue).where(Issue.tenant_id == tenant_id, Issue.fingerprint == dr.fingerprint))
                if row is None:
                    row = Issue(tenant_id=tenant_id, fingerprint=dr.fingerprint, issue_type=dr.issue_type,
                                severity=dr.severity, title=dr.title)
                    self.s.add(row)
                elif row.status == "resolved":
                    row.status, row.resolved_at = "open", None  # regression: the problem is back
                row.metric, row.severity, row.confidence = dr.metric, dr.severity, dr.confidence
                row.title, row.description, row.recommendation = dr.title, dr.description, dr.recommendation
                row.evidence, row.domain_id = dr.evidence, (domain_rows[key].id if key else None)
                row.snapshot_id = row.snapshot_id or snap.id
                row.last_detected_snapshot_id = snap.id
                row.updated_at = self.now
                self.s.flush()
                detected.add(row.id)
                if key:
                    issues_by_area.setdefault(key, []).append(row.id)
                for d in dr.document_ids:
                    issue_ids_by_doc.setdefault(d, []).append(row.id)
        for row in self.s.scalars(select(Issue).where(Issue.tenant_id == tenant_id,
                                                      Issue.status.in_(("open", "investigating")))):
            if row.id not in detected:
                row.status, row.resolved_at = "resolved", self.now
                row.evidence = {**(row.evidence or {}), "resolution": "auto: no longer detected"}

        # ---- geometry + layouts ---------------------------------------------------------------------
        prev_layout = {k: d.get("position") for k, d in prev_domains.items() if d.get("position")}
        for a in areas:
            ids = sorted(a["cluster"].doc_ids)
            r0 = 0.55 + 0.22 * np.sqrt(len(ids))
            prev_local = {d: prev_docs[d]["local"] for d in ids if d in prev_docs and prev_docs[d].get("local")
                          and prev_docs[d].get("domain") == (a["key"] if a["level"] == 1 else a["parent"])}
            a["local"] = local_layout(dg.graph, ids, r0, prev_local)
            if a["level"] == 2:  # child shapes are computed around their own centroid
                parent_local = next(p["local"] for p in areas if p["key"] == a["parent"])
                cx = float(np.mean([parent_local[d][0] for d in ids]))
                cy = float(np.mean([parent_local[d][1] for d in ids]))
                a["center_in_parent"] = [round(cx, 3), round(cy, 3)]
                rel = {d: (parent_local[d][0] - cx, parent_local[d][1] - cy) for d in ids}
                a["geometry"] = area_geometry(a["key"], len(ids), a["analysis"], rel, issue_ids_by_doc)
            else:
                a["geometry"] = area_geometry(a["key"], len(ids), a["analysis"], a["local"], issue_ids_by_doc)

        top = [a for a in areas if a["level"] == 1]
        cross: dict[tuple[str, str], float] = {}
        cross_count: dict[tuple[str, str], int] = {}
        for u, v, dd in dg.graph.edges(data=True):
            ka, kb = top_area_of.get(u), top_area_of.get(v)
            if ka and kb and ka != kb:
                pair = tuple(sorted((ka, kb)))
                cross[pair] = cross.get(pair, 0.0) + dd["weight"]
                cross_count[pair] = cross_count.get(pair, 0) + 1
        positions = global_layout({a["key"]: a["geometry"]["radius"] for a in top}, cross, prev_layout)

        # ---- memberships, metrics, lineage, relations ------------------------------------------------
        for a in areas:
            row = domain_rows[a["key"]]
            for d, w in a["cluster"].members.items():
                self.s.add(ClusterMembership(tenant_id=tenant_id, snapshot_id=snap.id, domain_id=row.id, document_id=d,
                                             membership_weight=w, membership_type=membership_type(w)))
            for name, m in a["analysis"].metrics.items():
                self.s.add(QualityMetric(tenant_id=tenant_id, snapshot_id=snap.id, domain_id=row.id, metric_name=name,
                                         score=m.score, confidence=m.confidence, sample_size=m.sample_size,
                                         measured=m.measured, signals=m.signals))
            lin = a["lineage"]
            prev_ids = [self._domain_id(tenant_id, k) for k in lin.previous_keys] or [None]
            for pid in prev_ids:
                self.s.add(SnapshotClusterLineage(tenant_id=tenant_id, snapshot_id=snap.id, domain_id=row.id,
                                                  previous_domain_id=pid, relation=lin.relation, overlap=lin.overlap))
        self._persist_relations(tenant_id, snap.id, corpus, dg, areas, domain_rows, alias_pairs, cross)

        # ---- payload ---------------------------------------------------------------------------------
        documents: dict[str, dict] = {}
        for d, info in corpus.docs.items():
            documents[d] = {"title": info.title, "uri": info.uri, "terms": distinctive_terms(corpus, [d], 6),
                            "entities": sorted(corpus.entities[e].canonical_name for e in info.entities
                                               if e in corpus.entities)[:12],
                            "updated_at": info.updated_at.isoformat() if info.updated_at else None,
                            "owner": info.owner, "domain": top_area_of.get(d), "flags": []}
        for a in top:
            an: AreaAnalysis = a["analysis"]
            cx, cy, _ = positions[a["key"]]
            for d, (lx, ly) in a["local"].items():
                documents[d]["local"] = [lx, ly]
                documents[d]["position"] = [round(cx + lx, 3), round(cy + ly, 3), 0.0]
                documents[d]["membership"] = a["cluster"].members[d]
            for d in an.stale_docs:
                documents[d]["flags"].append("stale")
            for d in an.isolated_docs:
                documents[d]["flags"].append("isolated")
            for d in an.stub_docs:
                documents[d]["flags"].append("stub")
            for cf in an.conflicts:
                for d in (cf.doc_a, cf.doc_b):
                    if "conflict" not in documents[d]["flags"]:
                        documents[d]["flags"].append("conflict")
            for x, y, _, _ in an.duplicates:
                for d in (x, y):
                    if "duplicate" not in documents[d]["flags"]:
                        documents[d]["flags"].append("duplicate")
        self._place_unassigned(documents, unassigned, dg, top_area_of, positions, top)
        for d in documents:
            documents[d]["issue_ids"] = sorted(set(issue_ids_by_doc.get(d, [])))

        domain_payload = []
        for a in areas:
            an = a["analysis"]
            domain_payload.append({
                "id": domain_rows[a["key"]].id, "stable_key": a["key"], "level": a["level"],
                "parent_key": a["parent"], "label": a["label"], "description": a["description"],
                "document_ids": sorted(a["cluster"].doc_ids), "size": len(a["cluster"].members),
                "confidence": a["cluster"].confidence,
                "metrics": {k: m.as_dict() for k, m in an.metrics.items()}, "health": an.composite,
                "geometry": a["geometry"], "position": positions.get(a["key"]),
                "center_in_parent": a.get("center_in_parent"),
                "children": [c["key"] for c in areas if c["parent"] == a["key"]],
                "issue_ids": issues_by_area.get(a["key"], []),
                "lineage": {"relation": a["lineage"].relation, "previous_keys": a["lineage"].previous_keys,
                            "overlap": a["lineage"].overlap},
            })
        max_cross = max(cross.values(), default=1.0)
        edges = [{"source": a_, "target": b_, "type": "cross_domain_dependency", "weight": round(w / max_cross, 3),
                  "edge_count": cross_count[(a_, b_)]} for (a_, b_), w in sorted(cross.items(), key=lambda x: -x[1])]
        doc_edges = sorted(({"source": u, "target": v, "weight": dd["weight"], "signals": dd["signals"]}
                            for u, v, dd in dg.graph.edges(data=True)), key=lambda e: -e["weight"])[: 6 * len(documents)]
        payload = {"documents": documents, "domains": domain_payload, "edges": edges, "doc_edges": doc_edges,
                   "unassigned": sorted(unassigned), "generated_at": self.now.isoformat(),
                   "previous_snapshot_id": prev.id if prev else None}
        stats = {"documents": len(documents), "domains": len(top), "subareas": len(areas) - len(top),
                 "unassigned": len(unassigned), "graph_edges": dg.graph.number_of_edges(),
                 "issues_detected": len(detected), "duplicates": len(dg.duplicates)}
        return payload, stats

    # ------------------------------------------------------------------------------------------------------
    def _cross_area_conflicts(self, corpus: Corpus, dg: DocGraph, area_of: dict[str, str]):
        """Contradictions between documents of *different but related* areas (graph neighbours or
        shared entities), e.g. an old and a new platform documenting the same policy differently."""
        from kt.topology.metrics import find_conflicts

        conflicts, _ = find_conflicts(corpus, sorted(area_of))
        out = []
        for cf in conflicts:
            a, b = area_of.get(cf.doc_a), area_of.get(cf.doc_b)
            if a == b:
                continue
            related = dg.graph.has_edge(cf.doc_a, cf.doc_b) or bool(
                corpus.docs[cf.doc_a].entities & corpus.docs[cf.doc_b].entities)
            if related:
                cf.confidence = round(cf.confidence * 0.85, 2)  # weaker: contexts may legitimately differ
                out.append(cf)
        return out

    def _domain_id(self, tenant_id: str, key: str) -> str | None:
        return self.s.scalar(select(KnowledgeDomain.id).where(KnowledgeDomain.tenant_id == tenant_id,
                                                              KnowledgeDomain.stable_key == key))

    def _place_unassigned(self, documents, unassigned, dg: DocGraph, area_of, positions, top) -> None:
        radius = {a["key"]: a["geometry"]["radius"] for a in top}
        span = max((np.hypot(p[0], p[1]) + radius[k] for k, p in positions.items()), default=2.0)
        for i, d in enumerate(sorted(unassigned)):
            best = max(((dd["weight"], area_of[v]) for _, v, dd in dg.graph.edges(d, data=True) if v in area_of),
                       default=None)
            if best:
                cx, cy, _ = positions[best[1]]
                ang = (hash(d) % 628) / 100
                r = radius[best[1]] * 1.7
                documents[d]["position"] = [round(cx + r * np.cos(ang), 3), round(cy + r * np.sin(ang), 3), 0.0]
                documents[d]["nearest_domain"] = best[1]
            else:
                ang = 2 * np.pi * i / max(1, len(unassigned))
                documents[d]["position"] = [round((span + 1.5) * np.cos(ang), 3),
                                            round((span + 1.5) * np.sin(ang), 3), 0.0]
            documents[d]["flags"].append("unassigned")

    def _persist_relations(self, tenant_id, snapshot_id, corpus: Corpus, dg: DocGraph, areas, domain_rows,
                           alias_pairs, cross) -> None:
        # Computed relations are replaced per snapshot (history lives in snapshot payloads).
        self.s.execute(delete(Relation).where(Relation.tenant_id == tenant_id,
                                              Relation.provenance.in_(COMPUTED_PROVENANCE)))

        def add(rtype, ft, fid, tt, tid, w, conf, evidence=None, provenance="topology_engine"):
            self.s.add(Relation(tenant_id=tenant_id, relation_type=rtype, from_type=ft, from_id=fid, to_type=tt,
                                to_id=tid, weight=round(float(w), 4), confidence=round(float(conf), 3),
                                provenance=provenance, evidence=evidence or {}, snapshot_id=snapshot_id))

        for u, v, dd in dg.graph.edges(data=True):
            sig = dd["signals"]
            if sig["link"]:
                add("LINKS_TO", "document", u, "document", v, 1.0, 1.0, {"explicit": True})
            if sig["semantic"] >= 0.25:
                add("SEMANTICALLY_SIMILAR", "document", u, "document", v, dd["weight"], sig["semantic"], sig)
        for a, b, score, method in dg.duplicates:
            add("DUPLICATES", "document", a, "document", b, score, score, {"method": method})
        for area in areas:
            if area["level"] == 1:
                for cf in area["analysis"].conflicts:
                    add("CONTRADICTS", "document", cf.doc_a, "document", cf.doc_b, 1.0, cf.confidence,
                        {"chunk_ids": [cf.chunk_a, cf.chunk_b], "values": [cf.value_a, cf.value_b], "unit": cf.unit})
            for d, w in area["cluster"].members.items():
                add("BELONGS_TO", "document", d, "domain", domain_rows[area["key"]].id, w, area["cluster"].confidence)
        for e1, e2 in alias_pairs:
            add("SAME_AS_CANDIDATE", "entity", e1, "entity", e2, 0.5, 0.5, {"status": "candidate"})
        for (ka, kb), w in cross.items():
            add("RELATED_AREA", "domain", domain_rows[ka].id, "domain", domain_rows[kb].id, w, 0.7)
