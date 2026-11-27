import { useEffect, useState } from "react";
import { api } from "../api";
import type { SearchResult } from "../types";
import { ago } from "../util";

export default function SearchView({ query, onOpenArea, onOpenIssue }: { query: string; onOpenArea: (k: string) => void; onOpenIssue: (id: string) => void }) {
  const [res, setRes] = useState<SearchResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setRes(null); setErr(null);
    if (query) api<SearchResult>("/api/v1/search", { method: "POST", body: JSON.stringify({ query, retrieval: { top_k: 10 } }) }).then(setRes).catch((e) => setErr(e.message));
  }, [query]);
  return (
    <div className="page">
      <h1>Search: “{query}”</h1>
      {err && <p className="error">{err}</p>}
      {!res ? <p className="muted">Searching…</p> : (
        <div className="grid2">
          <div className="list">
            {res.results.length === 0 && <div className="muted">Nothing relevant that you are allowed to see.</div>}
            {res.results.map((r) => (
              <div key={r.document_id} className="card">
                <div className="row"><b>{r.uri ? <a href={r.uri} target="_blank" rel="noreferrer">{r.title} ↗</a> : r.title}</b><span className="spacer" /><span className="mono faint">{r.score}</span></div>
                <div className="faint" style={{ fontSize: 11.5 }}>{r.retrieval_reasons.join(" · ")} · owner {r.owner ?? "—"} · updated {ago(r.updated_at)}</div>
                {r.evidence.map((e) => <div key={e.chunk_id} className="quote">{e.section && <div className="faint" style={{ fontSize: 11 }}>{e.section}</div>}{e.quote}</div>)}
              </div>
            ))}
          </div>
          <div className="list">
            {res.warnings.length > 0 && (
              <div className="card"><h3>Quality warnings</h3>
                {res.warnings.map((w) => <div key={w.issue_id} className="item" onClick={() => onOpenIssue(w.issue_id)}><span className={`sev ${w.severity}`}>{w.type}</span> {w.message}</div>)}
              </div>
            )}
            <div className="card"><h3>Areas</h3>
              {res.related_areas.map((a) => <div key={a.stable_key} className="item" onClick={() => onOpenArea(a.stable_key)}>{a.label ?? "(partially visible area)"}</div>)}
            </div>
            <div className="card"><h3>Entities</h3><div className="row">{res.related_entities.map((e) => <span key={e.id} className="pill">{e.name}</span>)}</div></div>
            <div className="card mono faint">{res.usage.returned_chunks} chunks · ~{res.usage.estimated_tokens} tokens</div>
          </div>
        </div>
      )}
    </div>
  );
}
