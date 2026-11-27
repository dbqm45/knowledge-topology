import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import type { DocInfo, Topology } from "../types";
import { SHAPE_COLOR, SHAPE_LABEL, fmt, shapeOf } from "../util";

interface Props {
  topology: Topology;
  selectedKey: string | null;
  onSelect: (key: string | null) => void;
  onOpen: (key: string) => void;
  showDocuments: boolean;
}

const FLAG_COLOR: Record<string, number> = {
  conflict: 0xfb7185, duplicate: 0xc084fc, stale: 0xfbbf24, isolated: 0x94a3b8, stub: 0x94a3b8, unassigned: 0x64748b,
};

/**
 * Knowledge Universe: each area is drawn from the geometry computed by the backend Geometry Engine.
 * Nothing here invents shape — outline, islands and strands come from metrics (see /docs/topology-algorithm.md).
 */
export default function Universe3D({ topology, selectedKey, onSelect, onOpen, showDocuments }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const selectRef = useRef(onSelect);
  const openRef = useRef(onOpen);
  const highlightRef = useRef<(key: string | null) => void>(() => undefined);
  selectRef.current = onSelect;
  openRef.current = onOpen;

  useEffect(() => {
    const mount = mountRef.current!;
    const width = mount.clientWidth, height = mount.clientHeight;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    mount.appendChild(renderer.domElement);
    const labels = new CSS2DRenderer();
    labels.setSize(width, height);
    labels.domElement.style.position = "absolute";
    labels.domElement.style.inset = "0";
    labels.domElement.style.pointerEvents = "none";
    mount.appendChild(labels.domElement);

    const scene = new THREE.Scene();
    const nodes = topology.nodes.filter((n) => n.position);
    const xs = nodes.map((n) => n.position![0]), ys = nodes.map((n) => n.position![1]);
    const cx = xs.length ? (Math.min(...xs) + Math.max(...xs)) / 2 : 0;
    const cy = ys.length ? (Math.min(...ys) + Math.max(...ys)) / 2 : 0;
    const span = Math.max(6, ...nodes.map((n) => Math.hypot(n.position![0] - cx, n.position![1] - cy) + n.geometry.radius * 1.6));
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 500);
    camera.position.set(cx, cy - span * 1.35, span * 1.85);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(cx, cy - span * 0.12, 0);
    controls.enableDamping = true;
    controls.maxDistance = span * 6;
    controls.minDistance = 2;
    controls.update();

    // Subtle reference grid = "landscape" floor.
    const grid = new THREE.PolarGridHelper(span * 1.4, 12, 8, 96, 0x1b2638, 0x141c2b);
    grid.rotation.x = Math.PI / 2;
    grid.position.set(cx, cy, -0.02);
    scene.add(grid);

    const disposables: { dispose: () => void }[] = [];
    const track = <T extends { dispose: () => void }>(o: T) => (disposables.push(o), o);
    const pickables: THREE.Mesh[] = [];
    const groups = new Map<string, { group: THREE.Group; outline: THREE.LineBasicMaterial; fill: THREE.MeshBasicMaterial; strands: THREE.Group }>();

    const toShape = (pts: [number, number][]) => {
      const s = new THREE.Shape();
      pts.forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y)));
      s.closePath();
      return s;
    };

    for (const n of nodes) {
      const g = n.geometry;
      const color = new THREE.Color(SHAPE_COLOR[shapeOf(n)]);
      const group = new THREE.Group();
      group.position.set(n.position![0], n.position![1], 0);
      const grain = g.texture?.grain ?? 0.3;

      const fillMat = track(new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.16 - 0.07 * grain, side: THREE.DoubleSide, depthWrite: false }));
      const shapes = [toShape(g.outline), ...g.islands.map((is) => {
        const c = new THREE.Shape();
        c.absarc(is.center[0], is.center[1], is.radius, 0, Math.PI * 2, false);
        return c;
      })];
      const fill = new THREE.Mesh(track(new THREE.ShapeGeometry(shapes, 4)), fillMat);
      fill.userData.key = n.stable_key;
      pickables.push(fill);
      group.add(fill);

      const outlineMat = track(new THREE.LineBasicMaterial({ color, transparent: true, opacity: g.boundary_opacity }));
      const ring = (pts: [number, number][], scale = 1, z = 0) =>
        new THREE.LineLoop(track(new THREE.BufferGeometry().setFromPoints(pts.map(([x, y]) => new THREE.Vector3(x * scale, y * scale, z)))), outlineMat);
      group.add(ring(g.outline));
      const halo = new THREE.LineLoop(
        track(new THREE.BufferGeometry().setFromPoints(g.outline.map(([x, y]) => new THREE.Vector3(x * 1.05, y * 1.05, 0)))),
        track(new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.12 })));
      group.add(halo);
      for (const is of g.islands) {
        const pts: [number, number][] = Array.from({ length: 40 }, (_, i) => {
          const a = (i / 40) * Math.PI * 2;
          return [is.center[0] + is.radius * Math.cos(a), is.center[1] + is.radius * Math.sin(a)];
        });
        group.add(ring(pts));
      }

      const strands = new THREE.Group();
      const strandMat = track(new THREE.LineBasicMaterial({ color, transparent: true, opacity: shapeOf(n) === "tangled" ? 0.5 : 0.28 }));
      for (const s of g.strands) {
        strands.add(new THREE.Line(track(new THREE.BufferGeometry().setFromPoints(s.map(([x, y, z]) => new THREE.Vector3(x, y, Math.abs(z) + 0.05)))), strandMat));
      }
      strands.userData.speed = reduceMotion ? 0 : (g.chaos ?? 0) * 0.0025;
      group.add(strands);

      const el = document.createElement("div");
      el.className = "area-label";
      el.innerHTML = `${escapeHtml(n.label)}<small>${n.document_count} docs · ${n.health === null ? "restricted" : "health " + fmt(n.health)}</small>`;
      const label = new CSS2DObject(el);
      label.position.set(0, -g.radius * 1.25, 0);
      group.add(label);

      scene.add(group);
      groups.set(n.stable_key, { group, outline: outlineMat, fill: fillMat, strands });
    }

    // Cross-area dependencies.
    const byKey = new Map(nodes.map((n) => [n.stable_key, n]));
    for (const e of topology.edges) {
      const a = byKey.get(e.source), b = byKey.get(e.target);
      if (!a || !b) continue;
      const pa = new THREE.Vector3(a.position![0], a.position![1], 0), pb = new THREE.Vector3(b.position![0], b.position![1], 0);
      const mid = pa.clone().add(pb).multiplyScalar(0.5);
      mid.z = pa.distanceTo(pb) * 0.22;
      const curve = new THREE.QuadraticBezierCurve3(pa, mid, pb);
      const mat = track(new THREE.LineBasicMaterial({ color: 0x7dd3fc, transparent: true, opacity: 0.12 + 0.5 * (e.weight ?? 0.3) }));
      scene.add(new THREE.Line(track(new THREE.BufferGeometry().setFromPoints(curve.getPoints(32))), mat));
    }

    // Documents as particles (optional).
    if (showDocuments && topology.documents) {
      const docs = Object.entries(topology.documents) as [string, DocInfo][];
      const pos: number[] = [], col: number[] = [];
      for (const [, d] of docs) {
        if (!d.position) continue;
        pos.push(d.position[0], d.position[1], 0.04);
        const flag = d.flags.find((f) => FLAG_COLOR[f]);
        const c = new THREE.Color(flag ? FLAG_COLOR[flag] : 0xe2e8f0);
        col.push(c.r, c.g, c.b);
      }
      const geom = track(new THREE.BufferGeometry());
      geom.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
      geom.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
      scene.add(new THREE.Points(geom, track(new THREE.PointsMaterial({ size: 0.09, vertexColors: true, transparent: true, opacity: 0.9 }))));
    }

    highlightRef.current = (key) => {
      groups.forEach((v, k) => {
        const on = key === null || k === key;
        v.outline.opacity = on ? Math.min(1, (byKey.get(k)!.geometry.boundary_opacity) + (k === key ? 0.3 : 0)) : 0.18;
        v.fill.opacity = k === key ? 0.26 : on ? 0.13 : 0.05;
      });
    };
    highlightRef.current(selectedKey);

    // Interaction.
    const ray = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    let hovered: string | null = null;
    const pick = (ev: PointerEvent | MouseEvent) => {
      const r = renderer.domElement.getBoundingClientRect();
      mouse.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(mouse, camera);
      const hit = ray.intersectObjects(pickables)[0];
      return { key: (hit?.object.userData.key as string | undefined) ?? null, r };
    };
    const onMove = (ev: PointerEvent) => {
      const { key, r } = pick(ev);
      hovered = key;
      renderer.domElement.style.cursor = key ? "pointer" : "grab";
      const tip = tipRef.current!;
      if (!key) { tip.style.display = "none"; return; }
      const n = byKey.get(key)!;
      tip.style.display = "block";
      tip.style.left = ev.clientX - r.left + 14 + "px";
      tip.style.top = ev.clientY - r.top + 14 + "px";
      tip.innerHTML = `<b>${escapeHtml(n.label)}</b><br/><span style="color:${SHAPE_COLOR[shapeOf(n)]}">${SHAPE_LABEL[shapeOf(n)]}</span> · ${n.document_count} documents` +
        (n.health !== null ? ` · health ${fmt(n.health)}` : "") + `<br/><span class="faint">click: details · double-click: open map</span>`;
    };
    let downAt = 0;
    const onDown = () => (downAt = performance.now());
    const onClick = (ev: MouseEvent) => {
      if (performance.now() - downAt > 250) return; // it was a drag
      selectRef.current(pick(ev).key);
    };
    const onDbl = (ev: MouseEvent) => {
      const { key } = pick(ev);
      if (key) openRef.current(key);
    };
    const onLeave = () => { if (tipRef.current) tipRef.current.style.display = "none"; };
    renderer.domElement.addEventListener("pointermove", onMove);
    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("click", onClick);
    renderer.domElement.addEventListener("dblclick", onDbl);
    renderer.domElement.addEventListener("pointerleave", onLeave);

    const onResize = () => {
      const w = mount.clientWidth, h = mount.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
      labels.setSize(w, h);
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(mount);

    let frame = 0;
    const loop = () => {
      frame = requestAnimationFrame(loop);
      groups.forEach((v) => (v.strands.rotation.z += v.strands.userData.speed));
      controls.update();
      renderer.render(scene, camera);
      labels.render(scene, camera);
      void hovered;
    };
    loop();

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      controls.dispose();
      disposables.forEach((d) => d.dispose());
      renderer.dispose();
      mount.removeChild(renderer.domElement);
      mount.removeChild(labels.domElement);
    };
  }, [topology, showDocuments]);

  useEffect(() => highlightRef.current(selectedKey), [selectedKey]);

  return (
    <div ref={mountRef} style={{ position: "absolute", inset: 0 }} aria-label="3D map of knowledge areas" role="img">
      <div ref={tipRef} className="tooltip" style={{ display: "none" }} />
    </div>
  );
}

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
