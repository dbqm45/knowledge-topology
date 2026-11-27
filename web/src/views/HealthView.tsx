import { useState } from "react";
import type { AreaNode, MetricName, Topology } from "../types";
import { METRICS } from "../types";
import { METRIC_HELP, fmt, scoreColor } from "../util";

export default function HealthView({ topology, onOpenArea }: { topology: Topology; onOpenArea: (k: string) => void }) {
  const [cell, setCell] = useState<{ node: AreaNode; metric: MetricName } | null>(null);
  const rows = [...topology.nodes].sort((a, b) => (a.health ?? 101) - (b.health ?? 101));
  const m = cell?.node.metrics?.[cell.metric];
  return (
    <div className="page">
      <h1>Knowledge health</h1>
      <p className="lead">Eight independent dimensions per area — never one hidden score. Italic cells are <i>estimated</i> (heuristics or missing reference model), not measured. Click a cell for its evidence.</p>
      <div className="grid2" style={{ gridTemplateColumns: "1.7fr 1fr" }}>
        <div className="card" style={{ overflowX: "auto" }}>
          <table className="matrix">
            <thead><tr><th>Area</th>{METRICS.map((x) => <th key={x} title={METRIC_HELP[x]} style={{ textTransform: "capitalize" }}>{x}</th>)}<th>Health</th></tr></thead>
            <tbody>
              {rows.map((n) => (
                <tr key={n.stable_key}>
                  <td className="lbl"><a href="#" onClick={(e) => { e.preventDefault(); onOpenArea(n.stable_key); }}>{n.label}</a><div className="faint" style={{ fontSize: 11, fontWeight: 400 }}>{n.document_count} docs</div></td>
                  {METRICS.map((x) => {
                    const v = n.metrics?.[x];
                    return (
                      <td key={x} className={v && !v.measured ? "est" : ""} onClick={() => n.metrics && setCell({ node: n, metric: x })}
                          style={{ background: v ? scoreColor(v.score, 0.16) : "#1e293b", color: v ? scoreColor(v.score) : "#64748b",
                                   outline: cell?.node === n && cell.metric === x ? "1px solid #fff" : undefined }}>
                        {v ? fmt(v.score) : "—"}
                      </td>
                    );
                  })}
                  <td style={{ color: scoreColor(n.health), cursor: "default" }}>{fmt(n.health)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          {cell && m ? (
            <>
              <div className="faint" style={{ fontSize: 12 }}>{cell.node.label}</div>
              <h3 style={{ fontSize: 16, textTransform: "capitalize" }}>{cell.metric}: {fmt(m.score)}/100</h3>
              <p className="muted">{METRIC_HELP[cell.metric]}</p>
              <p className="mono">confidence {m.confidence} · sample size {m.sample_size} · {m.measured ? "measured" : "estimated"}</p>
              <h3>Signals</h3>
              <pre className="code">{JSON.stringify(m.signals, null, 2)}</pre>
            </>
          ) : <div className="muted">Select a cell to see the signals that produced the score.</div>}
        </div>
      </div>
    </div>
  );
}
