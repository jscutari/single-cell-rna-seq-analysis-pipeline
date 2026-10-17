import { afterEach, describe, expect, it, vi } from "vitest";

// client.ts reads VITE_USE_MOCK at import time, so each test imports a fresh copy.
async function loadClient(useMock: "true" | "false") {
  vi.resetModules();
  vi.stubEnv("VITE_USE_MOCK", useMock);
  return import("./client");
}

function stubFetch(response: Response) {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("mock/real switch", () => {
  it("talks to the backend when VITE_USE_MOCK=false", async () => {
    const client = await loadClient("false");
    expect(client.USE_MOCK).toBe(false);
  });

  it("defaults to mock mode", async () => {
    vi.resetModules();
    const client = await import("./client");
    expect(client.USE_MOCK).toBe(true);
  });
});

describe("real backend requests", () => {
  it("sendMessage accepts a 204 No Content response", async () => {
    const { sendMessage } = await loadClient("false");
    const fetchMock = stubFetch(new Response(null, { status: 204 }));
    await expect(sendMessage("p1", "hello")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith("/api/projects/p1/messages", expect.objectContaining({ method: "POST" }));
  });

  it("GET requests send no JSON Content-Type header", async () => {
    const { listProjects } = await loadClient("false");
    const fetchMock = stubFetch(Response.json([]));
    await listProjects();
    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(headers.has("Content-Type")).toBe(false);
  });

  it("POST requests send JSON", async () => {
    const { sendMessage } = await loadClient("false");
    const fetchMock = stubFetch(new Response(null, { status: 204 }));
    await sendMessage("p1", "hello");
    const init = fetchMock.mock.calls[0][1]!;
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({ content: "hello" });
  });

  it("listMessages loads a project's chat history", async () => {
    const { listMessages } = await loadClient("false");
    const history = [{ id: "m1", project_id: "p1", role: "user", content: "hi", created_at: "2026-10-17T00:00:00Z" }];
    const fetchMock = stubFetch(Response.json(history));
    await expect(listMessages("p1")).resolves.toEqual(history);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/projects/p1/messages");
  });

  it("surfaces HTTP errors with the status code", async () => {
    const { listProjects } = await loadClient("false");
    stubFetch(new Response("boom", { status: 500 }));
    await expect(listProjects()).rejects.toThrow(/500/);
  });
});

describe("ids", () => {
  it("still creates ids where crypto.randomUUID is missing (plain-HTTP origins)", async () => {
    const { createProject } = await loadClient("true");
    const realCrypto = globalThis.crypto;
    vi.stubGlobal("crypto", { getRandomValues: (a: Uint8Array) => realCrypto.getRandomValues(a) });
    const project = await createProject("Project X");
    expect(project.id).toMatch(/^[0-9a-f]{32}$/);
  });
});
