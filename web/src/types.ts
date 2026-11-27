export type MetricName =
  | "cohesion" | "connectivity" | "coverage" | "consistency"
  | "clarity" | "freshness" | "duplication" | "traceability";

export const METRICS: MetricName[] = [
  "cohesion", "connectivity", "coverage", "consistency", "clarity", "freshness", "duplication", "traceability",
];

export interface Metric {
  score: number | null;
  confidence: number;
  sample_size: number;
  measured: boolean;
  signals: Record<string, unknown>;
}

export interface Explanation {
  feature: string;
  metric?: string;
  score?: number;
  angle?: number;
  text: string;
  document_ids?: string[];
  issue_ids?: string[];
  reasons?: string[];
  count?: number;
}

export interface Geometry {
  shape_class: "regular" | "deformed" | "tangled" | "restricted";
  chaos: number | null;
  radius: number;
  outline: [number, number][];
  islands: { center: [number, number]; radius: number; document_ids: string[] }[];
  strands: [number, number, number][][];
  texture: { freshness: number; grain: number } | null;
  boundary_opacity: number;
  explanations: Explanation[];
}

export interface AreaNode {
  id: string;
  stable_key: string;
  level: number;
  parent_key: string | null;
  label: string;
  description: string;
  document_count: number;
  visibility: "full" | "partial";
  confidence: number | null;
  health: number | null;
  metrics: Record<MetricName, Metric> | null;
  shape_class: Geometry["shape_class"];
  position: [number, number, number] | null;
  center_in_parent: [number, number] | null;
  children: string[];
  issue_ids: string[];
  lineage: { relation: string; previous_keys: string[]; overlap: number } | null;
  geometry: Geometry;
}

export interface DocInfo {
  title: string;
  uri: string | null;
  terms: string[];
  entities: string[];
  updated_at: string | null;
  owner: string | null;
  domain: string | null;
  flags: string[];
  local?: [number, number];
  position?: [number, number, number];
  membership?: number;
  issue_ids: string[];
}

export interface Topology {
  snapshot_id: string;
  created_at: string;
  algorithm_version: string;
  embedding_model: string;
  privileged: boolean;
  nodes: AreaNode[];
  edges: { source: string; target: string; weight: number | null; edge_count: number | null; type: string }[];
  documents?: Record<string, DocInfo>;
  summary: { documents: number; areas: number; unassigned: number };
}

export interface DocEdge {
  source: string;
  target: string;
  weight: number;
  signals: { semantic: number; entity: number; link: number; context: number; cosine: number };
}

export interface AreaMap {
  snapshot_id: string;
  domain: AreaNode;
  documents: Record<string, DocInfo>;
  edges: DocEdge[];
  children: AreaNode[];
  external_links: { from: string; document_id: string; title: string; domain: string | null; weight: number }[];
}

export interface Issue {
  id: string;
  issue_type: string;
  metric: string | null;
  severity: "high" | "medium" | "low";
  confidence: number;
  status: string;
  title: string;
  description: string | null;
  recommendation: string | null;
  evidence: {
    document_ids?: string[];
    quotes?: { document_id: string; chunk_id: string; quote: string }[];
    [k: string]: unknown;
  };
  domain_id: string | null;
  assigned_to: string | null;
  created_at: string;
  updated_at: string;
  documents?: { document_id: string; title: string; uri: string | null; owner: string | null; updated_at: string | null }[];
  evidence_chunks?: { chunk_id: string; document_id: string; content: string }[];
}

export interface SearchResult {
  query: string;
  results: {
    document_id: string;
    title: string;
    uri: string | null;
    score: number;
    retrieval_reasons: string[];
    evidence: { chunk_id: string; section: string | null; quote: string | null; relevance: number; tokens: number }[];
    updated_at: string | null;
    owner: string | null;
  }[];
  related_entities: { id: string; name: string; type: string; mentions: number }[];
  related_areas: { domain_id: string; stable_key: string; label: string | null; health: number | null }[];
  warnings: { type: string; issue_id: string; severity: string; message: string; document_ids: string[] }[];
  usage: { candidates: number; returned_chunks: number; estimated_tokens: number; budget_tokens: number };
}

export interface Snapshot {
  snapshot_id: string;
  created_at: string;
  algorithm_version: string;
  embedding_model: string;
  stats: Record<string, number>;
}

export interface Change {
  type: string;
  stable_key: string;
  label: string;
  previous_label?: string;
  previous_keys?: string[];
  document_delta?: number;
  metric_delta?: Record<string, { from: number; to: number; delta: number }>;
  health?: { from: number | null; to: number | null };
}
