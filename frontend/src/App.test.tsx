import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage, ProjectSummary } from "./types/schemas";
import type { Chat } from "./types/ui";

// Replace the API client; replies are delivered through the (real) mock event bus.
const api = vi.hoisted(() => ({
  listProjects: vi.fn(),
  createProject: vi.fn(),
  listChats: vi.fn(),
  listMessages: vi.fn(),
  sendMessage: vi.fn(),
}));
vi.mock("./api/client", () => ({ USE_MOCK: true, ...api }));

import App from "./App";
import { publishMockEvent } from "./api/mockEvents";

const NOW = new Date().toISOString();
const PROJECTS: ProjectSummary[] = [
  { id: "p1", name: "Project 1", created_at: NOW },
  { id: "p2", name: "Other", created_at: NOW },
];

function message(id: string, content: string, role: ChatMessage["role"] = "assistant", projectId = "p1"): ChatMessage {
  return { id, project_id: projectId, role, content, created_at: NOW };
}
function seededChats(projectId: string): { chats: Chat[]; messages: Record<string, ChatMessage[]> } {
  if (projectId !== "p1") {
    return { chats: [{ id: `${projectId}-c1`, project_id: projectId, title: "Chat 1", created_at: NOW }], messages: {} };
  }
  return {
    chats: [
      { id: "c1", project_id: "p1", title: "Chat 1", created_at: NOW },
      { id: "c2", project_id: "p1", title: "Chat 2", created_at: NOW },
    ],
    messages: {
      c1: [message("c1q", "first question", "user"), message("c1a", "first answer")],
      c2: [message("c2q", "second question", "user"), message("c2a", "second answer")],
    },
  };
}

function reply(id: string, content = "Trademarked 2026  Jiggle by Kerry", projectId = "p1") {
  act(() => {
    publishMockEvent({
      id: `e-${id}`,
      type: "chat_reply",
      project_id: projectId,
      created_at: NOW,
      payload: message(id, content, "assistant", projectId),
    });
  });
}

const input = () => screen.queryByLabelText("Ask SCRAP anything about your data") as HTMLTextAreaElement | null;
const typing = () => screen.queryByLabelText("SCRAP is typing");
const bubbles = () => Array.from(document.querySelectorAll(".bubble:not(.bubble--typing)")).map((b) => b.textContent);
const chatList = (name: string) => screen.queryByRole("list", { name: `${name} chats` });
const chatTitles = (name: string) => within(chatList(name)!).getAllByRole("button").map((b) => b.textContent);

function send(text: string) {
  fireEvent.change(input()!, { target: { value: text } });
  fireEvent.click(screen.getByLabelText("Send message"));
}
async function click(element: HTMLElement) {
  await act(async () => {
    fireEvent.click(element);
  });
}
const projectButton = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name}`) });
async function openChat(project: string, chat: string) {
  if (!chatList(project)) await click(projectButton(project));
  await click(within(chatList(project)!).getByRole("button", { name: chat }));
}

async function renderApp() {
  render(<App />);
  await act(async () => {});
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  api.listProjects.mockResolvedValue(PROJECTS);
  api.createProject.mockImplementation(async (name: string) => ({ id: `new-${name}`, name, created_at: NOW }));
  api.listChats.mockImplementation(async (projectId: string) => seededChats(projectId));
  api.sendMessage.mockResolvedValue(undefined);
});
afterEach(() => {
  vi.useRealTimers();
});

describe("sidebar navigation", () => {
  it("starts on the welcome screen with no project open", async () => {
    await renderApp();
    expect(screen.getByText(/Welcome to/)).toBeTruthy();
    expect(input()).toBeTruthy();
    expect(chatList("Project 1")).toBeNull();
  });

  it("clicking a project opens its page (no chat box) and shows its chats", async () => {
    await renderApp();
    await click(projectButton("Project 1"));
    expect(screen.getByRole("heading", { name: "Project 1" })).toBeTruthy();
    expect(input()).toBeNull();
    expect(chatTitles("Project 1")).toEqual(["New chat", "Chat 1", "Chat 2"]);
    expect(projectButton("Project 1").getAttribute("aria-expanded")).toBe("true");
  });

  it("collapses the dropdown when the open project is clicked again or another project is opened", async () => {
    await renderApp();
    await click(projectButton("Project 1"));
    await click(projectButton("Project 1"));
    expect(chatList("Project 1")).toBeNull();
    await click(projectButton("Project 1"));
    await click(projectButton("Other"));
    expect(chatList("Project 1")).toBeNull();
    expect(chatTitles("Other")).toEqual(["New chat", "Chat 1"]);
  });

  it("loads a project's chats only once", async () => {
    await renderApp();
    await click(projectButton("Project 1"));
    await click(projectButton("Other"));
    await click(projectButton("Project 1"));
    expect(api.listChats.mock.calls.filter(([id]) => id === "p1")).toHaveLength(1);
  });

  it("opening a chat shows its saved messages and the chat box", async () => {
    await renderApp();
    await openChat("Project 1", "Chat 2");
    expect(bubbles()).toEqual(["second question", "second answer"]);
    expect(input()).toBeTruthy();
  });

  it("New chat adds the next numbered chat and opens it on the welcome card", async () => {
    await renderApp();
    await click(projectButton("Project 1"));
    await click(within(chatList("Project 1")!).getByRole("button", { name: "New chat" }));
    expect(chatTitles("Project 1")).toEqual(["New chat", "Chat 1", "Chat 2", "Chat 3"]);
    expect(screen.getByText(/Welcome to/)).toBeTruthy();
    send("hello");
    expect(screen.queryByText(/Welcome to/)).toBeNull();
    expect(bubbles()).toEqual(["hello"]);
  });
});

describe("chat", () => {
  it("sends in the open chat and shows the reply there only", async () => {
    await renderApp();
    await openChat("Project 1", "Chat 1");
    send("hello");
    expect(api.sendMessage).toHaveBeenCalledWith("p1", "hello");
    expect(typing()).toBeTruthy();
    reply("r1");
    expect(bubbles()).toEqual(["first question", "first answer", "hello", "Trademarked 2026  Jiggle by Kerry"]);
    expect(typing()).toBeNull();
    await openChat("Project 1", "Chat 2");
    expect(bubbles()).toEqual(["second question", "second answer"]);
  });

  it("delivers a reply to the chat that was waiting, even after switching chats", async () => {
    await renderApp();
    await openChat("Project 1", "Chat 1");
    send("question in chat 1");
    await openChat("Project 1", "Chat 2");
    reply("r1");
    expect(bubbles()).toEqual(["second question", "second answer"]);
    await openChat("Project 1", "Chat 1");
    expect(bubbles()).toContain("Trademarked 2026  Jiggle by Kerry");
    expect(typing()).toBeNull();
  });

  it("sending from the start screen starts a new chat in the first project", async () => {
    await renderApp();
    send("hello from home");
    await act(async () => {});
    expect(chatTitles("Project 1")).toEqual(["New chat", "Chat 1", "Chat 2", "Chat 3"]);
    expect(bubbles()).toEqual(["hello from home"]);
    reply("r1");
    expect(bubbles()).toEqual(["hello from home", "Trademarked 2026  Jiggle by Kerry"]);
  });

  it("keeps the typing indicator until every pending message has a reply", async () => {
    await renderApp();
    await openChat("Project 1", "Chat 1");
    send("one");
    send("two");
    reply("r1");
    expect(typing()).toBeTruthy();
    reply("r2");
    expect(typing()).toBeNull();
  });

  it("stops the typing indicator if no reply arrives", async () => {
    await renderApp();
    await openChat("Project 1", "Chat 1");
    vi.useFakeTimers();
    vi.spyOn(console, "warn").mockImplementation(() => {});
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
    await openChat("Project 1", "Chat 1");
    send("hello");
    reply("r1");
    reply("r1");
    expect(bubbles().filter((b) => b === "Trademarked 2026  Jiggle by Kerry")).toHaveLength(1);
  });

  it("clears the typing indicator and logs when sending fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.sendMessage.mockRejectedValue(new Error("network down"));
    await renderApp();
    await openChat("Project 1", "Chat 1");
    await act(async () => send("hello"));
    expect(typing()).toBeNull();
    expect(console.error).toHaveBeenCalled();
  });

  it("keeps the typed text when sending before projects have loaded", async () => {
    api.listProjects.mockReturnValue(new Promise(() => {}));
    await renderApp();
    send("too early");
    expect(input()!.value).toBe("too early");
    expect(api.sendMessage).not.toHaveBeenCalled();
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

  it("New Project opens its empty page, and double clicks give unique names", async () => {
    await renderApp();
    const button = screen.getByRole("button", { name: /New Project/ });
    await act(async () => {
      fireEvent.click(button);
      fireEvent.click(button);
    });
    const names = api.createProject.mock.calls.map(([name]) => name);
    expect(new Set(names).size).toBe(2);
    const opened = screen.getByRole("heading", { level: 1 }).textContent!;
    expect(names).toContain(opened);
    expect(chatTitles(opened)).toEqual(["New chat"]);
    expect(api.listChats).not.toHaveBeenCalledWith(`new-${opened}`);
  });
});
