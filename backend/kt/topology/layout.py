"""Stable layouts. Previous positions seed the next run, so the map does not jump between snapshots."""

from __future__ import annotations

import hashlib
import math

import networkx as nx
import numpy as np


def _hash_pos(key: str, scale: float) -> tuple[float, float]:
    h = hashlib.sha256(key.encode()).digest()
    ang = int.from_bytes(h[:4], "little") / 2**32 * 2 * math.pi
    rad = (0.4 + 0.6 * int.from_bytes(h[4:8], "little") / 2**32) * scale
    return rad * math.cos(ang), rad * math.sin(ang)


def global_layout(
    nodes: dict[str, float],  # key -> radius
    edges: dict[tuple[str, str], float],
    previous: dict[str, list[float]] | None = None,
    seed: int = 7,
) -> dict[str, list[float]]:
    previous = previous or {}
    if not nodes:
        return {}
    g = nx.Graph()
    g.add_nodes_from(nodes)
    for (a, b), w in edges.items():
        if a in nodes and b in nodes:
            g.add_edge(a, b, weight=w)
    scale = 2.0 + math.sqrt(sum(r * r for r in nodes.values()))
    init = {k: (np.array(previous[k][:2]) if k in previous else np.array(_hash_pos(k, scale))) for k in nodes}
    if len(nodes) == 1:
        pos = {k: np.zeros(2) for k in nodes}
    else:
        stable = sum(1 for k in nodes if k in previous) / len(nodes)
        pos = nx.spring_layout(g, pos=init, weight="weight", iterations=25 if stable > 0.5 else 120, seed=seed,
                               k=1.6 / math.sqrt(len(nodes)), scale=None)
        # spring_layout returns arbitrary scale; normalise to the drawing scale
        arr = np.stack(list(pos.values()))
        arr = arr - arr.mean(axis=0)
        span = np.abs(arr).max() or 1.0
        pos = {k: arr[i] / span * scale for i, k in enumerate(pos)}
        if stable > 0.5:  # damp movement of known areas
            pos = {k: (0.65 * np.array(previous[k][:2]) + 0.35 * p) if k in previous else p for k, p in pos.items()}
    pos = _remove_overlaps({k: np.array(v, dtype=float) for k, v in pos.items()}, nodes)
    return {k: [round(float(v[0]), 3), round(float(v[1]), 3), 0.0] for k, v in pos.items()}


def _remove_overlaps(pos: dict[str, np.ndarray], radii: dict[str, float], gap: float = 0.6,
                     iterations: int = 200) -> dict[str, np.ndarray]:
    keys = sorted(pos)
    for _ in range(iterations):
        moved = False
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                d = pos[b] - pos[a]
                dist = float(np.linalg.norm(d))
                need = radii[a] * 1.35 + radii[b] * 1.35 + gap
                if dist < need:
                    direction = d / dist if dist > 1e-6 else np.array([1.0, 0.0])
                    push = (need - dist) / 2
                    pos[a] = pos[a] - direction * push
                    pos[b] = pos[b] + direction * push
                    moved = True
        if not moved:
            break
    return pos


def local_layout(
    g: nx.Graph, doc_ids: list[str], radius: float, previous: dict[str, list[float]] | None = None, seed: int = 11
) -> dict[str, tuple[float, float]]:
    """Positions of documents inside an area, normalised into a disc of ``radius``."""
    previous = previous or {}
    if not doc_ids:
        return {}
    if len(doc_ids) == 1:
        return {doc_ids[0]: (0.0, 0.0)}
    sub = g.subgraph(doc_ids)
    init = {d: (np.array(previous[d][:2]) / max(radius, 1e-6) if d in previous else np.array(_hash_pos(d, 1.0)))
            for d in doc_ids}
    pos = nx.spring_layout(sub, pos=init, weight="weight", seed=seed, iterations=60)
    arr = np.stack([pos[d] for d in doc_ids])
    arr = arr - arr.mean(axis=0)
    span = np.linalg.norm(arr, axis=1).max() or 1.0
    arr = arr / span * radius * 0.82
    return {d: (round(float(arr[i, 0]), 4), round(float(arr[i, 1]), 4)) for i, d in enumerate(doc_ids)}
