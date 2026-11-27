"""Cluster identity across snapshots (stable keys, continued / split / merged / new)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass
class LineageResult:
    key: str
    relation: str  # new | continued | split_from | merged_from
    previous_keys: list[str]
    overlap: float


def match_clusters(new: list[set[str]], previous: dict[str, set[str]], min_jaccard: float = 0.3) -> list[LineageResult]:
    pairs = []
    for i, members in enumerate(new):
        for key, old in previous.items():
            inter = len(members & old)
            if inter:
                pairs.append((inter / len(members | old), i, key, inter))
    pairs.sort(reverse=True)
    assigned: dict[int, tuple[str, float]] = {}
    used: set[str] = set()
    for jac, i, key, _ in pairs:
        if jac >= min_jaccard and i not in assigned and key not in used:
            assigned[i] = (key, jac)
            used.add(key)
    results = []
    for i, members in enumerate(new):
        contributors = [key for key, old in previous.items() if len(members & old) >= max(1, 0.5 * len(old))]
        if i in assigned:
            key, jac = assigned[i]
            merged = [k for k in contributors if k != key]
            results.append(LineageResult(key, "merged_from" if merged else "continued", [key, *merged], round(jac, 3)))
            continue
        best = max(((len(members & old) / len(members), k) for k, old in previous.items()), default=(0.0, None))
        new_key = "dom_" + uuid.uuid4().hex[:10]
        if best[1] is not None and best[0] >= 0.4:
            results.append(LineageResult(new_key, "split_from", [best[1]], round(best[0], 3)))
        else:
            results.append(LineageResult(new_key, "new", [], 0.0))
    return results
