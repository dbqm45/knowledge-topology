import { useEffect, useState } from "react";
import { api } from "../api";

interface Source { id: string; name: string; connector_type: string; status: string; last_synced_at: string | null; last_error: string | null; documents: number; config: Record<string, unknown> }

export default function SourcesView({ isAdmin, onRebuilt }: { isAdmin: boolean; onRebuilt: () => void }) {
  const [sources, setSources] = useState<Source[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const load = () => api<Source[]>("/api/v1/sources").then(setSources).catch((e) => setErr(e.message));
  useEffect(() => { if (isAdmin) load(); }, [isAdmin]);
  if (!isAdmin) return <div className="page"><h1>Sources</h1><p className="muted">Source administration requires the admin role.</p></div>;
  const sync = async (id: string, full: boolean) => {
    await api(`/api/v1/sources/${id}/sync?full=${full}`, { method: "POST" });
    setMsg("Sync started in the background — the topology is rebuilt automatically when content changed.");
    setTimeout(() => { load(); onRebuilt(); }, 2500);
  };
  const rebuild = async () => {
    setMsg("Rebuilding topology…");
    await api("/api/v1/topology/rebuild", { method: "POST" });
    setMsg("New snapshot built."); onRebuilt();
  };
  const add = async () => {
    try {
      await api("/api/v1/sources", { method: "POST", body: JSON.stringify({ connector_type: "filesystem", name: name || path, config: { path } }) });
      setMsg("Source added; first sync running."); setPath(""); setName(""); setTimeout(load, 2000);
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <div className="page">
      <h1>Sources</h1>
      <p className="lead">Connectors normalise any source into the same document model (structure, versions, ACL). Sync is incremental; a periodic reconciliation catches deletions missed by webhooks.</p>
      {err && <p className="error">{err}</p>}{msg && <p className="muted">{msg}</p>}
      <div className="card">
        <table className="matrix" style={{ borderSpacing: 0 }}>
          <thead><tr><th>Name</th><th>Connector</th><th>Documents</th><th>Status</th><th>Last sync</th><th /></tr></thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.id}>
                <td className="lbl">{s.name}<div className="faint mono" style={{ fontWeight: 400 }}>{String(s.config.path ?? s.config.base_url ?? "")}</div></td>
                <td className="lbl" style={{ fontWeight: 400 }}>{s.connector_type}</td>
                <td className="lbl" style={{ fontWeight: 400 }}>{s.documents}</td>
                <td className="lbl" style={{ fontWeight: 400 }}><span className={`pill ${s.status === "ok" ? "ok" : "warn"}`}>{s.status}</span>{s.last_error && <div className="error" style={{ fontSize: 11 }}>{s.last_error}</div>}</td>
                <td className="lbl" style={{ fontWeight: 400 }}>{s.last_synced_at ? new Date(s.last_synced_at).toLocaleString() : "—"}</td>
                <td className="lbl"><div className="row"><button className="btn small" onClick={() => sync(s.id, false)}>Sync</button><button className="btn small" onClick={() => sync(s.id, true)}>Full</button></div></td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row" style={{ marginTop: 12 }}><button className="btn" onClick={rebuild}>Rebuild topology now</button></div>
      </div>
      <div className="card" style={{ marginTop: 14 }}>
        <h3>Add a folder (Markdown / HTML)</h3>
        <div className="row">
          <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
          <input placeholder="Folder path on the server, e.g. C:\docs\wiki" value={path} onChange={(e) => setPath(e.target.value)} style={{ minWidth: 360 }} />
          <button className="btn primary" onClick={add} disabled={!path}>Add & sync</button>
        </div>
        <p className="faint" style={{ fontSize: 12 }}>Confluence Cloud sources are added with the CLI (credentials stay in environment variables): <span className="mono">kt source add confluence --name ENG --base-url https://your.atlassian.net --email bot@x --spaces ENG</span></p>
      </div>
    </div>
  );
}
