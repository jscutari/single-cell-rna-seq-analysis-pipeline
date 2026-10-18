// The only place the UI talks to the backend. Components call these functions,
// never fetch() directly.
//
// Backend routes (backend/, FastAPI) live under /api; Vite proxies /api in dev:
//   GET  /api/projects                         -> Project[]
//   POST /api/projects {name}                  -> Project
//   GET  /api/projects/{id}/state              -> messages, run, live views, results, last_event_id
//   POST /api/projects/{id}/start | /stop      -> {status}
//   POST /api/projects/{id}/messages {content, id} -> 204 (reply arrives as a chat_reply event)
//   GET  /api/projects/{id}/files | /findings  -> ProjectFile[] | FindingCard[] (from project_state.json)
//   GET  /api/projects/{id}/events?after=N     -> SSE stream of events
import { mockProjects } from "../data/mockProjects";
import { mockChatsFor, mockFilesFor, mockFindingsFor, mockOverviewFor } from "../data/mockWorkspace";
import { toOverview, type ResultsState } from "../lib/overview";
import { newId } from "../lib/ids";
import type { ChatMessage, ProjectSummary } from "../types/schemas";
import type { Chat, FindingCard, ProjectFile, RunInfo, RunStatus, ProjectOverview } from "../types/ui";
import { publishMockEvent } from "./mockEvents";

/** Mock data unless started with VITE_USE_MOCK=false. */
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";

/** An HTTP error with the backend's explanation (FastAPI's `detail`). */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`/api${path}`, { ...init, headers });
  // 204 / empty bodies are valid answers (e.g. POST /messages).
  const text = await res.text();
  if (!res.ok) throw new ApiError(errorMessage(text) ?? `${init.method ?? "GET"} ${path} failed: ${res.status}`, res.status);
  return (text ? JSON.parse(text) : undefined) as T;
}

function errorMessage(body: string): string | undefined {
  try {
    const detail = JSON.parse(body).detail;
    if (typeof detail === "string") return detail;
    if (typeof detail?.message === "string") return detail.message;
  } catch {
    // not JSON
  }
  return undefined;
}

let mockStore = [...mockProjects];

export async function listProjects(): Promise<ProjectSummary[]> {
  if (USE_MOCK) return mockStore;
  return request("/projects");
}

export async function createProject(name: string): Promise<ProjectSummary> {
  if (USE_MOCK) {
    const project = { id: newId(), name, created_at: new Date().toISOString() };
    mockStore = [project, ...mockStore];
    return project;
  }
  return request("/projects", { method: "POST", body: JSON.stringify({ name }) });
}

export async function listMessages(projectId: string): Promise<ChatMessage[]> {
  // In mock mode the conversation only lives in the UI's state.
  if (USE_MOCK) return [];
  return request(`/projects/${projectId}/messages`);
}

/** What /state returns (the parts the app uses). */
export interface ProjectState {
  run: RunInfo;
  last_event_id: number;
  messages: ChatMessage[];
}

export interface ProjectChats {
  chats: Chat[];
  messages: Record<string, ChatMessage[]>;
  run?: RunInfo;
  /** Stream from here so nothing between this snapshot and the stream is missed. */
  lastEventId?: number;
}

/**
 * A project's chats with their saved messages. The contract has no Chat model yet,
 * so with the real backend the project's whole conversation is one "Chat 1".
 */
export async function listChats(projectId: string): Promise<ProjectChats> {
  if (USE_MOCK) return mockChatsFor(projectId);
  const state = await request<ProjectState>(`/projects/${projectId}/state`);
  const chat = mainChat(projectId, state.messages[0]?.created_at);
  return { chats: [chat], messages: { [chat.id]: state.messages }, run: state.run, lastEventId: state.last_event_id };
}

/** The single conversation a project has with the real backend. */
export function mainChat(projectId: string, createdAt?: string): Chat {
  return { id: `${projectId}-chat-1`, project_id: projectId, title: "Chat 1", created_at: createdAt ?? new Date().toISOString() };
}

export async function listFiles(projectId: string): Promise<ProjectFile[]> {
  return USE_MOCK ? mockFilesFor(projectId) : request(`/projects/${projectId}/files`);
}

export async function listFindings(projectId: string): Promise<FindingCard[]> {
  return USE_MOCK ? mockFindingsFor(projectId) : request(`/projects/${projectId}/findings`);
}

/** What the project is: goal, data, and the report's summary (null until there is any). */
export async function getOverview(projectId: string): Promise<ProjectOverview | null> {
  if (USE_MOCK) return mockOverviewFor(projectId);
  const state = await request<{ results: ResultsState | null }>(`/projects/${projectId}/state`);
  return toOverview(state.results);
}

export async function startRun(projectId: string): Promise<RunStatus> {
  if (USE_MOCK) return "running";
  return (await request<{ status: RunStatus }>(`/projects/${projectId}/start`, { method: "POST" })).status;
}

export async function stopRun(projectId: string): Promise<RunStatus> {
  if (USE_MOCK) return "stopped";
  return (await request<{ status: RunStatus }>(`/projects/${projectId}/stop`, { method: "POST" })).status;
}

const MOCK_REPLY = "Trademarked 2026  Jiggle by Kerry";
const MOCK_REPLY_DELAY_MS = 600;

/**
 * Sends a user message. The backend saves it and hands it to the orchestrator
 * (handle_user_message); the assistant's answer arrives later as a chat_reply event.
 */
export async function sendMessage(projectId: string, text: string, messageId?: string): Promise<void> {
  if (USE_MOCK) {
    setTimeout(() => {
      publishMockEvent({
        id: newId(),
        type: "chat_reply",
        project_id: projectId,
        created_at: new Date().toISOString(),
        payload: {
          id: newId(),
          project_id: projectId,
          role: "assistant",
          content: MOCK_REPLY,
          created_at: new Date().toISOString(),
        },
      });
    }, MOCK_REPLY_DELAY_MS);
    return;
  }
  await request(`/projects/${projectId}/messages`, {
    method: "POST",
    // The id makes a retry safe and lets the backend keep the same id we show.
    body: JSON.stringify(messageId ? { content: text, id: messageId } : { content: text }),
  });
}
