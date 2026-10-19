import type { FileKind } from "../types/ui";

const BY_EXTENSION: Record<string, FileKind> = {
  pdf: "pdf",
  csv: "csv",
  tsv: "tsv",
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  svg: "image",
  webp: "image",
  txt: "text",
  md: "text",
  json: "text",
  log: "text",
  py: "text",
  ipynb: "notebook",
  h5ad: "h5ad",
};

export function fileKind(name: string): FileKind {
  const ext = name.toLowerCase().split(".").pop() ?? "";
  return name.includes(".") ? (BY_EXTENSION[ext] ?? "other") : "other";
}

/**
 * Parses CSV/TSV text into rows. Handles quoted fields with commas, escaped
 * quotes ("") and newlines; enough for previewing analysis tables.
 */
export function parseDelimited(text: string, delimiter: "," | "\t"): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') {
        quoted = false;
      } else {
        field += c;
      }
    } else if (c === '"') {
      quoted = true;
    } else if (c === delimiter) {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += c;
    }
  }
  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

/** How a project's files are sorted for people: figures first, then reports, code, tables, data. */
export const FILE_GROUPS = [
  { id: "figures", title: "Figures" },
  { id: "reports", title: "Papers & reports" },
  { id: "code", title: "Code" },
  { id: "tables", title: "Tables" },
  { id: "data", title: "Data" },
] as const;
export type FileGroupId = (typeof FILE_GROUPS)[number]["id"];

export function fileGroup(file: { kind: FileKind; name: string }): FileGroupId {
  if (file.kind === "image") return "figures";
  if (file.kind === "pdf" || (file.kind === "text" && /\.(md|txt)$/i.test(file.name))) return "reports";
  if (file.kind === "notebook") return "code";
  if (file.kind === "csv" || file.kind === "tsv") return "tables";
  return "data";
}

/** A figure's caption from its summary: "Figure (cell 5): ISGs are up" -> caption "ISGs are up", detail "cell 5". */
export function figureCaption(file: { name: string; summary?: string | null }): { caption: string; detail?: string } {
  const m = file.summary?.match(/^Figure \(([^)]*)\):\s*(.+)$/);
  if (m) return { caption: m[2], detail: m[1] };
  return { caption: file.summary || file.name };
}

/** Files in their groups (empty groups dropped); figures of the same finding sit together. */
export function groupProjectFiles<F extends { kind: FileKind; name: string; summary?: string | null }>(files: F[]) {
  return FILE_GROUPS.map((g) => {
    const members = files.filter((f) => fileGroup(f) === g.id);
    if (g.id === "figures") members.sort((a, b) => figureCaption(a).caption.localeCompare(figureCaption(b).caption));
    return { ...g, files: members };
  }).filter((g) => g.files.length);
}
