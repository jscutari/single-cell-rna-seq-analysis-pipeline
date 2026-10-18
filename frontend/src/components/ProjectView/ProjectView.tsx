import { formatBytes, formatP } from "../../lib/format";
import { relativeTime } from "../../lib/relativeTime";
import type { ProjectSummary } from "../../types/schemas";
import type { FindingCard, ProjectFile, RunInfo } from "../../types/ui";
import { FindingChart } from "../Charts/FindingChart";
import { useRef } from "react";
import { FileIcon, PlusIcon, UploadIcon } from "../icons/Icons";
import "./ProjectView.css";

interface ProjectViewProps {
  project: ProjectSummary;
  files: ProjectFile[];
  findings: FindingCard[];
  activeFileId?: string | null;
  onOpenFile?: (file: ProjectFile) => void;
  onUpload?: (files: File[]) => void;
  /** The project's analysis run; omit to hide run controls. */
  run?: RunInfo;
  /** Why the last start/stop didn't work (from the backend). */
  runError?: string;
  onStartRun?: () => void;
  onStopRun?: () => void;
  onNewChat?: () => void;
}

const RUN_LABEL: Record<RunInfo["status"], string> = {
  idle: "Not started",
  running: "Running",
  done: "Finished",
  stopped: "Stopped",
  failed: "Failed",
};

const STAGE_LABEL: Record<string, string> = {
  preprocess: "preparing the data",
  intake: "agreeing the brief in chat",
  literature: "reading the literature",
  planning: "planning hypotheses",
  analysis: "testing hypotheses",
  report: "report written",
};

const KIND_LABEL: Record<ProjectFile["kind"], string> = {
  pdf: "PDF",
  csv: "CSV",
  tsv: "TSV",
  image: "Image",
  text: "Text",
  notebook: "Notebook",
  h5ad: "AnnData",
  other: "File",
};

const VERDICT_LABEL = { approve: "Critic approved", revise: "Critic: revise", reject: "Critic rejected" } as const;
const NOVELTY_LABEL = { known: "Known", partly_known: "Partly known", not_found_in_sources: "Not found in sources" } as const;

/** A project's page: its files and key findings. */
export function ProjectView({
  project,
  files,
  findings,
  activeFileId,
  onOpenFile,
  onUpload,
  onNewChat,
  run,
  runError,
  onStartRun,
  onStopRun,
}: ProjectViewProps) {
  const fileInput = useRef<HTMLInputElement>(null);
  return (
    <div className="project-page">
      <header className="project-page-header">
        <h1 className="project-page-title">{project.name}</h1>
        <p className="project-page-meta">
          Created {new Date(project.created_at).toLocaleDateString()} · {files.length} {files.length === 1 ? "file" : "files"} ·{" "}
          {findings.length} {findings.length === 1 ? "finding" : "findings"}
        </p>
      </header>

      {run && (
        <div className={`run-bar run-bar--${run.status}`} role="status" aria-label="Analysis run">
          <span className="run-dot" aria-hidden="true" />
          <span className="run-text">
            <strong>{RUN_LABEL[run.status]}</strong>
            {run.status === "running" && run.stage && ` · ${STAGE_LABEL[run.stage] ?? run.stage}`}
            {runError && <span className="run-error"> · {runError}</span>}
          </span>
          {run.status === "running" ? (
            <button type="button" className="run-button run-button--stop" onClick={onStopRun}>
              Stop run
            </button>
          ) : (
            <button type="button" className="run-button" onClick={onStartRun}>
              {run.status === "idle" ? "Start run" : "Start new run"}
            </button>
          )}
        </div>
      )}

      <section className="project-section" aria-labelledby="files-heading">
        <div className="project-section-head">
          <h2 id="files-heading" className="project-section-title">
            Files
          </h2>
          <div className="project-actions">
            {onNewChat && (
              <button className="upload-button upload-button--secondary" type="button" onClick={onNewChat}>
                <PlusIcon />
                <span>New chat</span>
              </button>
            )}
            {onUpload && (
              <>
                <button className="upload-button" type="button" onClick={() => fileInput.current?.click()}>
                  <UploadIcon />
                  <span>Upload file</span>
                </button>
                <input
                  ref={fileInput}
                  className="sr-only"
                  type="file"
                  multiple
                  aria-label="Upload files"
                  tabIndex={-1}
                  onChange={(e) => {
                    const picked = Array.from(e.target.files ?? []);
                    if (picked.length) onUpload(picked);
                    e.target.value = ""; // allow picking the same file again
                  }}
                />
              </>
            )}
          </div>
        </div>
        {files.length ? (
          <ul className="file-list">
            {files.map((file) => (
              <li key={file.id}>
                <button
                  type="button"
                  className={file.id === activeFileId ? "file-row file-row--active" : "file-row"}
                  aria-current={file.id === activeFileId ? "true" : undefined}
                  onClick={() => onOpenFile?.(file)}
                >
                  <span className={`file-icon file-icon--${file.kind}`}>
                    <FileIcon />
                  </span>
                  <span className="file-main">
                    <span className="file-name">{file.name}</span>
                    {file.summary && <span className="file-summary">{file.summary}</span>}
                  </span>
                  <span className="file-badge">{KIND_LABEL[file.kind]}</span>
                  <span className="file-size">{formatBytes(file.size_bytes)}</span>
                  <span className="file-time">{relativeTime(file.added_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="project-empty">Upload a dataset or paper to get started.</p>
        )}
      </section>

      <section className="project-section" aria-labelledby="findings-heading">
        <div className="project-section-head">
          <h2 id="findings-heading" className="project-section-title">
            Key findings
          </h2>
        </div>
        {findings.length ? (
          <div className="finding-grid">
            {findings.map(({ finding, chart, mock, hypothesis_title, figure_url, notebook_url }) => (
              <article key={finding.id} className="finding-card" aria-label={finding.claim}>
                {mock && <span className="finding-mock">sample data</span>}
                {chart ? (
                  <FindingChart chart={chart} />
                ) : figure_url ? (
                  <img className="finding-figure" src={figure_url} alt={`Figure for: ${finding.claim}`} />
                ) : (
                  <p className="finding-nochart">No chart for this finding</p>
                )}
                {hypothesis_title && <p className="finding-hypothesis">{hypothesis_title}</p>}
                <h3 className="finding-claim">{finding.claim}</h3>
                <ul className="finding-chips" aria-label="Statistics">
                  <li className="chip">{finding.test}</li>
                  {finding.p_adj !== null && <li className="chip">p_adj {formatP(finding.p_adj)}</li>}
                  {finding.effect_size !== null && <li className="chip">effect {finding.effect_size.toFixed(1)}</li>}
                  {finding.critic_verdict && (
                    <li className={`chip chip--${finding.critic_verdict}`}>{VERDICT_LABEL[finding.critic_verdict]}</li>
                  )}
                  {finding.novelty && <li className="chip chip--novelty">{NOVELTY_LABEL[finding.novelty]}</li>}
                </ul>
                {(notebook_url || (chart && figure_url)) && (
                  <p className="finding-links">
                    {chart && figure_url && (
                      <a href={figure_url} target="_blank" rel="noreferrer">
                        Figure
                      </a>
                    )}
                    {notebook_url && (
                      <a href={notebook_url} target="_blank" rel="noreferrer">
                        Notebook
                      </a>
                    )}
                  </p>
                )}
              </article>
            ))}
          </div>
        ) : (
          <p className="project-empty">No findings yet. They appear here as the analysis runs.</p>
        )}
      </section>
    </div>
  );
}
