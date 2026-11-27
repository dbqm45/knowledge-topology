import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import MetricBars from "../components/MetricBars";
import type { AreaMap, DocEdge } from "../types";
import { SHAPE_COLOR, SHAPE_LABEL, ago, fmt, shapeOf } from "../util";

const FLAG_STYLE: Record<string, { color: string; label: string }> = {
  conflict: { color: "#fb7185", label: "conflict" },
  duplicate: { color: "#c084fc", label: "duplicate" },
  stale: { color: "#fbbf24", label: "stale" },
  isolated: { color: "#94a3b8", label: "isolated" },
  stub: { color: "#94a3b8", label: "stub" },
};

interface Related { related_documents: { document_id: string; title: string; uri: string | null; relations: string[]; weight: number }[]; entities: { name: string; type: string }[] }

export default function DomainMapView({ areaKey, onOpenIssue, onBack }: { areaKey: string; onOpenIssue: (id: string) => void; onBack: () => void }) {
  const [map, setMap] = useState<AreaMap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [doc, setDoc] = useState<string | null>(null);
  const [edge, setEdge] = useState<DocEdge | null>(null);
  const [related, setRelated] = useState<Related | null>(null);

  useEffect(() => {
    setMap(null); setDoc(null); setEdge(null);
    api<AreaMap>(`/api/v1/domains/${areaKey}`).then(setMap).catch((e) => setError(e.message));
  }, [areaKey]);
  useEffect(() => {
    setRelated(null);
    if (doc) api<Related>(`/api/v1/documents/${doc}/related`).then(setRelated).catch(() => setRelated(null));
  }, [doc]);

  const geo = map?.domain.geometry;
  const extent = useMemo(() => {
    if (!geo) return 3;
    return Math.max(geo.radius * 1.7, ...geo.islands.map((i) => Math.hypot(...i.center) + i.radius + 0.3));
  }, [geo]);
  if (error) return <div className="page"><p className="error">{error}</p></div>;
  if (!map || !geo) return <div className="empty">Loading area…</div>;
  const d = map.domain;
  const color = SHAPE_COLOR[shapeOf(d)];
  const u = extent / 100;
  const path = (pts: [number, number][], ox = 0, oy = 0) => "M" + pts.map(([x, y]) => `${x + ox},${-(y + oy)}`).join("L") + "Z";
  const docs = Object.entries(map.documents);
  const selDoc = doc ? map.documents[doc] : null;

  return (
    <div className="mapwrap">
      <div style={{ position: "relative" }}>
        <div className="stage" style={{ position: "absolute", inset: 0 }}>
          <div className="toolbar">
            <button className="btn small" onClick={onBack}>← Universe</button>
            <span className={`badge ${shapeOf(d)}`}>{SHAPE_LABEL[shapeOf(d)]}</span>
            <b>{d.label}</b>
          </div>
          <svg viewBox={`${-extent} ${-extent} ${2 * extent} ${2 * extent}`} onClick={() => { setDoc(null); setEdge(null); }}
               role="img" aria-label={`Map of area ${d.label}`}>
            <path d={path(geo.outline)} fill={color} fillOpacity={0.08} stroke={color} strokeOpacity={geo.boundary_opacity} strokeWidth={u * 0.6} />
            {geo.islands.map((is, i) => <circle key={i} cx={is.center[0]} cy={-is.center[1]} r={is.radius} fill={color} fillOpacity={0.08} stroke={color} strokeWidth={u * 0.5} />)}
            {map.children.map((c) => c.center_in_parent && (
              <g key={c.stable_key}>
                <path d={path(c.geometry.outline.map(([x, y]) => [x * 0.55, y * 0.55]), c.center_in_parent[0], c.center_in_parent[1])}
                      fill="none" stroke={SHAPE_COLOR[shapeOf(c)]} strokeDasharray={`${u * 1.5} ${u}`} strokeOpacity={0.7} strokeWidth={u * 0.35} />
                <text x={c.center_in_parent[0]} y={-c.center_in_parent[1] - c.geometry.radius * 0.6} fill="#93a1b8" fontSize={u * 2.6} textAnchor="middle">{c.label}</text>
              </g>
            ))}
            {geo.explanations.filter((e) => e.angle !== undefined).map((e, i) => {
              const r = geo.radius * 1.08;
              return (
                <g key={i} transform={`translate(${r * Math.cos(e.angle!)},${-r * Math.sin(e.angle!)})`}>
                  <circle r={u * 1.6} fill={e.feature === "dent" ? "#fbbf24" : "#fb7185"} fillOpacity={0.85}>
                    <title>{e.text}</title>
                  </circle>
                </g>
              );
            })}
            {map.edges.map((e, i) => {
              const a = map.documents[e.source]?.local, b = map.documents[e.target]?.local;
              if (!a || !b) return null;
              const sel = edge === e;
              return (
                <g key={i} className="edge" onClick={(ev) => { ev.stopPropagation(); setEdge(e); setDoc(null); }}>
                  <line x1={a[0]} y1={-a[1]} x2={b[0]} y2={-b[1]} stroke={e.signals.link ? "#7dd3fc" : "#94a3b8"}
                        strokeOpacity={sel ? 1 : 0.15 + 0.6 * e.weight} strokeWidth={u * (sel ? 0.7 : 0.25 + e.weight * 0.6)}
                        strokeDasharray={e.signals.link ? undefined : `${u} ${u * 0.7}`} />
                  <line x1={a[0]} y1={-a[1]} x2={b[0]} y2={-b[1]} stroke="transparent" strokeWidth={u * 2.2} />
                </g>
              );
            })}
            {docs.map(([id, info]) => {
              if (!info.local) return null;
              const flag = info.flags.find((f) => FLAG_STYLE[f]);
              const sel = id === doc;
              return (
                <g key={id} className="doc-node" transform={`translate(${info.local[0]},${-info.local[1]})`}
                   onClick={(ev) => { ev.stopPropagation(); setDoc(id); setEdge(null); }}>
                  {flag && <circle r={u * 3} fill="none" stroke={FLAG_STYLE[flag].color} strokeWidth={u * 0.5}
                                   strokeDasharray={flag === "stale" ? `${u} ${u * 0.6}` : undefined} />}
                  <circle className="core" r={u * (sel ? 2.2 : 1.7)} fill={sel ? "#fff" : "#e2e8f0"} stroke="#0b0f17" strokeWidth={u * 0.3} />
                  <text y={u * 5.5} textAnchor="middle" fill="#cbd5e1" fontSize={u * 2.3}>{info.title.length > 34 ? info.title.slice(0, 32) + "…" : info.title}</text>
                </g>
              );
            })}
          </svg>
          <div className="legend">
            {Object.entries(FLAG_STYLE).slice(0, 4).map(([k, v]) => <span key={k}><i style={{ background: v.color }} />{v.label}</span>)}
            <span><i style={{ background: "#7dd3fc" }} />explicit link</span>
            <span><i style={{ background: "#94a3b8" }} />semantic relation</span>
          </div>
        </div>
      </div>
      <aside className="side">
        {selDoc && doc ? (
          <div>
            <div className="faint" style={{ fontSize: 12 }}>Document</div>
            <h2>{selDoc.title}</h2>
            <div className="row" style={{ margin: "6px 0" }}>
              {selDoc.flags.map((f) => <span key={f} className="pill" style={{ color: FLAG_STYLE[f]?.color }}>{f}</span>)}
            </div>
            <div className="muted" style={{ fontSize: 12.5 }}>
              Owner: {selDoc.owner ?? <span className="error">none</span>} · updated {ago(selDoc.updated_at)}
              {selDoc.membership !== undefined && <> · membership {fmt(selDoc.membership, 2)}</>}
            </div>
            {selDoc.uri && <p><a href={selDoc.uri} target="_blank" rel="noreferrer">Open in source ↗</a></p>}
            {selDoc.entities.length > 0 && <p className="muted" style={{ fontSize: 12 }}>Entities: {selDoc.entities.join(", ")}</p>}
            {selDoc.issue_ids.length > 0 && (
              <div className="list">{selDoc.issue_ids.map((i) => <div key={i} className="item" onClick={() => onOpenIssue(i)}>Issue →</div>)}</div>
            )}
            {related && (
              <>
                <hr className="sep" />
                <h3 style={{ fontSize: 13 }}>Related knowledge</h3>
                <div className="list">
                  {related.related_documents.map((r) => (
                    <div key={r.document_id} className="item" onClick={() => map.documents[r.document_id] && setDoc(r.document_id)}>
                      <div style={{ fontSize: 12.5 }}>{r.title}</div>
                      <div className="faint" style={{ fontSize: 11 }}>{r.relations.join(", ")} · {fmt(r.weight, 2)}</div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        ) : edge ? (
          <div>
            <div className="faint" style={{ fontSize: 12 }}>Explain this connection</div>
            <h2 style={{ fontSize: 15 }}>{map.documents[edge.source].title} ↔ {map.documents[edge.target].title}</h2>
            <p className="muted">W = 0.55·semantic + 0.20·entity + 0.15·link + 0.10·context = <b>{fmt(edge.weight, 3)}</b></p>
            {(["semantic", "entity", "link", "context"] as const).map((k) => (
              <div className="metric" key={k}>
                <span style={{ textTransform: "capitalize" }}>{k}</span>
                <span className="bar"><span style={{ width: `${edge.signals[k] * 100}%`, background: "#7dd3fc" }} /></span>
                <span className="mono">{fmt(edge.signals[k], 2)}</span>
              </div>
            ))}
            <p className="faint" style={{ fontSize: 12 }}>Raw cosine similarity: {fmt(edge.signals.cosine, 3)}. Semantic signal is relative to the corpus background similarity.</p>
          </div>
        ) : (
          <div>
            <h2>{d.label}</h2>
            <p className="muted">{d.description}</p>
            {d.metrics ? <MetricBars metrics={d.metrics} /> : <p className="muted">Metrics hidden (partial visibility).</p>}
            <hr className="sep" />
            <p className="faint" style={{ fontSize: 12 }}>Click a document to see its details and related knowledge, or an edge to see why two documents are connected. Markers on the outline show where dents (gaps) and jagged zones (conflicts) come from.</p>
            {map.external_links.length > 0 && (
              <>
                <h3 style={{ fontSize: 13 }}>Connections to other areas</h3>
                <div className="list">
                  {map.external_links.slice(0, 10).map((l, i) => (
                    <div key={i} className="item" style={{ cursor: "default" }}>
                      <div style={{ fontSize: 12.5 }}>{map.documents[l.from]?.title} → {l.title}</div>
                      <div className="faint" style={{ fontSize: 11 }}>weight {fmt(l.weight, 2)}</div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}
