import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage, ProjectSummary } from "./types/schemas";

// Replace the API client; replies are delivered through the (real) mock event bus.
const api = vi.hoisted(() => ({
  listProjects: vi.fn(),
  createProject: vi.fn(),
  listMessages: vi.fn(),
  sendMessage: vi.fn(),
}));
vi.mock("./api/client", () => ({ USE_MOCK: true, ...api }));

import App from "./App";
import { publishMockEvent } from "./api/mockEvents";

const PROJECTS: ProjectSummary[] = [
  { id: "p1", name: "Project 1", created_at: new Date().toISOString() },
  { id: "p2", name: "Other", created_at: new Date().toISOString() },
];

function message(id: string, content: string, role: ChatMessage["role"] = "assistant", projectId = "p1"): ChatMessage {
  return { id, project_id: projectId, role, content, created_at: new Date().toISOString() };
}

function reply(id: string, content = "Trademarked 2026  Jiggle by Kerry", projectId = "p1") {
  act(() => {
    publishMockEvent({
      id: `e-${id}`,
      type: "chat_reply",
      project_id: projectId,
      created_at: new Date().toISOString(),
      payload: message(id, content, "assistant", projectId),
    });
  });
}

const input = () => screen.getByLabelText("Ask SCRAP anything about your data") as HTMLTextAreaElement;
const typing = () => screen.queryByLabelText("SCRAP is typing");
const bubbles = () => Array.from(document.querySelectorAll(".bubble:not(.bubble--typing)")).map((b) => b.textContent);

function send(text: string) {
  fireEvent.change(input(), { target: { value: text } });
  fireEvent.click(screen.getByLabelText("Send message"));
}

async function renderApp() {
  render(<App />);
  await act(async () => {});
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  api.listProjects.mockResolvedValue(PROJECTS);
  api.createProject.mockImplementation(async (name: string) => ({
    id: `new-${name}`,
    name,
    created_at: new Date().toISOString(),
  }));
  api.listMessages.mockResolvedValue([]);
  api.sendMessage.mockResolvedValue(undefined);
});
afterEach(() => {
  vi.useRealTimers();
});

describe("chat", () => {
  it("replaces the welcome card with the conversation and shows the reply", async () => {
    await renderApp();
    expect(screen.getByText(/Welcome to/)).toBeTruthy();
    send("hello");
    expect(screen.queryByText(/Welcome to/)).toBeNull();
    expect(api.sendMessage).toHaveBeenCalledWith("p1", "hello");
    expect(typing()).toBeTruthy();
    reply("r1");
    expect(bubbles()).toEqual(["hello", "Trademarked 2026  Jiggle by Kerry"]);
    expect(typing()).toBeNull();
  });

  it("keeps the typing indicator until every pending message has a reply", async () => {
    await renderApp();
    send("one");
    send("two");
    reply("r1");
    expect(typing()).toBeTruthy();
    reply("r2");
    expect(typing()).toBeNull();
  });

  it("stops the typing indicator if no reply arrives", async () => {
    vi.useFakeTimers();
    vi.spyOn(console, "warn").mockImplementation(() => {});
    await renderApp();
    send("hello");
    expect(typing()).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(typing()).toBeNull();
    expect(console.warn).toHaveBeenCalled();
  });

  it("ignores a replayed chat_reply with an id it already has", async () => {
    await renderApp();
    send("hello");
    reply("r1");
    reply("r1");
    expect(bubbles()).toEqual(["hello", "Trademarked 2026  Jiggle by Kerry"]);
  });

  it("loads a project's history once when it is selected, without duplicates", async () => {
    api.listMessages.mockImplementation(async (projectId: string) =>
      projectId === "p2" ? [message("h1", "earlier question", "user", "p2"), message("h2", "earlier answer", "assistant", "p2")] : [],
    );
    await renderApp();
    expect(api.listMessages).toHaveBeenCalledWith("p1");
    await act(async () => {
      fireEvent.click(screen.getByText("Other"));
    });
    expect(bubbles()).toEqual(["earlier question", "earlier answer"]);
    reply("h2", "earlier answer", "p2"); // the same message replayed over SSE
    expect(bubbles()).toEqual(["earlier question", "earlier answer"]);
    await act(async () => {
      fireEvent.click(screen.getByText("Project 1"));
    });
    await act(async () => {
      fireEvent.click(screen.getByText("Other"));
    });
    expect(api.listMessages.mock.calls.filter(([id]) => id === "p2")).toHaveLength(1);
  });

  it("keeps the typed text when sending before projects have loaded", async () => {
    api.listProjects.mockReturnValue(new Promise(() => {}));
    await renderApp();
    send("too early");
    expect(input().value).toBe("too early");
    expect(api.sendMessage).not.toHaveBeenCalled();
  });

  it("clears the typing indicator and logs when sending fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.sendMessage.mockRejectedValue(new Error("network down"));
    await renderApp();
    await act(async () => send("hello"));
    expect(typing()).toBeNull();
    expect(console.error).toHaveBeenCalled();
  });
});

describe("projects", () => {
  it("logs instead of leaving an unhandled rejection when projects fail to load", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    api.listProjects.mockRejectedValue(new Error("backend down"));
    await renderApp();
    expect(error).toHaveBeenCalled();
    expect(screen.getByText(/Welcome to/)).toBeTruthy();
  });

  it("gives each new project a unique name even when clicked twice quickly", async () => {
    await renderApp();
    const button = screen.getByRole("button", { name: /New Project/ });
    await act(async () => {
      fireEvent.click(button);
      fireEvent.click(button);
    });
    const names = api.createProject.mock.calls.map(([name]) => name);
    expect(new Set(names).size).toBe(2);
    const nav = screen.getByRole("navigation", { name: "Recent projects" });
    expect(within(nav).getAllByText(/^Project \d+$/)).toHaveLength(3);
  });
});
