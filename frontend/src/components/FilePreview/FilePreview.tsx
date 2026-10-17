import { useEffect, useState } from "react";
import { formatBytes } from "../../lib/format";
import { parseDelimited } from "../../lib/files";
import type { ProjectFile } from "../../types/ui";
import { CloseIcon } from "../icons/Icons";
import "./FilePreview.css";

const MAX_ROWS = 50;

interface FilePreviewProps {
  file: ProjectFile;
  onClose: () => void;
}

/** Right-side panel previewing one project file. */
export function FilePreview({ file, onClose }: FilePreviewProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside className="preview-panel" aria-label={`Preview of ${file.name}`}>
      <header className="preview-head">
        <div className="preview-title">
          <h2 className="preview-name" title={file.name}>
            {file.name}
          </h2>
          <p className="preview-meta">
            {formatBytes(file.size_bytes)}
            {file.summary ? ` · ${file.summary}` : ""}
          </p>
        </div>
        <button className="preview-close" type="button" aria-label="Close preview" onClick={onClose}>
          <CloseIcon />
        </button>
      </header>
      <div className="preview-body">
        <PreviewBody file={file} />
      </div>
    </aside>
  );
}

function PreviewBody({ file }: { file: ProjectFile }) {
  if (!file.url) return <Unavailable file={file} />;
  switch (file.kind) {
    case "image":
      return <img className="preview-image" src={file.url} alt={file.name} />;
    case "pdf":
      return <iframe className="preview-pdf" src={file.url} title={file.name} />;
    case "csv":
    case "tsv":
    case "text":
      return <TextPreview file={file} url={file.url} />;
    default:
      return <Unavailable file={file} />;
  }
}

type Loaded = { status: "loading" } | { status: "error"; message: string } | { status: "ok"; text: string };

function TextPreview({ file, url }: { file: ProjectFile; url: string }) {
  const [state, setState] = useState<Loaded>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.text();
      })
      .then((text) => !cancelled && setState({ status: "ok", text }))
      .catch((error: Error) => !cancelled && setState({ status: "error", message: error.message }));
    return () => {
      cancelled = true;
    };
  }, [url]);

  if (state.status === "loading") return <p className="preview-note">Loading preview…</p>;
  if (state.status === "error") return <p className="preview-note">Couldn't load this file ({state.message}).</p>;
  if (file.kind === "text") return <pre className="preview-text">{state.text}</pre>;

  const rows = parseDelimited(state.text, file.kind === "tsv" ? "\t" : ",").filter((r) => r.some((c) => c !== ""));
  const [header = [], ...body] = rows;
  const shown = body.slice(0, MAX_ROWS);
  return (
    <>
      <div className="preview-table-wrap">
        <table className="preview-table">
          <thead>
            <tr>
              {header.map((h, i) => (
                <th key={i} scope="col">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) => (
                  <td key={c}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="preview-note">
        {body.length > MAX_ROWS ? `Showing ${MAX_ROWS} of ${body.length} rows` : `${body.length} rows`}
      </p>
    </>
  );
}

function Unavailable({ file }: { file: ProjectFile }) {
  return (
    <div className="preview-unavailable">
      {file.summary && <p className="preview-summary">{file.summary}</p>}
      <p className="preview-note">
        {file.kind === "h5ad"
          ? "AnnData files can't be previewed in the browser. Ask SCRAP about this dataset in a chat."
          : "Preview isn't available for this file type."}
      </p>
    </div>
  );
}
