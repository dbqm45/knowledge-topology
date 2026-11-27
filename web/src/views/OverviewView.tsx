import { useEffect, useState } from "react";
import { api } from "../api";
import ShapeSvg from "../components/ShapeSvg";
import type { Change, Issue, Snapshot, Topology } from "../types";
import { SHAPE_LABEL, fmt } from "../util";

export default function OverviewView({ topology, onOpenArea, onOpenIssue, go }: {
  topology: Topology; onOpenArea: (k: string) => void; onOpenIssue: (id: string) => void; go: (v: string) => void;
}) {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [changes, setChanges] = useState<Change[] | null>(null);
  useEffect(() => {
    api<Issue[]>("/api/v1/issues?status=open").then(setIssues).catch(() => setIssues([]));
    api<Snapshot[]>("/api/v1/snapshots?limit=2").then((s) => {
      if (s.length > 1) api<{ changes: Change[] }>(`/api/v1/evolution/compare?from_snapshot_id=${s[1].snapshot_id}&to_snapshot_id=${s[0].snapshot_id}`)
        .then((c) => setChanges(c.changes)).catch(() => setChanges([]));
      else setChanges([]);
    }).catch(() => setChanges([]));
  }, [topology.snapshot_id]);
  const measured = topology.nodes.filter((n) => n.health !== null);
  const avg = measured.length ? measured.reduce((s, n) => s + n.health! * n.document_count, 0) / measured.reduce((s, n) => s + n.document_count, 0) : null;
  const sev = (s: string) => issues.filter((i) => i.severity === s).length;
  return (
    <div className="page">
      <h1>Organisational knowledge at a glance</h1>
      <p className="lead">Snapshot {new Date(topology.created_at).toLocaleString()} · algorithm {topology.algorithm_version} · embeddings {topology.embedding_model}</p>
      <div className="kpis">
        <div className="kpi"><div className="v">{topology.summary.documents}</div><div className="l">documents you can see</div></div>
        <div className="kpi"><div className="v">{topology.summary.areas}</div><div className="l">knowledge areas · {topology.summary.unassigned} orphan docs</div></div>
        <div className="kpi"><div className="v">{fmt(avg)}</div><div className="l">health index (document-weighted)</div></div>
        <div className="kpi"><div className="v">{issues.length}</div><div className="l"><span className="sev high">{sev("high")} high</span> · <span className="sev medium">{sev("medium")} medium</span> · <span className="sev low">{sev("low")} low</span></div></div>
      </div>
      <div className="grid2">
        <div className="card">
          <h3>Knowledge areas <span className="faint">(sorted by health)</span></h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 10 }}>
            {[...topology.nodes].sort((a, b) => (a.health ?? 101) - (b.health ?? 101)).map((n) => (
              <div key={n.stable_key} className="item" style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 10, cursor: "pointer", background: "var(--bg)" }}
                   onClick={() => onOpenArea(n.stable_key)}>
                <div style={{ display: "flex", justifyContent: "center" }}><ShapeSvg geometry={n.geometry} size={110} /></div>
                <b style={{ fontSize: 13 }}>{n.label}</b>
                <div className="faint" style={{ fontSize: 11.5 }}>{SHAPE_LABEL[n.geometry.shape_class]} · {n.document_count} docs · {n.health === null ? "restricted" : `health ${Math.round(n.health)}`}</div>
              </div>
            ))}
          </div>
          <p style={{ marginTop: 12 }}><button className="btn" onClick={() => go("universe")}>Explore the Universe →</button></p>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card">
            <h3>Most important issues</h3>
            <div className="list">
              {issues.slice(0, 6).map((i) => (
                <div key={i.id} className="item" onClick={() => onOpenIssue(i.id)}>
                  <span className={`sev ${i.severity}`}>{i.severity}</span> <span className="faint" style={{ fontSize: 11 }}>{i.issue_type} · confidence {fmt(i.confidence, 2)}</span>
                  <div style={{ fontSize: 12.5 }}>{i.title}</div>
                </div>
              ))}
              {issues.length === 0 && <div className="muted">No open issues visible to you.</div>}
            </div>
          </div>
          <div className="card">
            <h3>Recent evolution</h3>
            {changes === null ? <div className="muted">…</div> : changes.length === 0 ? <div className="muted">Only one snapshot so far.</div> : (
              <div className="list">
                {changes.slice(0, 6).map((c, i) => (
                  <div key={i} className="explain"><b>{c.type.replace("_", " ")}</b> · {c.label}
                    {c.health?.from != null && c.health?.to != null && <span className="faint"> · health {fmt(c.health.from)} → {fmt(c.health.to)}</span>}
                  </div>
                ))}
                <button className="btn small" onClick={() => go("evolution")}>Open evolution →</button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
