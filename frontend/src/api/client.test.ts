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

describe("backend routes (real mode)", () => {
  it("listChats reads /state: one Chat 1 with the history, the run and the stream start point", async () => {
    const { listChats } = await loadClient("false");
    const messages = [{ id: "m1", project_id: "p1", role: "user", content: "hi", created_at: "2026-10-17T00:00:00Z" }];
    const fetchMock = stubFetch(Response.json({ run: { status: "running", stage: "intake" }, last_event_id: 42, messages }));
    const result = await listChats("p1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/projects/p1/state");
    expect(result.chats.map((c) => [c.id, c.title])).toEqual([["p1-chat-1", "Chat 1"]]);
    expect(result.messages["p1-chat-1"]).toEqual(messages);
    expect(result.run).toEqual({ status: "running", stage: "intake" });
    expect(result.lastEventId).toBe(42);
  });

  it("startRun and stopRun POST and return the status", async () => {
    const { startRun, stopRun } = await loadClient("false");
    let fetchMock = stubFetch(Response.json({ status: "running" }));
    await expect(startRun("p1")).resolves.toBe("running");
    expect(fetchMock).toHaveBeenCalledWith("/api/projects/p1/start", expect.objectContaining({ method: "POST" }));
    fetchMock = stubFetch(Response.json({ status: "stopped" }));
    await expect(stopRun("p1")).resolves.toBe("stopped");
    expect(fetchMock).toHaveBeenCalledWith("/api/projects/p1/stop", expect.objectContaining({ method: "POST" }));
  });

  it("sendMessage sends the client id so retries are safe", async () => {
    const { sendMessage } = await loadClient("false");
    const fetchMock = stubFetch(new Response(null, { status: 204 }));
    await sendMessage("p1", "hello", "abc123def456");
    expect(JSON.parse(fetchMock.mock.calls[0][1]!.body as string)).toEqual({ content: "hello", id: "abc123def456" });
  });

  it("files and findings come from the backend", async () => {
    const { listFiles, listFindings } = await loadClient("false");
    let fetchMock = stubFetch(Response.json([{ id: "f" }]));
    await expect(listFiles("p1")).resolves.toEqual([{ id: "f" }]);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/projects/p1/files");
    fetchMock = stubFetch(Response.json([]));
    await listFindings("p1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/projects/p1/findings");
  });

  it("errors carry the backend's explanation", async () => {
    const { sendMessage, startRun, ApiError } = await loadClient("false");
    stubFetch(Response.json({ detail: "This project's run stopped. Start a new run to keep chatting." }, { status: 409 }));
    const error = await sendMessage("p1", "hi").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe("This project's run stopped. Start a new run to keep chatting.");
    expect(error.status).toBe(409);
    stubFetch(Response.json({ detail: { message: "Another project's run is in progress.", running_project_id: "x" } }, { status: 409 }));
    await expect(startRun("p1")).rejects.toThrow("Another project's run is in progress.");
  });

  it("mock mode run controls don't call the network", async () => {
    const { startRun, stopRun } = await loadClient("true");
    const fetchMock = stubFetch(Response.json({}));
    await expect(startRun("p1")).resolves.toBe("running");
    await expect(stopRun("p1")).resolves.toBe("stopped");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
