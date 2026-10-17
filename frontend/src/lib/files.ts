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
