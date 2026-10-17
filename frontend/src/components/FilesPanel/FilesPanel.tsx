import type { ReactNode } from "react";
import { formatP } from "../../lib/format";
import type { FindingCard, ProjectFile } from "../../types/ui";
import { FindingChart } from "../Charts/FindingChart";
import { FilePreview, PreviewFrame } from "../FilePreview/FilePreview";
import { ChartIcon, CodeIcon, FileIcon } from "../icons/Icons";
import "./FilesPanel.css";

/** What the panel shows: the list, one file, or one finding's chart. */
export type PanelItem = { kind: "file"; id: string } | { kind: "chart"; id: string } | null;

interface FilesPanelProps {
  projectName: string;
  files: ProjectFile[];
  findings: FindingCard[];
  selected: PanelItem;
  onSelect: (item: PanelItem) => void;
  onClose: () => void;
}

interface Group {
  title: string;
  icon: ReactNode;
  rows: { key: string; item: PanelItem; name: string; detail?: string; kind: string }[];
}

const isReport = (f: ProjectFile) => f.kind === "text" && /\.(md|txt)$/i.test(f.name);

/** Groups a project's outputs the way a biologist looks for them. */
export function groupFiles(files: ProjectFile[], findings: FindingCard[]): Group[] {
  const fileRow = (f: ProjectFile) => ({ key: f.id, item: { kind: "file" as const, id: f.id }, name: f.name, detail: f.summary, kind: f.kind });
  const groups: Group[] = [
    { title: "Papers & reports", icon: <FileIcon />, rows: files.filter((f) => f.kind === "pdf" || isReport(f)).map(fileRow) },
    {
      title: "Charts",
      icon: <ChartIcon />,
      rows: findings
        .filter((c) => c.chart)
        .map((c) => ({ key: `chart-${c.finding.id}`, item: { kind: "chart" as const, id: c.finding.id }, name: c.finding.claim, kind: c.chart.type })),
    },
    { title: "Figures", icon: <ChartIcon />, rows: files.filter((f) => f.kind === "image").map(fileRow) },
    { title: "Code", icon: <CodeIcon />, rows: files.filter((f) => f.kind === "notebook").map(fileRow) },
    { title: "Tables", icon: <FileIcon />, rows: files.filter((f) => f.kind === "csv" || f.kind === "tsv").map(fileRow) },
    {
      title: "Data",
      icon: <FileIcon />,
      rows: files.filter((f) => ["h5ad", "other"].includes(f.kind) || (f.kind === "text" && !isReport(f))).map(fileRow),
    },
  ];
  return groups.filter((g) => g.rows.length);
}

/** Right-side panel next to the chat: browse a project's papers, charts, figures and code. */
export function FilesPanel({ projectName, files, findings, selected, onSelect, onClose }: FilesPanelProps) {
  const back = () => onSelect(null);

  if (selected?.kind === "file") {
    const file = files.find((f) => f.id === selected.id);
    if (file) return <FilePreview file={file} onClose={onClose} onBack={back} />;
  }
  if (selected?.kind === "chart") {
    const card = findings.find((c) => c.finding.id === selected.id);
    if (card) {
      const f = card.finding;
      return (
        <PreviewFrame label={`Chart: ${f.claim}`} title={f.claim} meta={f.test} onClose={onClose} onBack={back}>
          <div className="panel-chart">
            <FindingChart chart={card.chart} />
          </div>
          <ul className="finding-chips" aria-label="Statistics">
            {f.p_adj !== null && <li className="chip">p_adj {formatP(f.p_adj)}</li>}
            {f.effect_size !== null && <li className="chip">effect {f.effect_size.toFixed(2)}</li>}
            {f.critic_verdict && <li className={`chip chip--${f.critic_verdict}`}>critic: {f.critic_verdict}</li>}
          </ul>
          {card.mock && <p className="preview-note">Sample data until the backend provides real charts.</p>}
        </PreviewFrame>
      );
    }
  }

  const groups = groupFiles(files, findings);
  return (
    <PreviewFrame label="Project files" title="Files" meta={projectName} onClose={onClose}>
      {groups.length ? (
        groups.map((group) => (
          <section key={group.title} className="panel-group" aria-label={group.title}>
            <h3 className="panel-group-title">
              {group.icon}
              <span>{group.title}</span>
              <span className="panel-group-count">{group.rows.length}</span>
            </h3>
            <ul className="panel-list">
              {group.rows.map((row) => (
                <li key={row.key}>
                  <button type="button" className="panel-row" onClick={() => onSelect(row.item)} title={row.name}>
                    <span className="panel-row-name">{row.name}</span>
                    {row.detail && <span className="panel-row-detail">{row.detail}</span>}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))
      ) : (
        <p className="preview-note">No files yet. Drop files into the chat or upload them on the project page.</p>
      )}
    </PreviewFrame>
  );
}
