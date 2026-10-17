import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NotebookPreview } from "./NotebookPreview";

const NOTEBOOK = {
  nbformat: 4,
  cells: [
    { cell_type: "markdown", source: ["# Interferon\n"] },
    {
      cell_type: "code",
      execution_count: 1,
      source: ["df = donor_scores(adata, genes, 'donor_id', 'disease')\n", "print(df)"],
      outputs: [
        { output_type: "stream", name: "stdout", text: ["C1  0.61\n", "H1  0.34\n"] },
        { output_type: "display_data", data: { "image/png": "iVBORw0KGgo=", "text/plain": "<Figure>" } },
      ],
    },
    {
      cell_type: "code",
      execution_count: 2,
      source: "1 / 0",
      outputs: [{ output_type: "error", ename: "ZeroDivisionError", evalue: "division by zero", traceback: ["\u001b[0;31mZeroDivisionError\u001b[0m: division by zero"] }],
    },
  ],
};

afterEach(() => vi.restoreAllMocks());

function mockFetch(body: string, ok = true) {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok, status: ok ? 200 : 404, text: async () => body })));
}

describe("NotebookPreview", () => {
  it("shows each cell's code, printed output, plots and errors", async () => {
    mockFetch(JSON.stringify(NOTEBOOK));
    render(<NotebookPreview url="/nb.ipynb" />);
    expect(await screen.findByText(/donor_scores\(adata/)).toBeTruthy();
    expect(screen.getByText("In [1]")).toBeTruthy();
    expect(screen.getByText(/C1\s+0\.61/)).toBeTruthy();
    expect(screen.getByRole("img", { name: "Cell output plot" }).getAttribute("src")).toBe("data:image/png;base64,iVBORw0KGgo=");
    const error = screen.getByText(/ZeroDivisionError: division by zero/);
    expect(error.textContent).not.toContain("\u001b");
    expect(screen.getByText("# Interferon")).toBeTruthy();
  });

  it("explains bad or missing notebooks", async () => {
    mockFetch("not json");
    const { unmount } = render(<NotebookPreview url="/bad.ipynb" />);
    expect(await screen.findByText("This file isn't a valid notebook.")).toBeTruthy();
    unmount();
    mockFetch("", false);
    render(<NotebookPreview url="/missing.ipynb" />);
    expect(await screen.findByText(/Couldn't load this notebook \(HTTP 404\)/)).toBeTruthy();
  });
});
