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
  listFiles: vi.fn(),
  listFindings: vi.fn(),
  sendMessage: vi.fn(),
}));
vi.mock("./api/client", () => ({ USE_MOCK: true, ...api }));

import App from "./App";
import { publishMockEvent } from "./api/mockEvents";
import { mockFilesFor, mockFindingsFor } from "./data/mockWorkspace";

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
const chatTitles = (name: string) =>
  within(chatList(name)!)
    .getAllByRole("button")
    .filter((b) => !b.classList.contains("chat-rename-button"))
    .map((b) => b.textContent);

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
  api.listFiles.mockImplementation(async (projectId: string) => mockFilesFor(projectId));
  api.listFindings.mockImplementation(async (projectId: string) => mockFindingsFor(projectId));
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
    expect(chatTitles("Project 1")).toEqual(["New chat", "Chat 1", "Chat 2", "From home"]);
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

describe("project page", () => {
  it("lists the project's files and key findings with charts, and has no chat box", async () => {
    await renderApp();
    await click(projectButton("Project 1"));
    const files = document.querySelectorAll(".file-row");
    expect(Array.from(files).map((f) => f.querySelector(".file-name")!.textContent)).toEqual([
      "processed.h5ad",
      "wilk_2020_covid_pbmc.pdf",
      "de_results.csv",
      "umap_clusters.svg",
      "analysis_notes.txt",
      "report.md",
      "ifn_alpha_cd14_monocytes.ipynb",
      "ifn_alpha_donor_scores.png",
    ]);
    const findings = screen.getAllByRole("article");
    expect(findings).toHaveLength(3);
    expect(within(findings[0]).getByRole("img", { name: /Volcano plot/ })).toBeTruthy();
    expect(within(findings[1]).getByRole("img", { name: /Bar chart/ })).toBeTruthy();
    expect(within(findings[2]).getByRole("img", { name: /UMAP/ })).toBeTruthy();
    expect(within(findings[0]).getByText("p_adj 2.1e−8")).toBeTruthy();
    expect(within(findings[0]).getByText("Critic approved")).toBeTruthy();
    expect(input()).toBeNull();
  });

  it("loads a project's files and findings only once", async () => {
    await renderApp();
    await click(projectButton("Project 1"));
    await click(projectButton("Other"));
    await click(projectButton("Project 1"));
    expect(api.listFiles.mock.calls.filter(([id]) => id === "p1")).toHaveLength(1);
    expect(api.listFindings.mock.calls.filter(([id]) => id === "p1")).toHaveLength(1);
  });

  it("shows empty states for a new project", async () => {
    await renderApp();
    await click(screen.getByRole("button", { name: /New Project/ }));
    expect(screen.getByText("Upload a dataset or paper to get started.")).toBeTruthy();
    expect(screen.getByText(/No findings yet/)).toBeTruthy();
    expect(api.listFiles).not.toHaveBeenCalled();
  });
});

describe("file preview", () => {
  const fileButton = (name: string) => screen.getByRole("button", { name: new RegExp(name.replace(".", "\\.")) });
  const panel = () => screen.queryByRole("complementary", { name: /^Preview of/ });

  it("opens a file in the right panel and closes it with Escape, the close button, or a second click", async () => {
    await renderApp();
    await click(projectButton("Project 1"));
    await click(fileButton("umap_clusters.svg"));
    expect(panel()!.getAttribute("aria-label")).toBe("Preview of umap_clusters.svg");
    expect(fileButton("umap_clusters.svg").getAttribute("aria-current")).toBe("true");
    await act(async () => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(panel()).toBeNull();
    await click(fileButton("umap_clusters.svg"));
    await click(screen.getByLabelText("Close preview"));
    expect(panel()).toBeNull();
    await click(fileButton("umap_clusters.svg"));
    await click(fileButton("umap_clusters.svg"));
    expect(panel()).toBeNull();
  });

  it("switches the preview when another file is clicked, and closes it when leaving the page", async () => {
    await renderApp();
    await click(projectButton("Project 1"));
    await click(fileButton("umap_clusters.svg"));
    await click(fileButton("processed.h5ad"));
    expect(panel()!.getAttribute("aria-label")).toBe("Preview of processed.h5ad");
    await openChat("Project 1", "Chat 1");
    expect(panel()).toBeNull();
    await click(projectButton("Project 1"));
    expect(panel()).toBeNull();
  });

  it("adds uploaded files to the project and previews them", async () => {
    URL.createObjectURL = vi.fn(() => "blob:mock-1");
    URL.revokeObjectURL = vi.fn();
    await renderApp();
    await click(projectButton("Project 1"));
    const upload = screen.getByLabelText("Upload files") as HTMLInputElement;
    const picked = new File(["<svg/>"], "my_plot.svg", { type: "image/svg+xml" });
    await act(async () => {
      fireEvent.change(upload, { target: { files: [picked] } });
    });
    expect(document.querySelector(".file-row .file-name")!.textContent).toBe("my_plot.svg");
    expect(panel()!.getAttribute("aria-label")).toBe("Preview of my_plot.svg");
    expect(screen.getByRole("img", { name: "my_plot.svg" }).getAttribute("src")).toBe("blob:mock-1");
  });
});

describe("sidebar collapse", () => {
  it("collapses to an icon rail, hides chats, and remembers the choice", async () => {
    localStorage.removeItem("scrap.sidebarCollapsed");
    await renderApp();
    await click(projectButton("Project 1"));
    expect(chatList("Project 1")).toBeTruthy();
    await click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(document.querySelector(".sidebar")!.classList.contains("sidebar--collapsed")).toBe(true);
    expect(chatList("Project 1")).toBeNull();
    expect(localStorage.getItem("scrap.sidebarCollapsed")).toBe("1");
    await click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(chatList("Project 1")).toBeTruthy();
    expect(localStorage.getItem("scrap.sidebarCollapsed")).toBe("0");
  });
});

describe("chat names", () => {
  async function renameTo(title: string, key = "Enter") {
    const field = screen.getByRole("textbox", { name: /^Rename/ });
    fireEvent.change(field, { target: { value: title } });
    await act(async () => {
      fireEvent.keyDown(field, { key });
    });
  }

  it("renames a chat with the pencil button; Escape cancels", async () => {
    await renderApp();
    await click(projectButton("Project 1"));
    await click(screen.getByRole("button", { name: "Rename Chat 1" }));
    await renameTo("Monocyte questions");
    expect(chatTitles("Project 1")).toEqual(["New chat", "Monocyte questions", "Chat 2"]);
    await click(screen.getByRole("button", { name: "Rename Chat 2" }));
    await renameTo("ignored", "Escape");
    expect(chatTitles("Project 1")).toEqual(["New chat", "Monocyte questions", "Chat 2"]);
  });

  it("double-clicking a chat title renames it too", async () => {
    await renderApp();
    await click(projectButton("Project 1"));
    await act(async () => {
      fireEvent.doubleClick(within(chatList("Project 1")!).getByRole("button", { name: "Chat 2" }));
    });
    await renameTo("Neutrophils");
    expect(chatTitles("Project 1")).toEqual(["New chat", "Chat 1", "Neutrophils"]);
  });

  it("names a new chat from its first message, but never renames a chat the user named or one with history", async () => {
    await renderApp();
    await click(projectButton("Project 1"));
    await click(within(chatList("Project 1")!).getByRole("button", { name: "New chat" }));
    send("Can you check HLA class II in monocytes?");
    expect(chatTitles("Project 1")).toEqual(["New chat", "Chat 1", "Chat 2", "Check HLA class II in monocytes"]);
    send("And in CD16 monocytes?");
    expect(chatTitles("Project 1")).toEqual(["New chat", "Chat 1", "Chat 2", "Check HLA class II in monocytes"]);
    await openChat("Project 1", "Chat 1");
    send("a follow-up in an old chat");
    expect(chatTitles("Project 1")[1]).toBe("Chat 1");
    await click(within(chatList("Project 1")!).getByRole("button", { name: "New chat" }));
    await click(screen.getByRole("button", { name: "Rename Chat 4" }));
    await renameTo("My name");
    send("This message should not rename it");
    expect(chatTitles("Project 1")).toContain("My name");
  });
});

describe("project page new chat", () => {
  it("has a New chat button next to Upload file that opens a fresh chat", async () => {
    await renderApp();
    await click(projectButton("Project 1"));
    const section = screen.getByRole("region", { name: "Files" });
    await click(within(section).getByRole("button", { name: "New chat" }));
    expect(chatTitles("Project 1")).toEqual(["New chat", "Chat 1", "Chat 2", "Chat 3"]);
    expect(screen.getByText(/Welcome to/)).toBeTruthy();
    expect(input()).toBeTruthy();
  });
});

describe("files in a chat", () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:mock-1");
    URL.revokeObjectURL = vi.fn();
  });

  async function drop(files: File[]) {
    const page = document.querySelector("main.page")!;
    await act(async () => {
      fireEvent.dragEnter(page, { dataTransfer: { types: ["Files"], files } });
    });
    expect(screen.getByText(/Drop files to add them to Project 1/)).toBeTruthy();
    await act(async () => {
      fireEvent.drop(page, { dataTransfer: { types: ["Files"], files } });
    });
  }

  it("dropping files attaches them to the next message and adds them to the project", async () => {
    await renderApp();
    await openChat("Project 1", "Chat 1");
    await drop([new File(["x"], "my_paper.pdf", { type: "application/pdf" })]);
    expect(screen.queryByText(/Drop files to add/)).toBeNull();
    const chips = screen.getByRole("list", { name: "Attached files" });
    expect(within(chips).getByText("my_paper.pdf")).toBeTruthy();
    send("what does this paper say?");
    expect(api.sendMessage).toHaveBeenCalledWith("p1", "what does this paper say?\n\n📎 Attached: my_paper.pdf");
    expect(screen.queryByRole("list", { name: "Attached files" })).toBeNull();
    await click(projectButton("Project 1"));
    expect(Array.from(document.querySelectorAll(".file-row .file-name")).map((f) => f.textContent)).toContain("my_paper.pdf");
  });

  it("the paperclip attaches files; an attachment can be removed before sending", async () => {
    await renderApp();
    await openChat("Project 1", "Chat 1");
    const picker = screen.getByLabelText("Choose files to attach") as HTMLInputElement;
    await act(async () => {
      fireEvent.change(picker, { target: { files: [new File(["a"], "a.csv"), new File(["b"], "b.csv")] } });
    });
    await click(screen.getByRole("button", { name: "Remove a.csv" }));
    send("");
    expect(api.sendMessage).toHaveBeenCalledWith("p1", "📎 Attached: b.csv");
  });

  it("the Files button opens a panel next to the chat with papers, charts, figures and code", async () => {
    await renderApp();
    await openChat("Project 1", "Chat 1");
    await click(screen.getByRole("button", { name: "Show project files" }));
    const panel = screen.getByRole("complementary", { name: "Project files" });
    const groups = within(panel).getAllByRole("region").map((g) => g.getAttribute("aria-label"));
    expect(groups).toEqual(["Papers & reports", "Charts", "Figures", "Code", "Tables", "Data"]);
    expect(input()).toBeTruthy(); // the chat stays usable

    await click(within(panel).getByRole("button", { name: /ifn_alpha_cd14_monocytes\.ipynb/ }));
    expect(screen.getByRole("complementary", { name: "Preview of ifn_alpha_cd14_monocytes.ipynb" })).toBeTruthy();
    await click(screen.getByRole("button", { name: "Back to files" }));

    const charts = within(screen.getByRole("complementary", { name: "Project files" })).getByRole("region", { name: "Charts" });
    await click(within(charts).getAllByRole("button")[0]);
    expect(screen.getByRole("img", { name: /Volcano plot/ })).toBeTruthy();

    await click(screen.getByRole("button", { name: "Close preview" }));
    expect(screen.queryByRole("complementary", { name: /^(Preview of|Project files|Chart:)/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Show project files" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("the Files button only appears in a chat and the panel closes when leaving it", async () => {
    await renderApp();
    expect(screen.queryByRole("button", { name: "Show project files" })).toBeNull();
    await openChat("Project 1", "Chat 1");
    await click(screen.getByRole("button", { name: "Show project files" }));
    await click(projectButton("Project 1"));
    expect(screen.queryByRole("complementary", { name: "Project files" })).toBeNull();
    expect(screen.queryByRole("button", { name: /project files/ })).toBeNull();
  });
});
