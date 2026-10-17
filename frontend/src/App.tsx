import { useEffect, useRef, useState } from "react";
import { createProject, listChats, listFiles, listFindings, listProjects, sendMessage } from "./api/client";
import { useProjectStream } from "./api/useProjectStream";
import { newId } from "./lib/ids";
import { ChatView } from "./components/ChatView/ChatView";
import { Composer } from "./components/Composer/Composer";
import { Page } from "./components/Page/Page";
import { ProjectView } from "./components/ProjectView/ProjectView";
import { Sidebar } from "./components/Sidebar/Sidebar";
import { SpiralBinding } from "./components/SpiralBinding";
import { WelcomeView } from "./components/WelcomeCard/WelcomeView";
import { Workbook } from "./components/Workbook";
import type { ScrapEvent } from "./types/events";
import type { ChatMessage, ProjectSummary } from "./types/schemas";
import type { Chat, FindingCard, ProjectFile, View } from "./types/ui";

/** Give up waiting for a reply after this long, so the typing dots don't spin forever. */
const REPLY_TIMEOUT_MS = 60_000;

type Timer = ReturnType<typeof setTimeout>;

export default function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [view, setView] = useState<View>({ kind: "home" });
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(null);
  const [chatsByProject, setChatsByProject] = useState<Record<string, Chat[]>>({});
  const [messagesByChat, setMessagesByChat] = useState<Record<string, ChatMessage[]>>({});
  const [filesByProject, setFilesByProject] = useState<Record<string, ProjectFile[]>>({});
  const [findingsByProject, setFindingsByProject] = useState<Record<string, FindingCard[]>>({});
  /** Messages sent per chat that are still waiting for a reply. */
  const [pendingCount, setPendingCount] = useState<Record<string, number>>({});

  // Synchronous bookkeeping that must not wait for a re-render.
  const seenMessageIds = useRef(new Set<string>()); // drops SSE replays / history overlap
  // Per project, in send order: which chat is waiting. Replies carry only project_id
  // (the contract has no chat_id yet), so the oldest waiting chat gets the next reply.
  const waiting = useRef(new Map<string, { chatId: string; timer: Timer }[]>());
  const chatsRequested = useRef(new Set<string>());
  const projectDataRequested = useRef(new Set<string>());
  const chatsRef = useRef<Record<string, Chat[]>>({});
  const takenNames = useRef(new Set<string>());

  useEffect(() => {
    listProjects()
      .then((list) => {
        list.forEach((p) => takenNames.current.add(p.name));
        setProjects(list);
      })
      .catch((error) => console.error("Could not load projects", error));
  }, []);

  useEffect(() => {
    const all = waiting.current;
    return () => all.forEach((list) => list.forEach((w) => clearTimeout(w.timer)));
  }, []);

  const setChats = (projectId: string, update: (chats: Chat[]) => Chat[]) => {
    const next = update(chatsRef.current[projectId] ?? []);
    chatsRef.current = { ...chatsRef.current, [projectId]: next };
    setChatsByProject(chatsRef.current);
  };

  /** Adds messages to a chat, skipping ids already shown. Returns how many were new. */
  const addMessages = (chatId: string, incoming: ChatMessage[], position: "append" | "prepend" = "append") => {
    const fresh = incoming.filter((m) => !seenMessageIds.current.has(m.id));
    fresh.forEach((m) => seenMessageIds.current.add(m.id));
    if (!fresh.length) return 0;
    setMessagesByChat((all) => {
      const list = all[chatId] ?? [];
      return { ...all, [chatId]: position === "append" ? [...list, ...fresh] : [...fresh, ...list] };
    });
    return fresh.length;
  };

  /** Loads a project's chats (and their saved messages) the first time it is opened. */
  const ensureChats = (projectId: string) => {
    if (chatsRequested.current.has(projectId)) return;
    chatsRequested.current.add(projectId);
    listChats(projectId)
      .then(({ chats, messages }) => {
        setChats(projectId, (local) => {
          // Chats created before the saved ones arrived go after them, renumbered.
          const extra = local.filter((c) => !chats.some((x) => x.id === c.id));
          return [...chats, ...extra.map((c, i) => ({ ...c, title: `Chat ${chats.length + i + 1}` }))];
        });
        for (const [chatId, history] of Object.entries(messages)) addMessages(chatId, history, "prepend");
      })
      .catch((error) => {
        chatsRequested.current.delete(projectId); // retry next time it is opened
        console.error("Could not load chats", error);
      });
  };

  /** Loads a project's files and findings the first time its page is opened. */
  const ensureProjectData = (projectId: string) => {
    if (projectDataRequested.current.has(projectId)) return;
    projectDataRequested.current.add(projectId);
    Promise.all([listFiles(projectId), listFindings(projectId)])
      .then(([files, findings]) => {
        setFilesByProject((all) => ({ ...all, [projectId]: [...files, ...(all[projectId] ?? [])] }));
        setFindingsByProject((all) => ({ ...all, [projectId]: findings }));
      })
      .catch((error) => {
        projectDataRequested.current.delete(projectId);
        console.error("Could not load project files and findings", error);
      });
  };

  const changePending = (chatId: string, delta: number) =>
    setPendingCount((all) => ({ ...all, [chatId]: Math.max(0, (all[chatId] ?? 0) + delta) }));

  const startWaiting = (projectId: string, chatId: string) => {
    const timer = setTimeout(() => {
      stopWaiting(projectId, timer);
      console.warn(`No reply in ${chatId} after ${REPLY_TIMEOUT_MS / 1000}s`);
    }, REPLY_TIMEOUT_MS);
    waiting.current.set(projectId, [...(waiting.current.get(projectId) ?? []), { chatId, timer }]);
    changePending(chatId, 1);
    return timer;
  };

  /** Stops one wait (a specific timer, or the oldest when a reply arrives); returns its chat. */
  const stopWaiting = (projectId: string, timer?: Timer): string | undefined => {
    const list = waiting.current.get(projectId) ?? [];
    const entry = timer === undefined ? list[0] : list.find((w) => w.timer === timer);
    if (!entry) return undefined;
    clearTimeout(entry.timer);
    waiting.current.set(projectId, list.filter((w) => w !== entry));
    changePending(entry.chatId, -1);
    return entry.chatId;
  };

  const openProject = (projectId: string) => {
    ensureChats(projectId);
    ensureProjectData(projectId);
    if (view.kind === "project" && view.projectId === projectId) {
      setExpandedProjectId((current) => (current === projectId ? null : projectId));
      return;
    }
    setView({ kind: "project", projectId });
    setExpandedProjectId(projectId);
  };

  const openChat = (projectId: string, chatId: string) => {
    setView({ kind: "chat", projectId, chatId });
    setExpandedProjectId(projectId);
  };

  /** Creates "Chat N" in a project and opens it. */
  const newChat = (projectId: string): string => {
    ensureChats(projectId);
    const chat: Chat = {
      id: newId(),
      project_id: projectId,
      title: `Chat ${(chatsRef.current[projectId]?.length ?? 0) + 1}`,
      created_at: new Date().toISOString(),
    };
    setChats(projectId, (chats) => [...chats, chat]);
    openChat(projectId, chat.id);
    return chat.id;
  };

  const handleNewProject = async () => {
    const name = nextProjectName(takenNames.current);
    takenNames.current.add(name); // reserve now so a quick second click gets the next number
    try {
      const project = await createProject(name);
      chatsRequested.current.add(project.id); // brand new: nothing to load
      projectDataRequested.current.add(project.id);
      setChats(project.id, () => []);
      setProjects((list) => [project, ...list]);
      setView({ kind: "project", projectId: project.id });
      setExpandedProjectId(project.id);
    } catch (error) {
      takenNames.current.delete(name);
      console.error("Could not create project", error);
    }
  };

  const handleSend = (text: string) => {
    let projectId: string;
    let chatId: string;
    if (view.kind === "chat") {
      ({ projectId, chatId } = view);
    } else {
      // From the start screen: start a new chat in the most recent project.
      if (!projects.length) return false; // projects not loaded yet: keep the text in the box
      if (!text) return;
      projectId = projects[0].id;
      chatId = newChat(projectId);
    }
    if (!text) return;
    addMessages(chatId, [{ id: newId(), project_id: projectId, role: "user", content: text, created_at: new Date().toISOString() }]);
    const timer = startWaiting(projectId, chatId);
    sendMessage(projectId, text).catch((error) => {
      console.error("Could not send message", error);
      stopWaiting(projectId, timer);
    });
  };

  const streamProjectId = view.kind === "home" ? expandedProjectId : view.projectId;
  useProjectStream(streamProjectId, (event: ScrapEvent) => {
    if (event.type !== "chat_reply") return;
    const projectId = event.project_id;
    const chatId =
      (waiting.current.get(projectId)?.[0]?.chatId) ??
      (view.kind === "chat" && view.projectId === projectId ? view.chatId : undefined) ??
      chatsRef.current[projectId]?.[0]?.id;
    if (!chatId) return;
    if (addMessages(chatId, [event.payload]) && waiting.current.get(projectId)?.length) stopWaiting(projectId);
  });

  const project = view.kind === "home" ? undefined : projects.find((p) => p.id === view.projectId);
  const messages = view.kind === "chat" ? (messagesByChat[view.chatId] ?? []) : [];
  const awaitingReply = view.kind === "chat" && (pendingCount[view.chatId] ?? 0) > 0;
  const composer = <Composer onSend={handleSend} onAttach={() => console.info("[mock] attach dataset")} />;

  let content;
  if (view.kind === "project" && project) {
    content = (
      <ProjectView project={project} files={filesByProject[project.id] ?? []} findings={findingsByProject[project.id] ?? []} />
    );
  } else if (view.kind === "chat" && (messages.length || awaitingReply)) {
    content = <ChatView messages={messages} awaitingReply={awaitingReply} />;
  } else {
    content = <WelcomeView />;
  }

  return (
    <Workbook>
      <Sidebar
        projects={projects}
        chatsByProject={chatsByProject}
        view={view}
        expandedProjectId={expandedProjectId}
        onSelectProject={openProject}
        onSelectChat={openChat}
        onNewChat={newChat}
        onNewProject={handleNewProject}
      />
      <SpiralBinding />
      <Page view={content} composer={view.kind === "project" ? undefined : composer} />
    </Workbook>
  );
}

function nextProjectName(taken: Set<string>): string {
  let n = 1;
  while (taken.has(`Project ${n}`)) n++;
  return `Project ${n}`;
}
