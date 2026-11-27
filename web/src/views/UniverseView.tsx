import { useState } from "react";
import AreaPanel from "../components/AreaPanel";
import Graph2D from "../components/Graph2D";
import Universe3D from "../components/Universe3D";
import type { Topology } from "../types";
import { SHAPE_COLOR, SHAPE_LABEL } from "../util";

export default function UniverseView({ topology, selected, onSelect, onOpenMap, onOpenIssue }: {
  topology: Topology; selected: string | null; onSelect: (k: string | null) => void;
  onOpenMap: (k: string) => void; onOpenIssue: (id: string) => void;
}) {
  const [mode, setMode] = useState<"universe" | "graph">("universe");
  const [docs, setDocs] = useState(false);
  const node = topology.nodes.find((n) => n.stable_key === selected) ?? null;
  return (
    <div className="universe">
      <div className="stage">
        <div className="toolbar">
          <div className="seg" role="tablist">
            <button className={mode === "universe" ? "on" : ""} onClick={() => setMode("universe")}>Universe</button>
            <button className={mode === "graph" ? "on" : ""} onClick={() => setMode("graph")}>Graph</button>
          </div>
          {mode === "universe" && (
            <label className="muted" style={{ fontSize: 12 }}>
              <input type="checkbox" checked={docs} onChange={(e) => setDocs(e.target.checked)} /> documents
            </label>
          )}
          <span className="pill">{topology.privileged ? "privileged topology" : "filtered by your permissions"}</span>
        </div>
        {mode === "universe"
          ? <Universe3D topology={topology} selectedKey={selected} onSelect={onSelect} onOpen={onOpenMap} showDocuments={docs} />
          : <Graph2D topology={topology} selectedKey={selected} onSelect={onSelect} onOpen={onOpenMap} />}
        <div className="legend">
          {(["regular", "deformed", "tangled", "restricted"] as const).map((s) => (
            <span key={s}><i style={{ background: SHAPE_COLOR[s] }} />{SHAPE_LABEL[s]}</span>
          ))}
          <span className="faint">size = number of documents · shape = quality</span>
        </div>
      </div>
      <aside className="side">
        {node ? <AreaPanel node={node} onOpenMap={onOpenMap} onOpenIssue={onOpenIssue} /> : (
          <div>
            <h2>Knowledge Universe</h2>
            <p className="muted">Each area is a cluster of documents discovered automatically. Its <b>size</b> is the amount of knowledge; its <b>shape</b> is quality:</p>
            <div className="explain"><b style={{ color: SHAPE_COLOR.regular }}>Circle</b> — coherent, consistent, connected documentation.</div>
            <div className="explain"><b style={{ color: SHAPE_COLOR.deformed }}>Deformed</b> — dents for gaps and stale pages, jagged zones for conflicts, islands for disconnected parts.</div>
            <div className="explain"><b style={{ color: SHAPE_COLOR.tangled }}>Tangle</b> — duplicates, contradictions, unknown sources of truth.</div>
            <p className="muted">Select an area to see why it looks the way it does. Double-click to open its map.</p>
            <hr className="sep" />
            <div className="list">
              {[...topology.nodes].sort((a, b) => (a.health ?? 101) - (b.health ?? 101)).map((n) => (
                <div key={n.stable_key} className="item" onClick={() => onSelect(n.stable_key)}>
                  <span className={`badge ${n.geometry.shape_class}`}>{SHAPE_LABEL[n.geometry.shape_class]}</span>{" "}
                  <b style={{ fontSize: 13 }}>{n.label}</b>
                  <div className="faint" style={{ fontSize: 11.5 }}>{n.document_count} documents · {n.health === null ? "restricted" : `health ${Math.round(n.health)}`}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
