import { formatBytes, formatP } from "../../lib/format";
import { relativeTime } from "../../lib/relativeTime";
import type { ProjectSummary } from "../../types/schemas";
import { datasetLine } from "../../lib/overview";
import { figureCaption, groupProjectFiles } from "../../lib/files";
import type { FindingCard, ProjectFile, ProjectOverview, RunInfo } from "../../types/ui";
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
  /** What the project is about; omitted until a brief or report exists. */
  overview?: ProjectOverview | null;
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
  overview,
}: ProjectViewProps) {
  const fileInput = useRef<HTMLInputElement>(null);
  // Key findings are the ones the critic approved; the rest are listed briefly below them.
  const keyFindings = findings.filter((c) => c.finding.critic_verdict === "approve" || c.mock);
  const otherFindings = findings.filter((c) => !keyFindings.includes(c));
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

      {overview && (
        <section className="project-section" aria-labelledby="overview-heading">
          <div className="project-section-head">
            <h2 id="overview-heading" className="project-section-title">
              Overview
            </h2>
          </div>
          <div className="overview-card">
            {overview.goal && (
              <p className="overview-row">
                <span className="overview-label">Question</span>
                <span className="overview-goal">{overview.goal}</span>
              </p>
            )}
            {datasetLine(overview) && (
              <p className="overview-row">
                <span className="overview-label">Data</span>
                <span>{datasetLine(overview)}</span>
              </p>
            )}
            {overview.summary && (
              <p className="overview-row">
                <span className="overview-label">Summary</span>
                <span>{overview.summary}</span>
              </p>
            )}
          </div>
        </section>
      )}

      <section className="project-section" aria-labelledby="findings-heading">
        <div className="project-section-head">
          <h2 id="findings-heading" className="project-section-title">
            Key findings
          </h2>
        </div>
        {keyFindings.length ? (
          <div className="finding-grid">
            {keyFindings.map(({ finding, chart, mock, hypothesis_title, figure_url, notebook_url }) => (
              <article key={finding.id} className="finding-card" aria-label={finding.claim}>
                {mock && <span className="finding-mock">sample data</span>}
                {chart ? (
                  <FindingChart chart={chart} />
                ) : figure_url ? (
                  <img className="finding-figure" src={figure_url} alt={`Figure for: ${finding.claim}`} />
                ) : (
                  <p className="finding-nochart">No chart for this finding</p>
                )}
                {hypothesis_title && (
                  <p className="finding-hypothesis" title={hypothesis_title}>
                    {hypothesis_title}
                  </p>
                )}
                <h3 className="finding-claim" title={finding.claim}>
                  {finding.claim}
                </h3>
                <ul className="finding-chips" aria-label="Statistics">
                  <li className="chip chip--test" title={finding.test}>
                    {finding.test}
                  </li>
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
          <p className="project-empty">
            {otherFindings.length
              ? "No hypothesis has been supported yet."
              : "No findings yet. They appear here as the analysis runs."}
          </p>
        )}
        {otherFindings.length > 0 && (
          <div className="also-tested">
            <h3 className="also-tested-title">Also tested, not supported</h3>
            <ul className="also-tested-list">
              {otherFindings.map(({ finding, hypothesis_title }) => (
                <li key={finding.id} title={finding.critic_notes || undefined}>
                  <span className={`chip chip--${finding.critic_verdict ?? "reject"}`}>
                    {finding.critic_verdict ? VERDICT_LABEL[finding.critic_verdict] : "Not reviewed"}
                  </span>
                  <span className="also-tested-claim">{hypothesis_title || finding.claim}</span>
                  {finding.p_adj !== null && <span className="also-tested-p">p_adj {formatP(finding.p_adj)}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

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
          groupProjectFiles(files).map((group) => (
            <div key={group.id} className="file-group" role="group" aria-label={group.title}>
              <h3 className="file-group-title">
                {group.title} <span className="file-group-count">{group.files.length}</span>
              </h3>
              {group.id === "figures" ? (
                <ul className="figure-grid">
                  {group.files.map((file) => {
                    const { caption, detail } = figureCaption(file);
                    return (
                      <li key={file.id}>
                        <button
                          type="button"
                          className={file.id === activeFileId ? "figure-tile figure-tile--active" : "figure-tile"}
                          aria-current={file.id === activeFileId ? "true" : undefined}
                          aria-label={`${caption} (${file.name})`}
                          title={caption}
                          onClick={() => onOpenFile?.(file)}
                        >
                          <span className="figure-thumb">
                            {file.url ? <img src={file.url} alt="" loading="lazy" /> : <FileIcon />}
                          </span>
                          <span className="figure-caption">{caption}</span>
                          {detail && <span className="figure-detail">{detail}</span>}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <ul className="file-list">
                  {group.files.map((file) => (
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
              )}
            </div>
          ))
        ) : (
          <p className="project-empty">Upload a dataset or paper to get started.</p>
        )}
      </section>
    </div>
  );
}
