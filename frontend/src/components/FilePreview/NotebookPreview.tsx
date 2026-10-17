import { useFileText } from "../../lib/useFileText";

/** The parts of the Jupyter .ipynb format (nbformat 4) we render. */
type Text = string | string[];
interface Output {
  output_type: "stream" | "display_data" | "execute_result" | "error";
  name?: string;
  text?: Text;
  data?: Record<string, Text>;
  ename?: string;
  evalue?: string;
  traceback?: string[];
}
interface Cell {
  cell_type: "code" | "markdown" | "raw";
  source: Text;
  execution_count?: number | null;
  outputs?: Output[];
}

const MAX_OUTPUT_CHARS = 4000;
const ANSI = /\x1b\[[0-9;]*m/g;

const join = (t: Text | undefined) => (Array.isArray(t) ? t.join("") : (t ?? ""));
const clip = (t: string) => (t.length > MAX_OUTPUT_CHARS ? `${t.slice(0, MAX_OUTPUT_CHARS)}\n… (output clipped)` : t);

/** Renders a notebook: each cell's code, then its printed output, plots and errors. */
export function NotebookPreview({ url }: { url: string }) {
  const state = useFileText(url);
  if (state.status === "loading") return <p className="preview-note">Loading notebook…</p>;
  if (state.status === "error") return <p className="preview-note">Couldn't load this notebook ({state.message}).</p>;

  let cells: Cell[];
  try {
    cells = (JSON.parse(state.text) as { cells?: Cell[] }).cells ?? [];
  } catch {
    return <p className="preview-note">This file isn't a valid notebook.</p>;
  }
  if (!cells.length) return <p className="preview-note">This notebook has no cells yet.</p>;

  return (
    <ol className="nb" aria-label="Notebook cells">
      {cells.map((cell, i) => (
        <li key={i} className={`nb-cell nb-cell--${cell.cell_type}`}>
          {cell.cell_type === "code" ? (
            <>
              <div className="nb-in">
                <span className="nb-prompt">In [{cell.execution_count ?? " "}]</span>
                <pre className="nb-code">{join(cell.source)}</pre>
              </div>
              {(cell.outputs ?? []).map((out, j) => (
                <OutputView key={j} output={out} />
              ))}
            </>
          ) : (
            <pre className="nb-markdown">{join(cell.source)}</pre>
          )}
        </li>
      ))}
    </ol>
  );
}

function OutputView({ output }: { output: Output }) {
  if (output.output_type === "stream") {
    const cls = output.name === "stderr" ? "nb-out nb-out--stderr" : "nb-out";
    return <pre className={cls}>{clip(join(output.text))}</pre>;
  }
  if (output.output_type === "error") {
    const trace = (output.traceback ?? []).join("\n").replace(ANSI, "");
    return <pre className="nb-out nb-out--error">{clip(trace || `${output.ename}: ${output.evalue}`)}</pre>;
  }
  const data = output.data ?? {};
  if (data["image/png"]) {
    return <img className="nb-image" alt="Cell output plot" src={`data:image/png;base64,${join(data["image/png"]).trim()}`} />;
  }
  if (data["text/plain"]) return <pre className="nb-out">{clip(join(data["text/plain"]))}</pre>;
  return null;
}
