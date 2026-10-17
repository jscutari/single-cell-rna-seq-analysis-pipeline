import { VOLCANO_FILL, VOLCANO_POINTS } from "../Doodles/volcanoPoints";
import "./Charts.css";

interface VolcanoChartProps {
  /** Gene labels placed in the chart's 265×218 coordinate space. */
  labels: { x: number; y: number; text: string }[];
}

/** Differential expression volcano plot (−log10 p vs log2 fold change). */
export function VolcanoChart({ labels }: VolcanoChartProps) {
  return (
    <svg className="chart" viewBox="-6 0 278 226" role="img" aria-label="Volcano plot of differential expression">
      <g className="ink">
        <path d="M42 13V180H253 M42 180l-5-9m5 9 6-9 M253 180l-8-6m8 6-8 6" />
      </g>
      <path className="guide" d="M42 163H253 M108 30V180 M170 30V180" />
      {VOLCANO_POINTS.map(([cx, cy, r, group, opacity], i) => (
        <circle key={i} cx={cx} cy={cy} r={r * 1.15} fill={VOLCANO_FILL[group]} opacity={Math.min(1, opacity + 0.25)} />
      ))}
      {labels.map((l) => (
        <g key={l.text}>
          <circle cx={l.x} cy={l.y + 6} r={2.6} fill="none" stroke="#183763" strokeWidth={1} />
          <text className="label-strong" x={l.x + 5} y={l.y}>
            {l.text}
          </text>
        </g>
      ))}
      <text x={4} y={110} transform="rotate(-90 4 110)">−log₁₀ p</text>
      <text x={128} y={204}>log₂ FC</text>
    </svg>
  );
}
