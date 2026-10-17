import type { ChartSpec } from "../../types/ui";
import { BarChart } from "./BarChart";
import { ScatterChart } from "./ScatterChart";
import { VolcanoChart } from "./VolcanoChart";

/** Picks the chart for a finding's chart spec. */
export function FindingChart({ chart }: { chart: ChartSpec }) {
  switch (chart.type) {
    case "volcano":
      return (
        <VolcanoChart labels={chart.labels} points={chart.points} threshold={chart.threshold} xLabel={chart.x_label} yLabel={chart.y_label} />
      );
    case "bar":
      return <BarChart bars={chart.bars} xLabel={chart.xLabel} />;
    case "umap":
      return <ScatterChart clusters={chart.clusters} />;
  }
}
