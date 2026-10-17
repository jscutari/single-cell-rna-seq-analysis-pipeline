import { VOLCANO_FILL, VOLCANO_POINTS } from "../Doodles/volcanoPoints";
import "./Charts.css";

interface VolcanoChartProps {
  /** Gene labels: data units when `points` is given, else the sketch's 265×218 space. */
  labels: { x: number; y: number; text: string }[];
  /** [log2 fold change, −log10 adjusted p] per gene (from agents/results.py). */
  points?: [number, number][];
  /** −log10 of the significance cut-off (e.g. 1.301 for p_adj 0.05). */
  threshold?: number;
  xLabel?: string;
  yLabel?: string;
}

// Plot area inside the 265×218 coordinate space (matches the axes below).
const X0 = 42;
const X1 = 253;
const Y0 = 180;
const Y1 = 13;
const UP = "#e8adb1";
const DOWN = "#a4c7ed";
const NS = "#9ca9b9";

/** Differential expression volcano plot (−log10 p vs log2 fold change). */
export function VolcanoChart({ labels, points, threshold, xLabel = "log₂ FC", yLabel = "−log₁₀ p" }: VolcanoChartProps) {
  const real = points !== undefined;
  // Symmetric x range so 0 sits in the middle; y from 0 to the largest value.
  const xMax = real ? Math.max(1, ...points.map(([x]) => Math.abs(x)), ...labels.map((l) => Math.abs(l.x))) * 1.08 : 1;
  const yMax = real ? Math.max(threshold ?? 0, 1, ...points.map(([, y]) => y), ...labels.map((l) => l.y)) * 1.08 : 1;
  const sx = (x: number) => (real ? X0 + ((x + xMax) / (2 * xMax)) * (X1 - X0) : x);
  const sy = (y: number) => (real ? Y0 - (y / yMax) * (Y0 - Y1) : y);

  return (
    <svg className="chart" viewBox="-6 0 278 226" role="img" aria-label="Volcano plot of differential expression">
      <g className="ink">
        <path d="M42 13V180H253 M42 180l-5-9m5 9 6-9 M253 180l-8-6m8 6-8 6" />
      </g>
      {real ? (
        <>
          {threshold !== undefined && <path className="guide" d={`M${X0} ${sy(threshold)}H${X1}`} data-testid="threshold" />}
          <path className="guide" d={`M${sx(0)} ${Y1}V${Y0}`} />
          {points.map(([x, y], i) => {
            const significant = threshold === undefined || y >= threshold;
            const fill = !significant ? NS : x > 0 ? UP : DOWN;
            return <circle key={i} cx={sx(x)} cy={sy(y)} r={1.8} fill={fill} opacity={significant ? 0.9 : 0.55} />;
          })}
        </>
      ) : (
        <>
          <path className="guide" d="M42 163H253 M108 30V180 M170 30V180" />
          {VOLCANO_POINTS.map(([cx, cy, r, group, opacity], i) => (
            <circle key={i} cx={cx} cy={cy} r={r * 1.15} fill={VOLCANO_FILL[group]} opacity={Math.min(1, opacity + 0.25)} />
          ))}
        </>
      )}
      {labels.map((l) => (
        <g key={l.text}>
          <circle cx={sx(l.x)} cy={sy(l.y) + (real ? 0 : 6)} r={2.6} fill="none" stroke="#183763" strokeWidth={1} />
          <text className="label-strong" x={sx(l.x) + 5} y={sy(l.y) - (real ? 4 : 0)}>
            {l.text}
          </text>
        </g>
      ))}
      <text x={4} y={110} transform="rotate(-90 4 110)">
        {yLabel}
      </text>
      <text x={147} y={204} textAnchor="middle">
        {xLabel}
      </text>
    </svg>
  );
}
