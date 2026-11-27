import { useState } from "react";
import { api } from "../api";
import type { SearchResult } from "../types";

const TOOLS = [
  ["search_knowledge", "Hybrid search; evidence chunks + sources + warnings within a token budget"],
  ["get_document_context", "Expand one hit with neighbouring chunks (cheaper than a full page)"],
  ["get_document", "Full page (truncated) — fallback"],
  ["get_related_knowledge", "Links, similar documents, duplicates, conflicts"],
  ["list_knowledge_domains / get_knowledge_area", "Narrow the search to one area"],
  ["check_knowledge_conflicts", "Suspected contradictions for a question"],
  ["get_knowledge_health / get_knowledge_gaps", "Quality profile and gaps of an area"],
  ["get_knowledge_changes / compare_knowledge_snapshots", "What changed"],
];

export default function AgentView() {
  const [q, setQ] = useState("How many times are failed card payments retried?");
  const [budget, setBudget] = useState(1200);
  const [res, setRes] = useState<SearchResult | null>(null);
  const run = async () => setRes(await api<SearchResult>("/api/v1/search", { method: "POST", body: JSON.stringify({ query: q, retrieval: { top_k: 5, max_tokens: budget } }) }));
  const config = {
    mcpServers: {
      "knowledge-topology": {
        command: "kt", args: ["mcp"],
        env: { KT_MCP_API_KEY: "<agent api key>", KT_DATA_DIR: "C:\\knowledge-topology\\backend\\data" },
      },
    },
  };
  return (
    <div className="page">
      <h1>Agent access (MCP)</h1>
      <p className="lead">Agents use the same services and permissions as people. The agent identity comes from the connection's API key — never from tool arguments.</p>
      <div className="grid2" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <div className="card">
          <h3>MCP configuration (stdio)</h3>
          <pre className="code">{JSON.stringify(config, null, 2)}</pre>
          <h3>Tools</h3>
          {TOOLS.map(([n, d]) => <div className="explain" key={n}><b className="mono">{n}</b><br />{d}</div>)}
        </div>
        <div className="card">
          <h3>Try what an agent receives</h3>
          <div className="row">
            <input value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1 }} />
            <input type="number" value={budget} onChange={(e) => setBudget(+e.target.value)} style={{ width: 90 }} title="token budget" />
            <button className="btn primary" onClick={run}>Search</button>
          </div>
          {res && (
            <>
              <p className="mono">{res.results.length} documents · {res.usage.returned_chunks} chunks · ~{res.usage.estimated_tokens}/{res.usage.budget_tokens} tokens · {res.usage.candidates} candidates</p>
              {res.warnings.map((w) => <div key={w.issue_id} className="quote" style={{ borderColor: "#7f1d1d" }}><span className={`sev ${w.severity}`}>{w.type}</span> {w.message}</div>)}
              {res.results.map((r) => (
                <div key={r.document_id} className="quote">
                  <b>{r.title}</b> <span className="faint">· {r.retrieval_reasons.join(", ")} · {r.score}</span>
                  {r.evidence.map((e) => <div key={e.chunk_id} className="muted" style={{ marginTop: 4, fontSize: 12 }}>{e.section && <span className="faint">{e.section}: </span>}{e.quote}</div>)}
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
