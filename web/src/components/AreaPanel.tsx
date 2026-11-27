import { useEffect, useState } from "react";
import { api } from "../api";
import type { AreaNode, Issue } from "../types";
import { SHAPE_LABEL, fmt, shapeOf } from "../util";
import MetricBars from "./MetricBars";

export default function AreaPanel({ node, onOpenMap, onOpenIssue }: {
  node: AreaNode; onOpenMap: (key: string) => void; onOpenIssue: (id: string) => void;
}) {
  const [issues, setIssues] = useState<Issue[]>([]);
  useEffect(() => {
    setIssues([]);
    if (node.visibility !== "full") return;
    api<Issue[]>(`/api/v1/issues?domain_id=${node.id}&status=open,investigating,accepted`).then(setIssues).catch(() => setIssues([]));
  }, [node.id, node.visibility]);
  const shape = shapeOf(node);
  return (
    <div>
      <div className="row">
        <span className={`badge ${shape}`}>{SHAPE_LABEL[shape]}</span>
        <span className="faint" style={{ fontSize: 12 }}>Knowledge area · {node.document_count} documents</span>
      </div>
      <h2>{node.label}</h2>
      <div className="muted" style={{ fontSize: 12.5 }}>{node.description}</div>
      {node.health !== null ? (
        <>
          <div className="health-big">{fmt(node.health)}<span className="faint" style={{ fontSize: 16 }}>/100</span></div>
          <div className="faint" style={{ fontSize: 11 }}>Composite health indicator — see dimensions below; clustering confidence {fmt(node.confidence, 2)}</div>
          <hr className="sep" />
          <MetricBars metrics={node.metrics!} />
        </>
      ) : (
        <p className="muted">You can see only part of this area, so its quality metrics and shape are hidden to avoid revealing documents you cannot access.</p>
      )}
      <hr className="sep" />
      <h3 style={{ fontSize: 13, margin: "0 0 6px" }}>Why does it look like this?</h3>
      {node.geometry.explanations.length === 0 && <div className="muted">Regular outline: no significant deformation signals.</div>}
      {node.geometry.explanations.slice(0, 8).map((e, i) => (
        <div className="explain" key={i}>
          <b>{e.feature.replace("_", " ")}</b>{e.metric ? <span className="faint"> · {e.metric}</span> : null}<br />{e.text}
          {e.issue_ids && e.issue_ids.length > 0 && (
            <div><a href="#" onClick={(ev) => { ev.preventDefault(); onOpenIssue(e.issue_ids![0]); }}>open issue →</a></div>
          )}
        </div>
      ))}
      {issues.length > 0 && (
        <>
          <hr className="sep" />
          <h3 style={{ fontSize: 13, margin: "0 0 6px" }}>Detected issues ({issues.length})</h3>
          <div className="list">
            {issues.slice(0, 8).map((i) => (
              <div className="item" key={i.id} onClick={() => onOpenIssue(i.id)}>
                <span className={`sev ${i.severity}`}>{i.severity}</span> <span className="faint" style={{ fontSize: 11 }}>{i.issue_type}</span>
                <div style={{ fontSize: 12.5 }}>{i.title}</div>
              </div>
            ))}
          </div>
        </>
      )}
      <hr className="sep" />
      <button className="btn primary" onClick={() => onOpenMap(node.stable_key)}>Explore knowledge area →</button>
      {node.lineage && node.lineage.relation !== "continued" && (
        <div className="faint" style={{ fontSize: 11, marginTop: 10 }}>Lineage: {node.lineage.relation.replace("_", " ")}</div>
      )}
    </div>
  );
}
