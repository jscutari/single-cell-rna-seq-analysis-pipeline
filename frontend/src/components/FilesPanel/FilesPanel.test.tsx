import { describe, expect, it } from "vitest";
import { mockFilesFor, mockFindingsFor } from "../../data/mockWorkspace";
import { groupFiles } from "./FilesPanel";

describe("groupFiles", () => {
  it("puts every file in exactly one group, in reading order", () => {
    const files = mockFilesFor("p1");
    const groups = groupFiles(files, mockFindingsFor("p1"));
    const byGroup = Object.fromEntries(groups.map((g) => [g.title, g.rows.map((r) => r.name)]));
    expect(byGroup["Papers & reports"]).toEqual(["wilk_2020_covid_pbmc.pdf", "analysis_notes.txt", "report.md"]);
    // Figures are named by what they show (their summary), sorted so a finding's figures sit together.
    expect(byGroup["Figures"]).toEqual(["Figure: IFN-α score per donor", "UMAP coloured by cell type"]);
    expect(byGroup["Code"]).toEqual(["ifn_alpha_cd14_monocytes.ipynb"]);
    expect(byGroup["Tables"]).toEqual(["de_results.csv"]);
    expect(byGroup["Data"]).toEqual(["processed.h5ad"]);
    expect(byGroup["Charts"]).toHaveLength(3);
    const fileRows = groups.flatMap((g) => g.rows).filter((r) => r.item?.kind === "file");
    expect(fileRows).toHaveLength(files.length);
  });

  it("hides empty groups", () => {
    expect(groupFiles([], [])).toEqual([]);
  });
});
