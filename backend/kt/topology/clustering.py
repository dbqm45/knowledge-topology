"""Hybrid clustering: graph communities (Leiden, fallback Louvain) cross-checked by HDBSCAN.

* Leiden/Louvain decides boundaries on the multi-signal graph (links + entities + semantics).
* HDBSCAN on the embedding space provides an independent density view; agreement between the
  two becomes the cluster *confidence*. Documents that HDBSCAN marks as noise and that are weakly
  attached to their community become ``low_confidence`` members.
* Documents are never forced into a cluster: isolated docs and tiny communities stay unassigned.
* An LLM may *name* clusters later; it never decides their boundaries.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import networkx as nx
import numpy as np

from kt.topology.graph import DocGraph


@dataclass
class ClusterParams:
    min_cluster_size: int = 3
    resolution: float = 1.0
    sub_resolution: float = 1.3
    min_subarea_parent: int = 8
    seed: int = 42


@dataclass
class Cluster:
    members: dict[str, float]  # doc_id -> membership weight
    confidence: float
    children: list["Cluster"] = field(default_factory=list)

    @property
    def doc_ids(self) -> set[str]:
        return set(self.members)


def _communities(g: nx.Graph, resolution: float, seed: int) -> list[set[str]]:
    if g.number_of_edges() == 0:
        return [{n} for n in g.nodes]
    try:  # optional: pip install knowledge-topology[leiden]
        import igraph as ig
        import leidenalg

        nodes = list(g.nodes)
        idx = {n: i for i, n in enumerate(nodes)}
        ig_g = ig.Graph(n=len(nodes), edges=[(idx[a], idx[b]) for a, b in g.edges])
        ig_g.es["weight"] = [g[a][b]["weight"] for a, b in g.edges]
        part = leidenalg.find_partition(ig_g, leidenalg.RBConfigurationVertexPartition, weights="weight",
                                        resolution_parameter=resolution, seed=seed)
        return [{nodes[i] for i in comm} for comm in part]
    except ImportError:
        return [set(c) for c in nx.community.louvain_communities(g, weight="weight", resolution=resolution,
                                                                  seed=seed)]


def _hdbscan_labels(dg: DocGraph, ids: list[str], min_size: int) -> dict[str, int]:
    if len(ids) < max(6, min_size * 2):
        return {}
    try:
        from sklearn.cluster import HDBSCAN
    except ImportError:  # pragma: no cover
        return {}
    pos = {i: k for k, i in enumerate(dg.ids)}
    sub = dg.sim[np.ix_([pos[i] for i in ids], [pos[i] for i in ids])]
    dist = np.clip(1.0 - sub, 0, 2)
    kwargs = {"min_cluster_size": min_size, "metric": "precomputed", "allow_single_cluster": True}
    try:
        model = HDBSCAN(copy=True, **kwargs)
    except TypeError:  # older scikit-learn
        model = HDBSCAN(**kwargs)
    labels = model.fit_predict(dist)
    return dict(zip(ids, (int(x) for x in labels)))


def _membership(g: nx.Graph, node: str, community: set[str]) -> float:
    total = sum(d["weight"] for _, _, d in g.edges(node, data=True))
    if total == 0:
        return 0.0
    inside = sum(d["weight"] for _, v, d in g.edges(node, data=True) if v in community)
    return inside / total


def _partition(dg: DocGraph, g: nx.Graph, params: ClusterParams, resolution: float) -> tuple[list[Cluster], set[str]]:
    comms = _communities(g, resolution, params.seed)
    hdb = _hdbscan_labels(dg, list(g.nodes), params.min_cluster_size)
    clusters: list[Cluster] = []
    unassigned: set[str] = set()
    for comm in sorted(comms, key=lambda c: (-len(c), sorted(c)[0])):
        if len(comm) < params.min_cluster_size:
            unassigned |= comm
            continue
        members = {n: round(_membership(g, n, comm), 3) for n in comm}
        if hdb:
            labels = [hdb[n] for n in comm if hdb.get(n, -1) >= 0]
            modal = Counter(labels).most_common(1)[0][0] if labels else None
            agree = sum(1 for n in comm if hdb.get(n, -1) == modal) / len(comm) if modal is not None else 0.3
        else:
            agree = 0.6  # no independent view available: moderate confidence
        mean_membership = float(np.mean(list(members.values())))
        clusters.append(Cluster(members, round(0.5 * agree + 0.5 * mean_membership, 3)))
    return clusters, unassigned


def hybrid_clustering(dg: DocGraph, params: ClusterParams | None = None) -> tuple[list[Cluster], set[str]]:
    p = params or ClusterParams()
    clusters, unassigned = _partition(dg, dg.graph, p, p.resolution)
    for cl in clusters:
        if len(cl.members) >= p.min_subarea_parent:
            sub_g = dg.graph.subgraph(cl.doc_ids).copy()
            sub_p = ClusterParams(min_cluster_size=max(2, p.min_cluster_size - 1), seed=p.seed)
            children, _ = _partition(dg, sub_g, sub_p, p.sub_resolution)
            if len(children) >= 2:
                cl.children = children
    return clusters, unassigned


def membership_type(weight: float) -> str:
    if weight >= 0.6:
        return "core"
    if weight >= 0.3:
        return "peripheral"
    return "low_confidence"
