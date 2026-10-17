// Frontend-only view types. NOT part of the shared contract (shared/), so
// check:contract ignores this file.
//
// Pending contract (ask Alex): shared/ has no Chat model and ChatMessage has no
// chat_id, so multiple chats per project live only in the UI for now. Once the
// contract has them, replace Chat with the shared model and route replies by chat_id.

import type { Finding } from "./schemas";

export interface Chat {
  id: string;
  project_id: string;
  title: string;
  created_at: string;
}

/** What the main page is showing. */
export type View =
  | { kind: "home" }
  | { kind: "project"; projectId: string }
  | { kind: "chat"; projectId: string; chatId: string };

export type FileKind = "pdf" | "csv" | "tsv" | "image" | "text" | "h5ad" | "other";

/** A file in a project (dataset, paper, table, figure). Shown on the project page. */
export interface ProjectFile {
  id: string;
  project_id: string;
  name: string;
  kind: FileKind;
  size_bytes: number;
  /** Where to fetch it for preview; null when it can't be previewed in the browser. */
  url: string | null;
  added_at: string;
  /** One-line description, e.g. "44,649 cells · 13 donors". */
  summary?: string;
}

export type ChartSpec =
  | { type: "volcano"; labels: { x: number; y: number; text: string }[] }
  | { type: "bar"; xLabel: string; bars: { label: string; value: number }[] }
  | { type: "umap"; clusters: { label: string; color: string; points: [number, number][] }[] };

/** A key finding on the project page: the shared Finding plus chart data (mock for now). */
export interface FindingCard {
  finding: Finding;
  chart: ChartSpec;
  mock: boolean;
}
