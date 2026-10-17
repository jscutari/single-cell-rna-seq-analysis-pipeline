import "./Charts.css";

interface BarChartProps {
  bars: { label: string; value: number }[];
  xLabel: string;
}

const WIDTH = 270;
const LABEL_W = 92;
const ROW = 30;

/** Horizontal bars, e.g. pathway enrichment scores. */
export function BarChart({ bars, xLabel }: BarChartProps) {
  const max = Math.max(...bars.map((b) => b.value), 1);
  const plotW = WIDTH - LABEL_W - 26;
  const height = bars.length * ROW + 34;
  return (
    <svg className="chart" viewBox={`0 0 ${WIDTH} ${height}`} role="img" aria-label={`Bar chart of ${xLabel}`}>
      {bars.map((bar, i) => {
        const y = 8 + i * ROW;
        const w = (bar.value / max) * plotW;
        return (
          <g key={bar.label}>
            <text x={LABEL_W - 6} y={y + 14} textAnchor="end">
              {bar.label}
            </text>
            {/* slightly uneven edges read as hand-shaded */}
            <path
              d={`M${LABEL_W} ${y + 3} L${LABEL_W + w} ${y + 2} L${LABEL_W + w + 1} ${y + 19} L${LABEL_W} ${y + 20} Z`}
              fill={i === 0 ? "#e8adb1" : "#a4c7ed"}
              fillOpacity={0.75}
              stroke="#8898b0"
              strokeWidth={1}
            />
            <text x={LABEL_W + w + 6} y={y + 15} className="label-strong">
              {bar.value.toFixed(1)}
            </text>
          </g>
        );
      })}
      <path className="ink" d={`M${LABEL_W} 4V${height - 26}H${WIDTH - 10}`} />
      <text x={LABEL_W + plotW / 2} y={height - 8} textAnchor="middle">
        {xLabel}
      </text>
    </svg>
  );
}
