import type { AreaNode, Geometry } from "./types";

export const SHAPE_COLOR: Record<Geometry["shape_class"], string> = {
  regular: "#5eead4",
  deformed: "#fbbf24",
  tangled: "#fb7185",
  restricted: "#64748b",
};

export const SHAPE_LABEL: Record<Geometry["shape_class"], string> = {
  regular: "Coherent",
  deformed: "Gaps / ambiguity",
  tangled: "Chaotic",
  restricted: "Partially visible",
};

/** Score 0..100 -> colour (rose -> amber -> teal). Used for matrices and bars. */
export function scoreColor(score: number | null | undefined, alpha = 1): string {
  if (score === null || score === undefined) return alpha < 1 ? `rgba(51,65,85,${alpha})` : "#334155";
  const stops: [number, [number, number, number]][] = [
    [0, [251, 113, 133]], [55, [251, 191, 36]], [80, [94, 234, 212]], [100, [45, 212, 191]],
  ];
  for (let i = 1; i < stops.length; i++) {
    if (score <= stops[i][0]) {
      const [a, ca] = stops[i - 1], [b, cb] = stops[i];
      const t = (score - a) / (b - a);
      const c = ca.map((v, k) => Math.round(v + (cb[k] - v) * t));
      return `rgba(${c[0]},${c[1]},${c[2]},${alpha})`;
    }
  }
  return `rgba(45,212,191,${alpha})`;
}

export const fmt = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined ? "—" : v.toFixed(digits);

export const ago = (iso: string | null | undefined) => {
  if (!iso) return "unknown";
  const days = Math.round((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days < 1) return "today";
  if (days < 60) return `${days} d ago`;
  if (days < 730) return `${Math.round(days / 30)} mo ago`;
  return `${(days / 365).toFixed(1)} y ago`;
};

export const shapeOf = (n: AreaNode) => n.geometry?.shape_class ?? n.shape_class;

export const METRIC_HELP: Record<string, string> = {
  cohesion: "Do the documents describe one coherent topic? (intra vs. nearest-area similarity)",
  connectivity: "Are documents linked to each other and to other areas? (fragments, isolated docs)",
  coverage: "Are the key concepts explained? Observed coverage is an estimate unless a template is configured.",
  consistency: "Do documents agree? Conflicting numeric claims about the same subject.",
  clarity: "Structure, sentence length, stub pages (heuristic estimate).",
  freshness: "Exponential decay of age, with half-life per document type.",
  duplication: "Share of documents that are near-duplicates of another document.",
  traceability: "Owner, source link, version and modification date present.",
};
