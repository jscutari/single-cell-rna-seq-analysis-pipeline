import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ProjectFile } from "../../types/ui";
import { FilePreview } from "./FilePreview";

const file = (over: Partial<ProjectFile>): ProjectFile => ({
  id: "f1",
  project_id: "p1",
  name: "file",
  kind: "other",
  size_bytes: 2048,
  url: "/mock-files/x",
  added_at: "2026-10-17T00:00:00Z",
  ...over,
});

function stubFetch(body: string, status = 200) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status })));
}

async function show(f: ProjectFile, onClose = vi.fn()) {
  render(<FilePreview file={f} onClose={onClose} />);
  await act(async () => {});
  return onClose;
}

describe("FilePreview", () => {
  it("shows the name, size and summary", async () => {
    await show(file({ name: "de.csv", kind: "image", summary: "Pseudobulk DE" }));
    expect(screen.getByRole("heading", { name: "de.csv" })).toBeTruthy();
    expect(screen.getByText("2.0 KB · Pseudobulk DE")).toBeTruthy();
  });

  it("renders images and PDFs from their URL", async () => {
    await show(file({ name: "umap.svg", kind: "image", url: "/mock-files/umap.svg" }));
    expect(screen.getByRole("img", { name: "umap.svg" }).getAttribute("src")).toBe("/mock-files/umap.svg");
    await show(file({ id: "f2", name: "paper.pdf", kind: "pdf", url: "/mock-files/paper.pdf" }));
    expect(document.querySelector("iframe")!.getAttribute("src")).toBe("/mock-files/paper.pdf");
  });

  it("renders CSV as a table with a row count", async () => {
    stubFetch("gene,p_adj\nIFI27,2e-12\nISG15,4e-10\n");
    await show(file({ name: "de.csv", kind: "csv" }));
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["gene", "p_adj"]);
    expect(screen.getAllByRole("row")).toHaveLength(3);
    expect(screen.getByText("2 rows")).toBeTruthy();
  });

  it("caps long tables at 50 rows", async () => {
    stubFetch("n\n" + Array.from({ length: 80 }, (_, i) => i).join("\n"));
    await show(file({ name: "big.csv", kind: "csv" }));
    expect(screen.getAllByRole("row")).toHaveLength(51);
    expect(screen.getByText("Showing 50 of 80 rows")).toBeTruthy();
  });

  it("renders text files as plain text", async () => {
    stubFetch("line one\nline two");
    await show(file({ name: "notes.txt", kind: "text" }));
    expect(document.querySelector(".preview-text")!.textContent).toBe("line one\nline two");
  });

  it("explains when a file can't be loaded or previewed", async () => {
    stubFetch("nope", 404);
    await show(file({ name: "gone.txt", kind: "text" }));
    expect(screen.getByText(/Couldn't load this file \(HTTP 404\)/)).toBeTruthy();
    await show(file({ id: "f3", name: "processed.h5ad", kind: "h5ad", url: null, summary: "44,649 cells" }));
    expect(screen.getByText(/AnnData files can't be previewed/)).toBeTruthy();
    expect(screen.getByText("44,649 cells")).toBeTruthy();
  });

  it("closes with the close button and with Escape", async () => {
    const onClose = await show(file({ name: "a.svg", kind: "image" }));
    fireEvent.click(screen.getByLabelText("Close preview"));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
