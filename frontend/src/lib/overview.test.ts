import { describe, expect, it } from "vitest";
import { datasetLine, reportSummary, toOverview } from "./overview";

const REPORT = `# Summary

In this dataset of **44,649** blood cells, CD14 monocytes show a stronger \`interferon\` response.

## Approved findings

### Interferon
...`;

describe("overview", () => {
  it("takes the first paragraph of the report, without Markdown", () => {
    expect(reportSummary(REPORT)).toBe("In this dataset of 44,649 blood cells, CD14 monocytes show a stronger interferon response.");
    expect(reportSummary("# Only a heading")).toBeNull();
    // The reporter sometimes writes the text right under its heading, with no blank line.
    expect(reportSummary("# Title\n\n## Summary\nAnalysis of 13 donors reveals a robust response.\n\n## Approved Findings\n..."))
      .toBe("Analysis of 13 donors reveals a robust response.");
    expect(reportSummary(null)).toBeNull();
    expect(reportSummary("Here is the final report:\n\n# Summary\n\nIFN is up in monocytes.")).toBe("IFN is up in monocytes.");
  });

  it("builds an overview from project_state.json", () => {
    const o = toOverview({
      brief: { goals: " Compare monocytes. ", organism: "human" },
      dataset: { n_cells: 44649, n_donors: 13, conditions: { "COVID-19": 28023, normal: 16626 } },
      report: REPORT,
    })!;
    expect(o.goal).toBe("Compare monocytes.");
    expect(datasetLine(o)).toBe("44,649 cells · 13 donors · COVID-19 vs normal · human");
    expect(o.summary).toMatch(/^In this dataset/);
  });

  it("is null when there is nothing to show", () => {
    expect(toOverview(null)).toBeNull();
    expect(toOverview({ brief: null, dataset: null, report: null })).toBeNull();
  });
});
