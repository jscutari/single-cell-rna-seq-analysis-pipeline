// The only place the UI talks to the backend. Components call these functions,
// never fetch() directly.
//
// Backend routes live under /api (Vite proxies /api to FastAPI in dev; FastAPI
// serves the built app in production):
//   GET  /api/projects                   -> Project[]
//   POST /api/projects {name}            -> Project
//   GET  /api/projects/{id}/messages     -> ChatMessage[]
//   POST /api/projects/{id}/messages {content} -> 204 (reply arrives as a chat_reply event)
//   GET  /api/projects/{id}/events       -> SSE stream of shared Event JSON
import { mockProjects } from "../data/mockProjects";
import { mockChatsFor, mockFilesFor, mockFindingsFor } from "../data/mockWorkspace";
import { newId } from "../lib/ids";
import type { ChatMessage, ProjectSummary } from "../types/schemas";
import type { Chat, FindingCard, ProjectFile } from "../types/ui";
import { publishMockEvent } from "./mockEvents";

/** Mock data unless started with VITE_USE_MOCK=false. */
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`/api${path}`, { ...init, headers });
  if (!res.ok) throw new Error(`${init.method ?? "GET"} ${path} failed: ${res.status}`);
  // 204 / empty bodies are valid answers (e.g. POST /messages).
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
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

/**
 * A project's chats with their saved messages. The contract has no Chat model yet,
 * so with the real backend the project's whole history is shown as one "Chat 1".
 */
export async function listChats(projectId: string): Promise<{ chats: Chat[]; messages: Record<string, ChatMessage[]> }> {
  if (USE_MOCK) return mockChatsFor(projectId);
  const history = await listMessages(projectId);
  const chat: Chat = { id: `${projectId}-chat-1`, project_id: projectId, title: "Chat 1", created_at: history[0]?.created_at ?? new Date().toISOString() };
  return { chats: [chat], messages: { [chat.id]: history } };
}

// No backend endpoints are agreed for files and findings yet, so the real-backend
// mode shows none; mock mode shows sample data.
export async function listFiles(projectId: string): Promise<ProjectFile[]> {
  return USE_MOCK ? mockFilesFor(projectId) : [];
}

export async function listFindings(projectId: string): Promise<FindingCard[]> {
  return USE_MOCK ? mockFindingsFor(projectId) : [];
}

const MOCK_REPLY = "Trademarked 2026  Jiggle by Kerry";
const MOCK_REPLY_DELAY_MS = 600;

/**
 * Sends a user message. The backend saves it and hands it to the orchestrator
 * (handle_user_message); the assistant's answer arrives later as a chat_reply event.
 */
export async function sendMessage(projectId: string, text: string): Promise<void> {
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
    body: JSON.stringify({ content: text }),
  });
}
