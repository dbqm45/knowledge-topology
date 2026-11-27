import { useEffect, useState } from "react";
import { api, qs } from "../api";
import type { Issue } from "../types";
import { ago, fmt } from "../util";

const STATUSES = ["open", "investigating", "accepted", "resolved", "dismissed"];

export default function IssuesView({ focusId, onFocus }: { focusId: string | null; onFocus: (id: string | null) => void }) {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [detail, setDetail] = useState<Issue | null>(null);
  const [status, setStatus] = useState("open,investigating,accepted");
  const [severity, setSeverity] = useState("");
  const [type, setType] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const load = () => api<Issue[]>("/api/v1/issues" + qs({ status, severity, issue_type: type })).then(setIssues).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [status, severity, type]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setDetail(null);
    if (focusId) api<Issue>(`/api/v1/issues/${focusId}`).then(setDetail).catch((e) => setErr(e.message));
  }, [focusId]);
  const patch = async (s: string) => {
    if (!detail) return;
    await api(`/api/v1/issues/${detail.id}`, { method: "PATCH", body: JSON.stringify({ status: s }) });
    setDetail(await api<Issue>(`/api/v1/issues/${detail.id}`));
    load();
  };
  const types = Array.from(new Set(issues.map((i) => i.issue_type))).sort();
  return (
    <div className="page">
      <h1>Issue explorer</h1>
      <p className="lead">Every issue carries evidence and a recommended action. The platform never edits documentation itself — owners decide.</p>
      {err && <p className="error">{err}</p>}
      <div className="filters">
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="status">
          <option value="open,investigating,accepted">Active</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          <option value="">all</option>
        </select>
        <select value={severity} onChange={(e) => setSeverity(e.target.value)} aria-label="severity">
          <option value="">any severity</option><option>high</option><option>medium</option><option>low</option>
        </select>
        <select value={type} onChange={(e) => setType(e.target.value)} aria-label="type">
          <option value="">any type</option>{types.map((t) => <option key={t}>{t}</option>)}
        </select>
        <span className="faint" style={{ alignSelf: "center" }}>{issues.length} issues</span>
      </div>
      <div className="issues">
        <div className="list">
          {issues.map((i) => (
            <div key={i.id} className={`item ${i.id === focusId ? "sel" : ""}`} onClick={() => onFocus(i.id)}>
              <div className="row">
                <span className={`sev ${i.severity}`}>{i.severity}</span>
                <span className="pill">{i.issue_type}</span>
                <span className="faint" style={{ fontSize: 11 }}>{i.metric} · confidence {fmt(i.confidence, 2)}</span>
                <span className="spacer" /><span className="faint" style={{ fontSize: 11 }}>{i.status}</span>
              </div>
              <div style={{ marginTop: 4 }}>{i.title}</div>
            </div>
          ))}
        </div>
        <div className="card" style={{ position: "sticky", top: 10, alignSelf: "start" }}>
          {detail ? (
            <>
              <div className="row"><span className={`sev ${detail.severity}`}>{detail.severity}</span><span className="pill">{detail.issue_type}</span><span className="pill">{detail.status}</span></div>
              <h3 style={{ fontSize: 15, marginTop: 8 }}>{detail.title}</h3>
              <p className="muted" style={{ whiteSpace: "pre-wrap" }}>{detail.description}</p>
              {detail.evidence.quotes && detail.evidence.quotes.length > 0 && (
                <>
                  <h3>Evidence</h3>
                  {detail.evidence.quotes.map((q, k) => {
                    const d = detail.documents?.find((x) => x.document_id === q.document_id);
                    return <div key={k} className="quote">“{q.quote}”<div className="faint" style={{ fontSize: 11, marginTop: 4 }}>{d?.title} · updated {ago(d?.updated_at)}</div></div>;
                  })}
                </>
              )}
              <h3>Documents</h3>
              <div className="list">
                {detail.documents?.map((d) => (
                  <div key={d.document_id} className="item" style={{ cursor: "default" }}>
                    {d.uri ? <a href={d.uri} target="_blank" rel="noreferrer">{d.title} ↗</a> : d.title}
                    <div className="faint" style={{ fontSize: 11 }}>owner {d.owner ?? "—"} · updated {ago(d.updated_at)}</div>
                  </div>
                ))}
              </div>
              <h3 style={{ marginTop: 12 }}>Recommended action</h3>
              <p>{detail.recommendation}</p>
              <div className="row">
                {STATUSES.filter((s) => s !== detail.status).map((s) => <button key={s} className="btn small" onClick={() => patch(s)}>{s}</button>)}
              </div>
              <p className="faint" style={{ fontSize: 11 }}>Status changes are audited. Confidence is about detection, not truth.</p>
            </>
          ) : <div className="muted">Select an issue.</div>}
        </div>
      </div>
    </div>
  );
}
