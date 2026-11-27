import type { Metric, MetricName } from "../types";
import { METRICS } from "../types";
import { METRIC_HELP, scoreColor } from "../util";

export default function MetricBars({ metrics, onPick }: { metrics: Record<MetricName, Metric>; onPick?: (m: MetricName) => void }) {
  return (
    <div>
      {METRICS.map((m) => {
        const v = metrics[m];
        if (!v) return null;
        return (
          <div className="metric" key={m} title={`${METRIC_HELP[m]}\nconfidence ${v.confidence} · n=${v.sample_size}`}
               onClick={() => onPick?.(m)} style={{ cursor: onPick ? "pointer" : undefined }}>
            <span style={{ textTransform: "capitalize" }}>{m}{!v.measured && <span className="est"> est.</span>}</span>
            <span className="bar"><span style={{ width: `${v.score ?? 0}%`, background: scoreColor(v.score), opacity: 0.4 + 0.6 * v.confidence }} /></span>
            <span className="mono" style={{ textAlign: "right" }}>{v.score === null ? "—" : Math.round(v.score)}</span>
          </div>
        );
      })}
      <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>Bar opacity = confidence · “est.” = estimated, not measured</div>
    </div>
  );
}
