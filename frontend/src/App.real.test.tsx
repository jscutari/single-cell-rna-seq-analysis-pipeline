// App against the real backend's API shapes (USE_MOCK off). The stream hook is
// replaced so tests can push backend events straight into the app.
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage, Finding, ProjectSummary } from "./types/schemas";
import type { FindingCard, StreamEvent } from "./types/ui";

const api = vi.hoisted(() => ({
  listProjects: vi.fn(),
  createProject: vi.fn(),
  listChats: vi.fn(),
  listMessages: vi.fn(),
  listFiles: vi.fn(),
  listFindings: vi.fn(),
  getOverview: vi.fn(),
  sendMessage: vi.fn(),
  startRun: vi.fn(),
  stopRun: vi.fn(),
  uploadDataset: vi.fn(),
}));
vi.mock("./api/client", () => ({
  USE_MOCK: false,
  ...api,
  mainChat: (projectId: string) => ({ id: `${projectId}-chat-1`, project_id: projectId, title: "Chat 1", created_at: "" }),
}));

const stream = vi.hoisted(() => ({ handler: null as null | ((e: StreamEvent) => void), calls: [] as unknown[][] }));
vi.mock("./api/useProjectStream", () => ({
  useProjectStream: (...args: unknown[]) => {
    stream.calls.push(args);
    stream.handler = args[1] as (e: StreamEvent) => void;
  },
}));

import App from "./App";

const NOW = "2026-10-17T00:00:00Z";
const PROJECT: ProjectSummary = { id: "covid_pbmc", name: "COVID-19 PBMC", created_at: NOW };

const msg = (id: string, content: string, role: ChatMessage["role"] = "assistant"): ChatMessage => ({
  id,
  project_id: PROJECT.id,
  role,
  content,
  created_at: NOW,
});

function push(event: Omit<StreamEvent, "id" | "created_at" | "project_id">) {
  act(() => stream.handler!({ id: "1", created_at: NOW, project_id: PROJECT.id, ...event } as StreamEvent));
}

async function click(el: HTMLElement) {
  await act(async () => {
    fireEvent.click(el);
  });
}
const input = () => screen.queryByLabelText("Ask SCRAP anything about your data") as HTMLTextAreaElement | null;
const bubbles = () => Array.from(document.querySelectorAll(".bubble:not(.bubble--typing)")).map((b) => b.textContent);
const runBar = () => screen.getByRole("status", { name: "Analysis run" });
const projectButton = () => screen.getByRole("button", { name: /^COVID-19 PBMC/ });

async function renderApp() {
  render(<App />);
  await act(async () => {});
}

async function openProject() {
  await click(projectButton());
  await act(async () => {});
}

const finding = (over: Partial<Finding> = {}): Finding => ({
  id: "f1",
  hypothesis_id: "h1",
  claim: "ISGs are up",
  test: "DESeq2",
  statistic: 6,
  p_adj: 1e-10,
  effect_size: 2.4,
  figure_path: null,
  critic_verdict: "approve",
  critic_notes: "",
  novelty: "known",
  citations: [],
  sources_searched: [],
  notebook_path: null,
  ...over,
});

beforeEach(() => {
  localStorage.clear(); // chats saved in the browser must not leak between tests
  Element.prototype.scrollIntoView = vi.fn();
  stream.handler = null;
  stream.calls = [];
  api.listProjects.mockResolvedValue([PROJECT]);
  api.listChats.mockResolvedValue({
    chats: [{ id: "covid_pbmc-chat-1", project_id: PROJECT.id, title: "Chat 1", created_at: NOW }],
    messages: { "covid_pbmc-chat-1": [msg("a1", "Hello from intake")] },
    run: { status: "idle", stage: null },
    lastEventId: 41,
  });
  api.listFiles.mockResolvedValue([]);
  api.listFindings.mockResolvedValue([]);
  api.getOverview.mockResolvedValue(null);
  api.sendMessage.mockResolvedValue(undefined);
  api.startRun.mockResolvedValue("running");
  api.stopRun.mockResolvedValue("stopped");
  api.uploadDataset.mockResolvedValue(undefined);
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("run controls", () => {
  it("shows the run, starts it, and follows its stages", async () => {
    await renderApp();
    await openProject();
    expect(within(runBar()).getByText("Not started")).toBeTruthy();
    await click(within(runBar()).getByRole("button", { name: "Start run" }));
    expect(api.startRun).toHaveBeenCalledWith(PROJECT.id);
    expect(within(runBar()).getByText("Running")).toBeTruthy();
    push({ type: "stage_done", payload: { stage: "literature", summary: "" } });
    expect(runBar().textContent).toContain("reading the literature");
    push({ type: "stage_done", payload: { stage: "report", summary: "" } });
    expect(within(runBar()).getByText("Finished")).toBeTruthy();
    expect(within(runBar()).getByRole("button", { name: "Start new run" })).toBeTruthy();
  });

  it("stops a running run", async () => {
    api.listChats.mockResolvedValue({ chats: [], messages: {}, run: { status: "running", stage: "analysis" }, lastEventId: 3 });
    await renderApp();
    await openProject();
    await click(within(runBar()).getByRole("button", { name: "Stop run" }));
    expect(api.stopRun).toHaveBeenCalledWith(PROJECT.id);
    expect(within(runBar()).getByText("Stopped")).toBeTruthy();
  });

  it("run_status events update the bar", async () => {
    await renderApp();
    await openProject();
    push({ type: "run_status", payload: { status: "failed" } });
    expect(within(runBar()).getByText("Failed")).toBeTruthy();
  });

  it("shows why a start was refused", async () => {
    api.startRun.mockRejectedValue(new Error("Another project's run is in progress."));
    await renderApp();
    await openProject();
    await click(within(runBar()).getByRole("button", { name: "Start run" }));
    expect(runBar().textContent).toContain("Another project's run is in progress.");
  });

  it("streams from the snapshot's last event id", async () => {
    await renderApp();
    await openProject();
    expect(stream.calls.at(-1)).toEqual([PROJECT.id, expect.any(Function), 41]);
  });
});

describe("chat with the backend", () => {
  it("opens the saved conversation as Chat 1", async () => {
    await renderApp();
    await openProject();
    const list = screen.getByRole("list", { name: "COVID-19 PBMC chats" });
    expect(Array.from(list.querySelectorAll(".chat-title")).map((t) => t.textContent)).toEqual(["Chat 1"]);
    await click(within(list).getByRole("button", { name: "Chat 1" }));
    expect(bubbles()).toEqual(["Hello from intake"]);
  });

  it("New chat opens an empty chat whose messages survive a reload", async () => {
    const { unmount } = render(<App />);
    await act(async () => {});
    await openProject();
    const list = () => screen.getByRole("list", { name: "COVID-19 PBMC chats" });
    await click(within(list()).getByRole("button", { name: "New chat" }));
    expect(Array.from(list().querySelectorAll(".chat-title")).map((t) => t.textContent)).toEqual(["Chat 1", "Chat 2"]);
    expect(bubbles()).toEqual([]);
    fireEvent.change(input()!, { target: { value: "Which monocytes changed?" } });
    await click(screen.getByLabelText("Send message"));
    const id = api.sendMessage.mock.calls[0][2];
    push({ type: "chat_reply", payload: msg("r1", "CD14 monocytes.") });
    expect(bubbles()).toEqual(["Which monocytes changed?", "CD14 monocytes."]);
    unmount();

    // The backend returns the whole project conversation as one list.
    api.listChats.mockResolvedValue({
      chats: [{ id: "covid_pbmc-chat-1", project_id: PROJECT.id, title: "Chat 1", created_at: NOW }],
      messages: {
        "covid_pbmc-chat-1": [msg("a1", "Hello from intake"), msg(id, "Which monocytes changed?", "user"), msg("r1", "CD14 monocytes.")],
      },
      run: { status: "idle", stage: null },
      lastEventId: 41,
    });
    await renderApp();
    await openProject();
    const titles = Array.from(list().querySelectorAll(".chat-title")).map((t) => t.textContent);
    expect(titles).toEqual(["Chat 1", "Which monocytes changed"]);
    await click(within(list()).getByRole("button", { name: "Chat 1" }));
    expect(bubbles()).toEqual(["Hello from intake"]);
    await click(within(list()).getByRole("button", { name: "Which monocytes changed" }));
    expect(bubbles()).toEqual(["Which monocytes changed?", "CD14 monocytes."]);
  });

  it("sending from the start screen starts a new chat in the first project, with an id", async () => {
    await renderApp();
    fireEvent.change(input()!, { target: { value: "Compare COVID vs healthy" } });
    await click(screen.getByLabelText("Send message"));
    await act(async () => {});
    const [pid, text, id] = api.sendMessage.mock.calls[0];
    expect([pid, text]).toEqual([PROJECT.id, "Compare COVID vs healthy"]);
    expect(id).toMatch(/^[0-9a-f]{32}$/);
    expect(bubbles()).toEqual(["Compare COVID vs healthy"]);
    // The backend echoes our message as user_message with the same id: not shown twice.
    push({ type: "user_message", payload: msg(id, "Compare COVID vs healthy", "user") });
    push({ type: "chat_reply", payload: msg("r1", "Sounds good, starting.") });
    expect(bubbles()).toEqual(["Compare COVID vs healthy", "Sounds good, starting."]);
  });

  it("shows messages sent from another tab", async () => {
    await renderApp();
    await openProject();
    await click(screen.getByRole("button", { name: "Chat 1" }));
    push({ type: "user_message", payload: msg("other-tab", "From my laptop", "user") });
    expect(bubbles()).toContain("From my laptop");
  });

  it("explains in the chat when the backend refuses a message (a warning, not an app error)", async () => {
    api.sendMessage.mockRejectedValue(
      Object.assign(new Error("This project's run stopped. Start a new run to keep chatting."), { status: 409 }),
    );
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    await renderApp();
    await openProject();
    await click(screen.getByRole("button", { name: "Chat 1" }));
    fireEvent.change(input()!, { target: { value: "hi" } });
    await click(screen.getByLabelText("Send message"));
    expect(bubbles().at(-1)).toBe("⚠️ This project's run stopped. Start a new run to keep chatting.");
    expect(screen.queryByLabelText("SCRAP is typing")).toBeNull();
    expect(warn).toHaveBeenCalled();
    expect(error).not.toHaveBeenCalled();
  });

  it("logs server failures as errors", async () => {
    api.sendMessage.mockRejectedValue(Object.assign(new Error("boom"), { status: 502 }));
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    await renderApp();
    await openProject();
    await click(screen.getByRole("button", { name: "Chat 1" }));
    fireEvent.change(input()!, { target: { value: "hi" } });
    await click(screen.getByLabelText("Send message"));
    expect(error).toHaveBeenCalled();
    expect(bubbles().at(-1)).toBe("⚠️ boom");
  });

  it("a reply before the chat list loaded still lands in Chat 1", async () => {
    api.listChats.mockReturnValue(new Promise(() => {}));
    await renderApp();
    await openProject();
    push({ type: "chat_reply", payload: msg("early", "I looked at your dataset.") });
    await click(screen.getByRole("button", { name: "Chat 1" }));
    expect(bubbles()).toEqual(["I looked at your dataset."]);
  });
});

describe("results from the backend", () => {
  const card = (over: Partial<FindingCard>): FindingCard => ({ finding: finding(), chart: null, mock: false, ...over });

  it("renders real charts, figures, titles and links", async () => {
    api.listFindings.mockResolvedValue([
      card({
        chart: { type: "volcano", points: [[2, 5]], threshold: 1.3, labels: [], x_label: "LFC" },
        hypothesis_title: "Interferon response",
        figure_url: "/api/projects/covid_pbmc/files/fig.png",
        notebook_url: "/api/projects/covid_pbmc/files/h1.ipynb",
      }),
      card({ finding: finding({ id: "f2", claim: "HLA-II down" }), figure_url: "/api/projects/covid_pbmc/files/f2.png" }),
      card({ finding: finding({ id: "f3", claim: "No table" }) }),
    ]);
    await renderApp();
    await openProject();
    const [first, second, third] = screen.getAllByRole("article");
    expect(within(first).getByRole("img", { name: /Volcano/ })).toBeTruthy();
    expect(within(first).getByText("Interferon response")).toBeTruthy();
    expect(within(first).getByRole("link", { name: "Notebook" }).getAttribute("href")).toBe("/api/projects/covid_pbmc/files/h1.ipynb");
    expect(within(first).queryByText("sample data")).toBeNull();
    expect(within(second).getByRole("img", { name: "Figure for: HLA-II down" }).getAttribute("src")).toBe(
      "/api/projects/covid_pbmc/files/f2.png",
    );
    expect(within(third).getByText("No chart for this finding")).toBeTruthy();
  });

  it("re-reads files and findings after result events (debounced)", async () => {
    await renderApp();
    await openProject();
    vi.useFakeTimers();
    api.listFindings.mockResolvedValue([card({ finding: finding({ claim: "New finding" }) })]);
    push({ type: "hypothesis_status", payload: { id: "h1" } as never });
    push({ type: "finding", payload: finding({ claim: "New finding" }) });
    push({ type: "stage_done", payload: { stage: "analysis", summary: "" } });
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    vi.useRealTimers();
    await act(async () => {});
    expect(api.listFindings).toHaveBeenCalledTimes(2); // first load + one refresh for the burst
    expect(api.listFiles).toHaveBeenCalledTimes(2);
    expect(screen.getByText("New finding")).toBeTruthy();
  });

  it("does not fetch results for projects that were never opened", async () => {
    await renderApp();
    vi.useFakeTimers();
    push({ type: "finding", payload: finding() });
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(api.listFindings).not.toHaveBeenCalled();
  });

  it("keeps local uploads when the server's file list refreshes", async () => {
    URL.createObjectURL = vi.fn(() => "blob:local-1");
    URL.revokeObjectURL = vi.fn();
    api.listFiles.mockResolvedValue([{ id: "srv", project_id: PROJECT.id, name: "report.md", kind: "text", size_bytes: 1, url: "/x", added_at: NOW }]);
    await renderApp();
    await openProject();
    await act(async () => {
      fireEvent.change(screen.getByLabelText("Upload files"), { target: { files: [new File(["x"], "mine.txt")] } });
    });
    vi.useFakeTimers();
    push({ type: "finding", payload: finding() });
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    vi.useRealTimers();
    await act(async () => {});
    expect(Array.from(document.querySelectorAll(".file-name")).map((f) => f.textContent)).toEqual(["mine.txt", "report.md"]);
  });
});


describe("dataset upload", () => {
  it("an .h5ad attached in the chat is uploaded, and the message waits for it", async () => {
    let finish!: () => void;
    api.uploadDataset.mockReturnValue(new Promise<void>((resolve) => (finish = resolve)));
    await renderApp();
    await openProject();
    await click(screen.getByRole("button", { name: "Chat 1" }));
    const picked = new File(["x"], "wilk.h5ad");
    await act(async () => {
      fireEvent.change(screen.getByLabelText("Choose files to attach"), { target: { files: [picked] } });
    });
    expect(api.uploadDataset).toHaveBeenCalledWith(PROJECT.id, picked);
    expect(bubbles().at(-1)).toContain("Uploading dataset wilk.h5ad");
    fireEvent.change(input()!, { target: { value: "Analyze this" } });
    await click(screen.getByLabelText("Send message"));
    expect(api.sendMessage).not.toHaveBeenCalled(); // still uploading
    await act(async () => finish());
    expect(api.sendMessage).toHaveBeenCalledTimes(1);
    expect(bubbles().some((b) => b?.startsWith("✅ Dataset uploaded"))).toBe(true);
  });

  it("other files are not sent as the dataset", async () => {
    await renderApp();
    await openProject();
    await act(async () => {
      fireEvent.change(screen.getByLabelText("Upload files"), { target: { files: [new File(["%PDF"], "paper.pdf")] } });
    });
    expect(api.uploadDataset).not.toHaveBeenCalled();
  });
});
