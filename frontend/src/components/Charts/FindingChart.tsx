import type { ChartSpec } from "../../types/ui";
import { BarChart } from "./BarChart";
import { ScatterChart } from "./ScatterChart";
import { VolcanoChart } from "./VolcanoChart";

/** Picks the chart for a finding's chart spec. */
export function FindingChart({ chart }: { chart: ChartSpec }) {
  switch (chart.type) {
    case "volcano":
      return <VolcanoChart labels={chart.labels} />;
    case "bar":
      return <BarChart bars={chart.bars} xLabel={chart.xLabel} />;
    case "umap":
      return <ScatterChart clusters={chart.clusters} />;
  }
}
