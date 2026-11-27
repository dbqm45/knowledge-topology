"""Geometry Engine: deterministic translation of metrics + structure into shape.

The geometry is a *representation* of the metrics, never a source of truth. Rules:

* size   (base radius r0)  -> scale of knowledge (document count), NOT quality;
* outline regularity       -> cohesion            r(θ) = r0·[1 + a·sin(kθ+φ) + b·L(θ) + c·C(θ)]
* local dents  L(θ)        -> gaps: stale / stub / isolated documents at their angular position
* jagged zones C(θ)        -> conflicts and duplicates at the angular position of the documents involved
* islands                  -> disconnected components (connectivity)
* strands ("tangle")       -> chaos = low cohesion + conflicts + duplication + fragmentation
* texture / boundary       -> freshness / clarity + traceability

The same snapshot always produces the same geometry (seeded by the area's stable key).
Every visible feature carries an ``explanations`` entry pointing to metric + documents + issues.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np

from kt.topology.metrics import AreaAnalysis

SAMPLES = 144


def _seed(key: str) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)


def _angle(p) -> float:
    return math.atan2(p[1], p[0]) % (2 * math.pi)


def _bump(theta: np.ndarray, center: float, sigma: float) -> np.ndarray:
    d = np.angle(np.exp(1j * (theta - center)))  # wrapped angular distance
    return np.exp(-(d**2) / (2 * sigma**2))


def chaos_index(m: dict[str, float]) -> float:
    """1 - weighted quality of the signals that make knowledge *chaotic* (not merely thin or old)."""
    return float(np.clip(1 - (0.15 * m["cohesion"] + 0.30 * m["consistency"] + 0.20 * m["duplication"]
                              + 0.10 * m["connectivity"] + 0.10 * m["clarity"] + 0.15 * m["traceability"]) / 100,
                         0, 1))


def shape_class(chaos: float) -> str:
    if chaos < 0.2:
        return "regular"
    if chaos < 0.4:
        return "deformed"
    return "tangled"


def area_geometry(
    stable_key: str,
    size: int,
    analysis: AreaAnalysis,
    local_pos: dict[str, tuple[float, float]],
    issues_by_doc: dict[str, list[str]],
) -> dict:
    rng = np.random.default_rng(_seed(stable_key))
    m = {k: (v.score if v.score is not None else 50.0) for k, v in analysis.metrics.items()}
    r0 = round(0.55 + 0.22 * math.sqrt(size), 3)
    theta = np.linspace(0, 2 * math.pi, SAMPLES, endpoint=False)
    explanations: list[dict] = []

    # 1) Global irregularity from cohesion.
    a = 0.26 * (1 - m["cohesion"] / 100) ** 1.2
    k = 2 + int(rng.integers(0, 3))
    phi = float(rng.uniform(0, 2 * math.pi))
    harmonic = a * np.sin(k * theta + phi) + 0.45 * a * np.sin((k + 3) * theta + 2 * phi)
    if a > 0.05:
        explanations.append({"feature": "irregular_outline", "metric": "cohesion", "score": round(m["cohesion"], 1),
                             "text": f"Irregular outline: cohesion {m['cohesion']:.0f}/100 — documents in this area "
                                     f"cover loosely related topics."})

    # 2) Dents (gaps) at the angular position of stale / stub / isolated documents.
    gap_weight: dict[str, float] = {}
    for d, ratio in analysis.stale_docs.items():
        gap_weight[d] = gap_weight.get(d, 0) + min(1.0, 0.35 * ratio)
    for d in analysis.stub_docs:
        gap_weight[d] = gap_weight.get(d, 0) + 0.5
    for d in analysis.isolated_docs:
        gap_weight[d] = gap_weight.get(d, 0) + 0.7
    L = np.zeros_like(theta)
    for d, w in gap_weight.items():
        if d in local_pos:
            L -= min(w, 1.2) * _bump(theta, _angle(local_pos[d]), 0.32)
    if L.min() < 0:
        L = L / max(1.0, -L.min())
    b = 0.12 + 0.28 * (1 - min(m["coverage"], m["freshness"]) / 100)
    for d, _w in sorted(gap_weight.items(), key=lambda x: -x[1])[:8]:
        if d in local_pos:
            reasons = [r for r, cond in (("stale", d in analysis.stale_docs), ("stub", d in analysis.stub_docs),
                                         ("isolated", d in analysis.isolated_docs)) if cond]
            explanations.append({"feature": "dent", "metric": "freshness" if "stale" in reasons else "coverage",
                                 "angle": round(_angle(local_pos[d]), 3), "document_ids": [d], "reasons": reasons,
                                 "issue_ids": issues_by_doc.get(d, []),
                                 "text": "Dent: " + ", ".join(reasons) + " document weakens this side of the area."})

    # 3) Jagged zones: conflicts (strong) and duplicates (weaker).
    C = np.zeros_like(theta)
    jag_docs: dict[str, float] = {}
    for cf in analysis.conflicts:
        for d in (cf.doc_a, cf.doc_b):
            jag_docs[d] = jag_docs.get(d, 0) + 1.0
    for a_, b_, _, _ in analysis.duplicates:
        for d in (a_, b_):
            jag_docs[d] = jag_docs.get(d, 0) + 0.5
    freq = 11 + int(rng.integers(0, 5))
    for d, w in jag_docs.items():
        if d in local_pos:
            C += min(w, 2.0) * _bump(theta, _angle(local_pos[d]), 0.28) * np.abs(np.sin(freq * theta + phi))
    if C.max() > 0:
        C = C / max(1.0, C.max())
    c = 0.32 * (1 - m["consistency"] / 100) + 0.16 * (1 - m["duplication"] / 100)
    for d in list(jag_docs)[:8]:
        if d in local_pos:
            explanations.append({"feature": "jagged_zone", "metric": "consistency", "angle": round(_angle(local_pos[d]), 3),
                                 "document_ids": [d], "issue_ids": issues_by_doc.get(d, []),
                                 "text": "Jagged zone: conflicting or duplicated content."})

    r = r0 * (1 + harmonic + b * L + c * C)
    r = np.maximum(r, 0.3 * r0)
    outline = [[round(float(rr * math.cos(t)), 4), round(float(rr * math.sin(t)), 4)] for rr, t in zip(r, theta)]

    # 4) Islands: secondary connected components drift outside the main body.
    islands = []
    if len(analysis.components) > 1:
        for comp in analysis.components[1:6]:
            pts = [local_pos[d] for d in comp if d in local_pos]
            ang = float(np.mean([_angle(p) for p in pts])) if pts else float(rng.uniform(0, 2 * math.pi))
            dist = r0 * (1.25 + 0.15 * len(islands))
            islands.append({"center": [round(dist * math.cos(ang), 4), round(dist * math.sin(ang), 4)],
                            "radius": round(0.18 + 0.12 * math.sqrt(len(comp)), 3), "document_ids": sorted(comp)})
        explanations.append({"feature": "islands", "metric": "connectivity", "score": round(m["connectivity"], 1),
                             "count": len(islands),
                             "text": f"{len(islands)} detached fragment(s): parts of this area are not connected "
                                     f"to the rest (connectivity {m['connectivity']:.0f}/100)."})

    # 5) Strands — the "ball of yarn". Count and amplitude grow with chaos.
    chaos = chaos_index(m)
    n_strands = int(round(2 + 30 * chaos**1.4))
    strands = []
    for i in range(n_strands):
        p1, p2, p3 = rng.uniform(0, 2 * math.pi, 3)
        m1, m2 = int(rng.integers(1, 4)), int(rng.integers(2, 6))
        wobble = 0.15 + 0.85 * chaos
        t = np.linspace(0, 2 * math.pi, 64)
        rad = r0 * (0.25 + 0.6 * (0.5 + 0.5 * np.sin(m1 * t + p1)) * (0.35 + 0.65 * wobble))
        ang = t * (1 if i % 2 else -1) + wobble * np.sin(m2 * t + p2)
        z = r0 * 0.6 * wobble * np.sin((m1 + m2) * t + p3)
        strands.append([[round(float(x), 3), round(float(y), 3), round(float(zz), 3)]
                        for x, y, zz in zip(rad * np.cos(ang), rad * np.sin(ang), z)])
    cls = shape_class(chaos)
    if cls != "regular":
        explanations.append({"feature": "tangle", "metric": "chaos_index", "score": round(100 * chaos, 1),
                             "text": f"{n_strands} internal strands: chaos index {100 * chaos:.0f}/100 "
                                     f"(low cohesion, conflicts, duplicates, fragmentation)."})

    return {
        "shape_class": cls,
        "chaos": round(chaos, 3),
        "radius": r0,
        "outline": outline,
        "islands": islands,
        "strands": strands,
        "texture": {"freshness": round(m["freshness"] / 100, 3), "grain": round(1 - m["freshness"] / 100, 3)},
        "boundary_opacity": round(0.35 + 0.65 * (m["clarity"] + m["traceability"]) / 200, 3),
        "parameters": {"a": round(a, 4), "b": round(b, 4), "c": round(c, 4), "k": k, "phi": round(phi, 4)},
        "explanations": explanations,
    }


def neutral_geometry(size: int) -> dict:
    """Shape for areas whose metrics the caller may not see: a plain circle that leaks nothing."""
    r0 = round(0.55 + 0.22 * math.sqrt(size), 3)
    theta = np.linspace(0, 2 * math.pi, 48, endpoint=False)
    return {"shape_class": "restricted", "chaos": None, "radius": r0,
            "outline": [[round(float(r0 * math.cos(t)), 4), round(float(r0 * math.sin(t)), 4)] for t in theta],
            "islands": [], "strands": [], "texture": None, "boundary_opacity": 0.4, "parameters": {},
            "explanations": [{"feature": "restricted", "text": "Quality details are hidden: you can see only part "
                                                               "of this area."}]}
