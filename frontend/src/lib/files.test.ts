import { describe, expect, it } from "vitest";
import { fileKind, parseDelimited } from "./files";

describe("fileKind", () => {
  it.each([
    ["paper.PDF", "pdf"],
    ["de.csv", "csv"],
    ["counts.tsv", "tsv"],
    ["umap.svg", "image"],
    ["plot.png", "image"],
    ["notes.md", "text"],
    ["processed.h5ad", "h5ad"],
    ["archive.zip", "other"],
    ["README", "other"],
  ])("%s -> %s", (name, kind) => {
    expect(fileKind(name)).toBe(kind);
  });
});

describe("parseDelimited", () => {
  it("parses rows, quoted commas, escaped quotes and CRLF", () => {
    const text = 'gene,note\r\nIFI27,"up, strongly"\r\nMX1,"say ""hi"""\r\n';
    expect(parseDelimited(text, ",")).toEqual([
      ["gene", "note"],
      ["IFI27", "up, strongly"],
      ["MX1", 'say "hi"'],
    ]);
  });

  it("parses TSV and a last line without a newline", () => {
    expect(parseDelimited("a\tb\n1\t2", "\t")).toEqual([
      ["a", "b"],
      ["1", "2"],
    ]);
  });
});
