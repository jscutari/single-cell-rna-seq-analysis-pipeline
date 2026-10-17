import "./Charts.css";

interface ScatterChartProps {
  clusters: { label: string; color: string; points: [number, number][] }[];
}

/** UMAP-style scatter of cells, coloured by cluster, in a 260×200 space. */
export function ScatterChart({ clusters }: ScatterChartProps) {
  return (
    <svg className="chart" viewBox="0 0 270 250" role="img" aria-label="UMAP of cell clusters">
      <path className="ink" d="M14 196V20 M14 196H250" />
      {clusters.map((c) =>
        c.points.map(([x, y], i) => <circle key={`${c.label}-${i}`} cx={x + 14} cy={y + 8} r={2.2} fill={c.color} opacity={0.85} />),
      )}
      <text x={210} y={212}>UMAP 1</text>
      <text x={6} y={64} transform="rotate(-90 6 64)">UMAP 2</text>
      {/* legend in a 2-column grid under the plot, clear of the points */}
      {clusters.map((c, i) => (
        <g key={c.label} transform={`translate(${22 + (i % 2) * 120} ${230 + Math.floor(i / 2) * 15})`}>
          <circle cx={0} cy={-3} r={3.5} fill={c.color} />
          <text x={7} y={0}>
            {c.label}
          </text>
        </g>
      ))}
    </svg>
  );
}
