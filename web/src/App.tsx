import { useCallback, useEffect, useState } from "react";
import { ApiError, DEV_IDENTITIES, api, getApiKey, setApiKey } from "./api";
import type { Topology } from "./types";
import AgentView from "./views/AgentView";
import DomainMapView from "./views/DomainMapView";
import EvolutionView from "./views/EvolutionView";
import HealthView from "./views/HealthView";
import IssuesView from "./views/IssuesView";
import OverviewView from "./views/OverviewView";
import SearchView from "./views/SearchView";
import SourcesView from "./views/SourcesView";
import UniverseView from "./views/UniverseView";

type Route = { view: string; arg: string | null };

const parse = (): Route => {
  const [view, ...rest] = window.location.hash.replace(/^#\/?/, "").split("/");
  return { view: view || "overview", arg: rest.length ? decodeURIComponent(rest.join("/")) : null };
};

const NAV: [string, string][] = [
  ["overview", "Overview"], ["universe", "Universe"], ["health", "Health"], ["issues", "Issues"],
  ["evolution", "Evolution"], ["sources", "Sources"], ["agent", "Agent access"],
];

export default function App() {
  const [route, setRoute] = useState<Route>(parse);
  const [key, setKey] = useState(getApiKey());
  const [me, setMe] = useState<{ id: string; roles: string[]; groups: string[] } | null>(null);
  const [topology, setTopology] = useState<Topology | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = useCallback((view: string, arg?: string | null) => {
    window.location.hash = "/" + view + (arg ? "/" + encodeURIComponent(arg) : "");
  }, []);

  const load = useCallback(() => {
    setError(null);
    api<{ id: string; roles: string[]; groups: string[] }>("/api/v1/me").then(setMe).catch(() => setMe(null));
    api<Topology>("/api/v1/topology?include_documents=true")
      .then(setTopology)
      .catch((e: ApiError) => { setTopology(null); setError(e.status === 404 ? "No topology snapshot yet. Run `kt demo` or `kt sync` first." : `${e.message}${e.traceId ? ` (trace ${e.traceId})` : ""}`); });
  }, []);
  useEffect(load, [key, load]);

  const switchKey = (k: string) => { setApiKey(k); setKey(k); setSelected(null); };
  const openArea = (k: string) => go("area", k);
  const openIssue = (id: string) => go("issues", id);

  let body: JSX.Element;
  if (error) body = <div className="page"><h1>Knowledge Topology</h1><p className="error">{error}</p></div>;
  else if (!topology) body = <div className="empty">Loading topology…</div>;
  else switch (route.view) {
    case "universe": body = <UniverseView topology={topology} selected={selected ?? route.arg} onSelect={setSelected} onOpenMap={openArea} onOpenIssue={openIssue} />; break;
    case "area": body = route.arg ? <DomainMapView areaKey={route.arg} onOpenIssue={openIssue} onBack={() => go("universe", route.arg)} /> : <div />; break;
    case "health": body = <HealthView topology={topology} onOpenArea={openArea} />; break;
    case "issues": body = <IssuesView focusId={route.arg} onFocus={(id) => go("issues", id)} />; break;
    case "evolution": body = <EvolutionView />; break;
    case "sources": body = <SourcesView isAdmin={!!me?.roles.includes("admin")} onRebuilt={load} />; break;
    case "agent": body = <AgentView />; break;
    case "search": body = <SearchView query={route.arg ?? ""} onOpenArea={openArea} onOpenIssue={openIssue} />; break;
    default: body = <OverviewView topology={topology} onOpenArea={(k) => { setSelected(k); go("universe", k); }} onOpenIssue={openIssue} go={go} />;
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand"><img className="brand-mark" src="/favicon.svg" alt="" />KNOWLEDGE TOPOLOGY</div>
        <form className="search" onSubmit={(e) => { e.preventDefault(); if (q.trim()) go("search", q.trim()); }}>
          <input placeholder="Search knowledge, entities, documents…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
        </form>
        {topology && <span className="pill ok">Synced · {new Date(topology.created_at).toLocaleDateString()}</span>}
        <div className="identity">
          <span>Viewing as</span>
          <select value={DEV_IDENTITIES.some((d) => d.key === key) ? key : "custom"} aria-label="Identity"
                  onChange={(e) => e.target.value === "custom" ? switchKey(prompt("API key") || key) : switchKey(e.target.value)}>
            {DEV_IDENTITIES.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
            <option value="custom">Custom API key…</option>
          </select>
        </div>
      </header>
      <nav className="nav">
        <div className="section">Explore</div>
        {NAV.slice(0, 5).map(([v, l]) => (
          <button key={v} className={route.view === v || (v === "universe" && route.view === "area") ? "active" : ""} onClick={() => go(v)}>{l}</button>
        ))}
        <div className="section">Platform</div>
        {NAV.slice(5).map(([v, l]) => <button key={v} className={route.view === v ? "active" : ""} onClick={() => go(v)}>{l}</button>)}
        <div className="foot">{me ? <>{me.id}<br />{me.groups.join(", ") || "no groups"}</> : "not authenticated"}</div>
      </nav>
      <main className="main">{body}</main>
    </div>
  );
}
