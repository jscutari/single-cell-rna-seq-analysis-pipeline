import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BarChart } from "./BarChart";
import { FindingChart } from "./FindingChart";
import { ScatterChart } from "./ScatterChart";
import { VolcanoChart } from "./VolcanoChart";

const circles = (c: HTMLElement) => Array.from(c.querySelectorAll("circle"));

describe("VolcanoChart with backend data (data units)", () => {
  const points: [number, number][] = [
    [3, 6], // up, significant
    [-2, 4], // down, significant
    [0.5, 0.4], // not significant
  ];

  it("plots every point and label inside the axes, coloured by direction and significance", () => {
    const { container } = render(
      <VolcanoChart points={points} threshold={1.301} labels={[{ x: 3, y: 6, text: "IFI27" }]} xLabel="log2 FC" yLabel="-log10 p" />,
    );
    const dots = circles(container).filter((c) => c.getAttribute("r") === "1.8");
    expect(dots.map((d) => d.getAttribute("fill"))).toEqual(["#e8adb1", "#a4c7ed", "#9ca9b9"]);
    for (const d of dots) {
      const x = Number(d.getAttribute("cx"));
      const y = Number(d.getAttribute("cy"));
      expect(x).toBeGreaterThanOrEqual(42);
      expect(x).toBeLessThanOrEqual(253);
      expect(y).toBeGreaterThanOrEqual(13);
      expect(y).toBeLessThanOrEqual(180);
    }
    expect(container.querySelector('[data-testid="threshold"]')).toBeTruthy();
    expect(container.textContent).toContain("IFI27");
    expect(container.textContent).toContain("log2 FC");
  });

  it("keeps 0 log2FC in the middle", () => {
    const { container } = render(<VolcanoChart points={[[-4, 1], [4, 1]]} labels={[]} />);
    const xs = circles(container).map((c) => Number(c.getAttribute("cx")));
    expect((xs[0] + xs[1]) / 2).toBeCloseTo((42 + 253) / 2, 0);
  });

  it("falls back to the sketch data without points", () => {
    const { container } = render(<VolcanoChart labels={[{ x: 100, y: 50, text: "HLA" }]} />);
    expect(circles(container).length).toBeGreaterThan(200);
  });
});

describe("BarChart", () => {
  it("colours bars by group and shows a legend", () => {
    const { container } = render(
      <BarChart
        xLabel="score"
        bars={[
          { label: "H1", value: 0.8, group: "normal" },
          { label: "C1", value: 0.4, group: "COVID-19" },
          { label: "H2", value: 0.7, group: "normal" },
        ]}
      />,
    );
    const fills = Array.from(container.querySelectorAll("path[data-group]")).map((p) => [p.getAttribute("data-group"), p.getAttribute("fill")]);
    expect(fills).toEqual([["normal", "#a4c7ed"], ["COVID-19", "#e8adb1"], ["normal", "#a4c7ed"]]);
    expect(container.querySelectorAll("rect")).toHaveLength(2);
    expect(container.textContent).toContain("0.80");
  });

  it("handles negative values and no groups", () => {
    const { container } = render(<BarChart xLabel="x" bars={[{ label: "a", value: -2 }, { label: "b", value: 1 }]} />);
    expect(container.textContent).toContain("-2.0");
    expect(container.querySelectorAll("rect")).toHaveLength(0);
  });
});

describe("ScatterChart", () => {
  it("rescales 0-1 points into the plot and flips y so up is up", () => {
    const { container } = render(
      <ScatterChart clusters={[{ label: "T", color: "#9ca9b9", points: [[0, 0], [1, 1]] }]} />,
    );
    const [low, high] = circles(container).filter((c) => c.getAttribute("r") === "2.2");
    expect(Number(low.getAttribute("cx"))).toBeLessThan(Number(high.getAttribute("cx")));
    expect(Number(low.getAttribute("cy"))).toBeGreaterThan(Number(high.getAttribute("cy")));
  });

  it("truncates long legend labels and grows for many clusters", () => {
    const clusters = Array.from({ length: 12 }, (_, i) => ({
      label: i === 0 ? "A very long cell type name indeed" : `c${i}`,
      color: "#ccc",
      points: [[i, i]] as [number, number][],
    }));
    const { container } = render(<ScatterChart clusters={clusters} />);
    expect(container.textContent).toContain("A very long cell…");
    expect(container.querySelector("svg")!.getAttribute("viewBox")).toBe("0 0 270 316");
  });
});

it("FindingChart passes backend volcano fields through", () => {
  const { container } = render(
    <FindingChart chart={{ type: "volcano", points: [[1, 2]], threshold: 1.3, labels: [], x_label: "LFC (COVID vs normal)" }} />,
  );
  expect(container.textContent).toContain("LFC (COVID vs normal)");
});
