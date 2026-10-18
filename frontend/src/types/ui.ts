// Frontend-only view types. NOT part of the shared contract (shared/), so
// check:contract ignores this file.
//
// Pending contract (ask Alex): shared/ has no Chat model and ChatMessage has no
// chat_id, so multiple chats per project live only in the UI for now. Once the
// contract has them, replace Chat with the shared model and route replies by chat_id.

import type { EventType, ScrapEvent } from "./events";
import type { ChatMessage, Finding } from "./schemas";

export interface Chat {
  id: string;
  project_id: string;
  title: string;
  created_at: string;
  /** Where the title came from: numbered by default, generated from the first message, or typed by the user. */
  title_source?: "default" | "auto" | "user";
}

/** What the main page is showing. */
export type View =
  | { kind: "home" }
  | { kind: "project"; projectId: string }
  | { kind: "chat"; projectId: string; chatId: string };

export type FileKind = "pdf" | "csv" | "tsv" | "image" | "text" | "notebook" | "h5ad" | "other";

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
  summary?: string | null;
  /** Path relative to the project folder (backend only). */
  path?: string;
}

/**
 * Chart data, as built by agents/results.py (data units). Mock volcano charts
 * omit `points` and use the sketch's own coordinates for labels.
 */
export type ChartSpec =
  | {
      type: "volcano";
      labels: { x: number; y: number; text: string }[];
      points?: [number, number][];
      threshold?: number;
      x_label?: string;
      y_label?: string;
    }
  | { type: "bar"; xLabel: string; bars: { label: string; value: number; group?: string }[] }
  | { type: "umap"; clusters: { label: string; color: string; points: [number, number][] }[] };

/** A key finding on the project page: the shared Finding plus chart data and file links. */
export interface FindingCard {
  finding: Finding;
  /** null when no result table backs the finding. */
  chart: ChartSpec | null;
  mock: boolean;
  hypothesis_title?: string | null;
  figure_url?: string | null;
  notebook_url?: string | null;
}

/** What a project is about, for the top of its page (from project_state.json). */
export interface ProjectOverview {
  goal: string | null;
  organism: string | null;
  n_cells: number | null;
  n_donors: number | null;
  /** Cells per condition label, e.g. {"COVID-19": 28023, "normal": 16626}. */
  conditions: Record<string, number> | null;
  /** The opening paragraph of the final report, when there is one. */
  summary: string | null;
}

export type RunStatus = "idle" | "running" | "done" | "stopped" | "failed";

/** A project's run, as tracked by the backend. */
export interface RunInfo {
  status: RunStatus;
  stage: string | null;
}

/** Backend-only stream events (not in shared/events.py). */
export type BackendEvent =
  | { id: string; type: "user_message"; project_id: string; payload: ChatMessage; created_at: string }
  | { id: string; type: "run_status"; project_id: string; payload: { status: RunStatus }; created_at: string };

export type StreamEvent = ScrapEvent | BackendEvent;

export const BACKEND_EVENT_TYPES = ["user_message", "run_status"] as const;
export type StreamEventType = EventType | (typeof BACKEND_EVENT_TYPES)[number];
