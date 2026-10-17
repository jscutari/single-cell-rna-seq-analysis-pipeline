import { useEffect, type ReactNode } from "react";
import { formatBytes } from "../../lib/format";
import { parseDelimited } from "../../lib/files";
import { useFileText } from "../../lib/useFileText";
import type { ProjectFile } from "../../types/ui";
import { ChevronLeftIcon, CloseIcon } from "../icons/Icons";
import { NotebookPreview } from "./NotebookPreview";
import "./FilePreview.css";

const MAX_ROWS = 50;

interface PreviewFrameProps {
  label: string;
  title: string;
  meta?: string;
  onClose: () => void;
  /** Shows a back arrow (e.g. to return to the file list). */
  onBack?: () => void;
  children: ReactNode;
}

/** The right-side sheet: header with title, optional back arrow and close button; Escape closes it. */
export function PreviewFrame({ label, title, meta, onClose, onBack, children }: PreviewFrameProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside className="preview-panel" aria-label={label}>
      <header className="preview-head">
        {onBack && (
          <button className="preview-close preview-back" type="button" aria-label="Back to files" onClick={onBack}>
            <ChevronLeftIcon />
          </button>
        )}
        <div className="preview-title">
          <h2 className="preview-name" title={title}>
            {title}
          </h2>
          {meta && <p className="preview-meta">{meta}</p>}
        </div>
        <button className="preview-close" type="button" aria-label="Close preview" onClick={onClose}>
          <CloseIcon />
        </button>
      </header>
      <div className="preview-body">{children}</div>
    </aside>
  );
}

interface FilePreviewProps {
  file: ProjectFile;
  onClose: () => void;
  onBack?: () => void;
}

/** Right-side panel previewing one project file. */
export function FilePreview({ file, onClose, onBack }: FilePreviewProps) {
  return (
    <PreviewFrame
      label={`Preview of ${file.name}`}
      title={file.name}
      meta={`${formatBytes(file.size_bytes)}${file.summary ? ` · ${file.summary}` : ""}`}
      onClose={onClose}
      onBack={onBack}
    >
      <PreviewBody file={file} />
    </PreviewFrame>
  );
}

function PreviewBody({ file }: { file: ProjectFile }) {
  if (!file.url) return <Unavailable file={file} />;
  switch (file.kind) {
    case "image":
      return <img className="preview-image" src={file.url} alt={file.name} />;
    case "pdf":
      return <iframe className="preview-pdf" src={file.url} title={file.name} />;
    case "notebook":
      return <NotebookPreview url={file.url} />;
    case "csv":
    case "tsv":
    case "text":
      return <TextPreview file={file} url={file.url} />;
    default:
      return <Unavailable file={file} />;
  }
}

function TextPreview({ file, url }: { file: ProjectFile; url: string }) {
  const state = useFileText(url);

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
