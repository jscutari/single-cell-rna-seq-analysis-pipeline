// The only place the UI talks to the backend. Components call these functions,
// never fetch() directly. Flip USE_MOCK off once FastAPI (proxied at /api) is up.
import { mockProjects } from "../data/mockProjects";
import type { ProjectSummary } from "../types/schemas";
import { publishMockEvent } from "./mockEvents";

export const USE_MOCK = true;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) throw new Error(`${init?.method ?? "GET"} ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
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

/** Hex id in the same format as shared.schemas.new_id(). */
function newId(): string {
  return crypto.randomUUID().replaceAll("-", "");
}
