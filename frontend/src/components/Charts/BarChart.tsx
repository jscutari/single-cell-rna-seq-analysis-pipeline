import "./Charts.css";

interface BarChartProps {
  bars: { label: string; value: number; group?: string }[];
  xLabel: string;
}

const WIDTH = 270;
const LABEL_W = 92;
const ROW = 30;
const GROUP_COLORS = ["#a4c7ed", "#e8adb1", "#c7d9a8", "#f2cf8f"];

/** Horizontal bars, e.g. pathway enrichment or per-donor scores coloured by condition. */
export function BarChart({ bars, xLabel }: BarChartProps) {
  const max = Math.max(...bars.map((b) => Math.abs(b.value)), 1e-9);
  const plotW = WIDTH - LABEL_W - 30;
  const groups = [...new Set(bars.map((b) => b.group).filter((g): g is string => !!g))];
  const legendH = groups.length ? 18 : 0;
  const height = bars.length * ROW + 34 + legendH;
  const color = (bar: BarChartProps["bars"][number], i: number) =>
    bar.group ? GROUP_COLORS[groups.indexOf(bar.group) % GROUP_COLORS.length] : i === 0 ? "#e8adb1" : "#a4c7ed";
  const decimals = max < 10 ? (max < 1 ? 2 : 1) : 0;

  return (
    <svg className="chart" viewBox={`0 0 ${WIDTH} ${height}`} role="img" aria-label={`Bar chart of ${xLabel}`}>
      {bars.map((bar, i) => {
        const y = 8 + i * ROW;
        const w = (Math.abs(bar.value) / max) * plotW;
        return (
          <g key={`${bar.label}-${i}`}>
            <text x={LABEL_W - 6} y={y + 14} textAnchor="end">
              {bar.label}
            </text>
            {/* slightly uneven edges read as hand-shaded */}
            <path
              d={`M${LABEL_W} ${y + 3} L${LABEL_W + w} ${y + 2} L${LABEL_W + w + 1} ${y + 19} L${LABEL_W} ${y + 20} Z`}
              fill={color(bar, i)}
              fillOpacity={0.8}
              stroke="#8898b0"
              strokeWidth={1}
              data-group={bar.group}
            />
            <text x={LABEL_W + w + 6} y={y + 15} className="label-strong">
              {bar.value.toFixed(decimals)}
            </text>
          </g>
        );
      })}
      <path className="ink" d={`M${LABEL_W} 4V${height - 26 - legendH}H${WIDTH - 10}`} />
      <text x={LABEL_W + plotW / 2} y={height - 8 - legendH} textAnchor="middle">
        {xLabel}
      </text>
      {groups.map((g, i) => (
        <g key={g} transform={`translate(${LABEL_W + i * 90} ${height - 6})`}>
          <rect x={0} y={-8} width={9} height={9} fill={GROUP_COLORS[i % GROUP_COLORS.length]} stroke="#8898b0" strokeWidth={0.8} />
          <text x={13} y={0}>
            {g}
          </text>
        </g>
      ))}
    </svg>
  );
}
