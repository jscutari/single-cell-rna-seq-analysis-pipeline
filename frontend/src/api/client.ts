// The only place the UI talks to the backend. Components call these functions,
// never fetch() directly. Flip USE_MOCK off once FastAPI (proxied at /api) is up.
import { mockProjects } from "../data/mockProjects";
import type { ProjectSummary } from "../types/schemas";

const USE_MOCK = true;

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
    const project = { id: crypto.randomUUID(), name, updated_at: new Date().toISOString() };
    mockStore = [project, ...mockStore];
    return project;
  }
  return request("/projects", { method: "POST", body: JSON.stringify({ name }) });
}

export async function sendMessage(projectId: string, text: string): Promise<void> {
  if (USE_MOCK) {
    console.info("[mock] sendMessage", projectId, text);
    return;
  }
  await request(`/projects/${projectId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content: text }),
  });
}
