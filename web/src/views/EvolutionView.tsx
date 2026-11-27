import { useEffect, useState } from "react";
import { api } from "../api";
import ShapeSvg from "../components/ShapeSvg";
import type { Change, Snapshot, Topology } from "../types";
import { fmt } from "../util";

export default function EvolutionView() {
  const [snaps, setSnaps] = useState<Snapshot[]>([]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [changes, setChanges] = useState<Change[]>([]);
  const [tops, setTops] = useState<[Topology | null, Topology | null]>([null, null]);
  useEffect(() => {
    api<Snapshot[]>("/api/v1/snapshots").then((s) => {
      setSnaps(s);
      if (s.length > 1) { setFrom(s[1].snapshot_id); setTo(s[0].snapshot_id); }
      else if (s.length) { setFrom(s[0].snapshot_id); setTo(s[0].snapshot_id); }
    });
  }, []);
  useEffect(() => {
    if (!from || !to) return;
    api<{ changes: Change[] }>(`/api/v1/evolution/compare?from_snapshot_id=${from}&to_snapshot_id=${to}`).then((c) => setChanges(c.changes));
    Promise.all([api<Topology>(`/api/v1/topology?snapshot_id=${from}`), api<Topology>(`/api/v1/topology?snapshot_id=${to}`)]).then((t) => setTops(t));
  }, [from, to]);
  const label = (s: Snapshot) => new Date(s.created_at).toLocaleString();
  return (
    <div className="page">
      <h1>Knowledge evolution</h1>
      <p className="lead">Areas keep stable identities between snapshots (lineage), so you can see them appear, split, merge, degrade or recover.</p>
      <div className="row" style={{ marginBottom: 14 }}>
        <span className="muted">From</span>
        <select value={from} onChange={(e) => setFrom(e.target.value)}>{snaps.map((s) => <option key={s.snapshot_id} value={s.snapshot_id}>{label(s)}</option>)}</select>
        <span className="muted">to</span>
        <select value={to} onChange={(e) => setTo(e.target.value)}>{snaps.map((s) => <option key={s.snapshot_id} value={s.snapshot_id}>{label(s)}</option>)}</select>
      </div>
      <div className="grid2" style={{ gridTemplateColumns: "1fr 1fr" }}>
        {tops.map((t, k) => (
          <div className="card" key={k}>
            <h3>{k === 0 ? "Before" : "After"}</h3>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
              {t?.nodes.map((n) => (
                <div key={n.stable_key} style={{ width: 120, textAlign: "center" }}>
                  <ShapeSvg geometry={n.geometry} size={96} />
                  <div style={{ fontSize: 11.5 }}>{n.label}</div>
                  <div className="faint" style={{ fontSize: 11 }}>{n.document_count} docs · {fmt(n.health)}</div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="card" style={{ marginTop: 14 }}>
        <h3>Changes</h3>
        {changes.length === 0 && <div className="muted">No differences.</div>}
        {changes.map((c, i) => (
          <div className="explain" key={i}>
            <b>{c.type.replace("_", " ")}</b> — {c.label}
            {c.previous_label && c.previous_label !== c.label && <span className="faint"> (was “{c.previous_label}”)</span>}
            {c.document_delta ? <span className="faint"> · documents {c.document_delta > 0 ? "+" : ""}{c.document_delta}</span> : null}
            {c.health?.from != null && c.health?.to != null && <span className="faint"> · health {fmt(c.health.from)} → {fmt(c.health.to)}</span>}
            {c.metric_delta && Object.keys(c.metric_delta).length > 0 && (
              <div className="mono" style={{ marginTop: 3 }}>
                {Object.entries(c.metric_delta).map(([m, d]) => `${m} ${fmt(d.from)}→${fmt(d.to)}`).join(" · ")}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
