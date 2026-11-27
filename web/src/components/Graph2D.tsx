import { useMemo, useState } from "react";
import type { Topology } from "../types";
import { SHAPE_COLOR, fmt, shapeOf } from "../util";

/** Analytical view of the same areas: nodes sized by documents, edges weighted, same selection. */
export default function Graph2D({ topology, selectedKey, onSelect, onOpen }: {
  topology: Topology; selectedKey: string | null; onSelect: (k: string | null) => void; onOpen: (k: string) => void;
}) {
  const [hoverEdge, setHoverEdge] = useState<number | null>(null);
  const nodes = topology.nodes.filter((n) => n.position);
  const box = useMemo(() => {
    const xs = nodes.flatMap((n) => [n.position![0] - n.geometry.radius * 1.6, n.position![0] + n.geometry.radius * 1.6]);
    const ys = nodes.flatMap((n) => [-n.position![1] - n.geometry.radius * 1.6, -n.position![1] + n.geometry.radius * 1.6]);
    const pad = 1.2;
    return { x: Math.min(...xs) - pad, y: Math.min(...ys) - pad, w: Math.max(...xs) - Math.min(...xs) + 2 * pad,
             h: Math.max(...ys) - Math.min(...ys) + 2 * pad };
  }, [nodes]);
  const byKey = new Map(nodes.map((n) => [n.stable_key, n]));
  const unit = Math.max(box.w, box.h) / 100;
  return (
    <svg viewBox={`${box.x} ${box.y} ${box.w} ${box.h}`} style={{ width: "100%", height: "100%" }} onClick={() => onSelect(null)}
         role="img" aria-label="Graph of knowledge areas and their dependencies">
      {topology.edges.map((e, i) => {
        const a = byKey.get(e.source), b = byKey.get(e.target);
        if (!a || !b) return null;
        const [x1, y1, x2, y2] = [a.position![0], -a.position![1], b.position![0], -b.position![1]];
        return (
          <g key={i} onMouseEnter={() => setHoverEdge(i)} onMouseLeave={() => setHoverEdge(null)}>
            <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#7dd3fc" strokeOpacity={0.15 + 0.6 * (e.weight ?? 0.3)}
                  strokeWidth={unit * (0.25 + 1.2 * (e.weight ?? 0.3))} />
            <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="transparent" strokeWidth={unit * 3} />
            {hoverEdge === i && (
              <text x={(x1 + x2) / 2} y={(y1 + y2) / 2} fill="#e6edf7" fontSize={unit * 1.5} textAnchor="middle">
                {e.edge_count !== null ? `${e.edge_count} document relations · weight ${fmt(e.weight, 2)}` : "related"}
              </text>
            )}
          </g>
        );
      })}
      {nodes.map((n) => {
        const r = 0.35 + Math.sqrt(n.document_count) * 0.35;
        const sel = n.stable_key === selectedKey;
        const c = SHAPE_COLOR[shapeOf(n)];
        return (
          <g key={n.stable_key} transform={`translate(${n.position![0]},${-n.position![1]})`} style={{ cursor: "pointer" }}
             onClick={(ev) => { ev.stopPropagation(); onSelect(n.stable_key); }} onDoubleClick={() => onOpen(n.stable_key)}>
            <circle r={r} fill={c} fillOpacity={sel ? 0.35 : 0.18} stroke={c} strokeWidth={unit * (sel ? 0.8 : 0.4)}
                    strokeDasharray={n.visibility === "partial" ? `${unit} ${unit}` : undefined} />
            <text y={r + unit * 2.4} textAnchor="middle" fill="#e6edf7" fontSize={unit * 1.6} fontWeight={600}>{n.label}</text>
            <text y={r + unit * 4.2} textAnchor="middle" fill="#93a1b8" fontSize={unit * 1.3}>
              {n.document_count} docs · {n.health === null ? "restricted" : `health ${fmt(n.health)}`} · {n.issue_ids.length} issues
            </text>
          </g>
        );
      })}
    </svg>
  );
}
