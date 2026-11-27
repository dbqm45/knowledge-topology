import type { Geometry } from "../types";
import { SHAPE_COLOR } from "../util";

/** Small 2D rendering of an area's geometry (outline + islands + projected strands). */
export default function ShapeSvg({ geometry, size = 90, strands = true }: { geometry: Geometry; size?: number; strands?: boolean }) {
  const r = Math.max(geometry.radius * 1.9, ...geometry.islands.map((i) => Math.hypot(...i.center) + i.radius));
  const color = SHAPE_COLOR[geometry.shape_class];
  const path = (pts: [number, number][]) => "M" + pts.map(([x, y]) => `${x.toFixed(3)},${(-y).toFixed(3)}`).join("L") + "Z";
  return (
    <svg width={size} height={size} viewBox={`${-r} ${-r} ${2 * r} ${2 * r}`} aria-hidden>
      <path d={path(geometry.outline)} fill={color} fillOpacity={0.14} stroke={color} strokeOpacity={geometry.boundary_opacity}
            strokeWidth={r * 0.025} />
      {geometry.islands.map((is, i) => (
        <circle key={i} cx={is.center[0]} cy={-is.center[1]} r={is.radius} fill={color} fillOpacity={0.12} stroke={color}
                strokeWidth={r * 0.02} />
      ))}
      {strands && geometry.strands.map((s, i) => (
        <polyline key={i} points={s.map(([x, y]) => `${x},${-y}`).join(" ")} fill="none" stroke={color}
                  strokeOpacity={0.35} strokeWidth={r * 0.008} />
      ))}
    </svg>
  );
}
