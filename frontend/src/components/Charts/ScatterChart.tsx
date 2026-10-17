import "./Charts.css";

interface ScatterChartProps {
  clusters: { label: string; color: string; points: [number, number][] }[];
}

// Plot area; points are rescaled into it whatever their units (0–1 from the backend).
const LEFT = 18;
const TOP = 10;
const W = 228;
const H = 184;

/** UMAP-style scatter of cells, coloured by cluster, with a legend underneath. */
export function ScatterChart({ clusters }: ScatterChartProps) {
  const all = clusters.flatMap((c) => c.points);
  const xs = all.map(([x]) => x);
  const ys = all.map(([, y]) => y);
  const [xMin, xMax] = [Math.min(...xs), Math.max(...xs)];
  const [yMin, yMax] = [Math.min(...ys), Math.max(...ys)];
  const sx = (x: number) => LEFT + (xMax > xMin ? (x - xMin) / (xMax - xMin) : 0.5) * W;
  // UMAP y grows upward; SVG y grows downward.
  const sy = (y: number) => TOP + (yMax > yMin ? 1 - (y - yMin) / (yMax - yMin) : 0.5) * H;
  const legendRows = Math.ceil(clusters.length / 2);
  const height = 226 + legendRows * 15;

  return (
    <svg className="chart" viewBox={`0 0 270 ${height}`} role="img" aria-label="UMAP of cell clusters">
      <path className="ink" d="M14 200V8 M14 200H252" />
      {clusters.map((c) =>
        c.points.map(([x, y], i) => <circle key={`${c.label}-${i}`} cx={sx(x)} cy={sy(y)} r={2.2} fill={c.color} opacity={0.85} />),
      )}
      <text x={210} y={214}>UMAP 1</text>
      <text x={6} y={64} transform="rotate(-90 6 64)">UMAP 2</text>
      {/* legend in a 2-column grid under the plot, clear of the points */}
      {clusters.map((c, i) => (
        <g key={c.label} transform={`translate(${22 + (i % 2) * 120} ${232 + Math.floor(i / 2) * 15})`}>
          <circle cx={0} cy={-3} r={3.5} fill={c.color} />
          <text x={7} y={0}>
            {c.label.length > 18 ? `${c.label.slice(0, 17).trimEnd()}…` : c.label}
          </text>
        </g>
      ))}
    </svg>
  );
}
