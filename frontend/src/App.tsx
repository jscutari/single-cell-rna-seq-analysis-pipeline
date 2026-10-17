import { useCallback, useEffect, useRef, useState } from "react";
import {
  USE_MOCK,
  createProject,
  listChats,
  listFiles,
  listFindings,
  listProjects,
  mainChat,
  sendMessage,
  startRun,
  stopRun,
} from "./api/client";
import { useProjectStream } from "./api/useProjectStream";
import { fileKind } from "./lib/files";
import { newId } from "./lib/ids";
import { ChatView } from "./components/ChatView/ChatView";
import { Composer } from "./components/Composer/Composer";
import { FilePreview } from "./components/FilePreview/FilePreview";
import { Page } from "./components/Page/Page";
import { ProjectView } from "./components/ProjectView/ProjectView";
import { Sidebar } from "./components/Sidebar/Sidebar";
import { SpiralBinding } from "./components/SpiralBinding";
import { WelcomeView } from "./components/WelcomeCard/WelcomeView";
import { Workbook } from "./components/Workbook";
import type { ChatMessage, ProjectSummary } from "./types/schemas";
import type { Chat, FindingCard, ProjectFile, RunInfo, StreamEvent, View } from "./types/ui";

/** Give up waiting for a reply after this long, so the typing dots don't spin forever. */
const REPLY_TIMEOUT_MS = 60_000;
/** Coalesce bursts of result events into one refresh of files and findings. */
const REFRESH_DELAY_MS = 400;
const FINAL_STAGE_STATUS: Record<string, RunInfo["status"]> = { report: "done", stopped: "stopped", failed: "failed" };

type Timer = ReturnType<typeof setTimeout>;

export default function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [view, setView] = useState<View>({ kind: "home" });
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(null);
  const [chatsByProject, setChatsByProject] = useState<Record<string, Chat[]>>({});
  const [messagesByChat, setMessagesByChat] = useState<Record<string, ChatMessage[]>>({});
  const [filesByProject, setFilesByProject] = useState<Record<string, ProjectFile[]>>({});
  const [findingsByProject, setFindingsByProject] = useState<Record<string, FindingCard[]>>({});
  const [previewFileId, setPreviewFileId] = useState<string | null>(null);
  /** Messages sent per chat that are still waiting for a reply. */
  const [pendingCount, setPendingCount] = useState<Record<string, number>>({});
  const [runByProject, setRunByProject] = useState<Record<string, RunInfo>>({});
  const [runError, setRunError] = useState<Record<string, string | undefined>>({});
  /** Last event id in each project's /state snapshot; the stream continues from it. */
  const [lastEventId, setLastEventId] = useState<Record<string, number>>({});

  // Synchronous bookkeeping that must not wait for a re-render.
  const seenMessageIds = useRef(new Set<string>()); // drops SSE replays / history overlap
  // Per project, in send order: which chat is waiting. Replies carry only project_id
  // (the contract has no chat_id yet), so the oldest waiting chat gets the next reply.
  const waiting = useRef(new Map<string, { chatId: string; timer: Timer }[]>());
  const chatsRequested = useRef(new Set<string>());
  const projectDataRequested = useRef(new Set<string>());
  const chatsRef = useRef<Record<string, Chat[]>>({});
  const takenNames = useRef(new Set<string>());
  const refreshTimers = useRef(new Map<string, Timer>());

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
    const refreshes = refreshTimers.current;
    return () => {
      all.forEach((list) => list.forEach((w) => clearTimeout(w.timer)));
      refreshes.forEach(clearTimeout);
    };
  }, []);

  // The preview belongs to a project page; leaving the page closes it.
  const viewKey = view.kind === "project" ? view.projectId : view.kind;
  useEffect(() => setPreviewFileId(null), [viewKey]);

  // Uploaded files are held as object URLs; release them when the app goes away.
  const objectUrls = useRef<string[]>([]);
  useEffect(() => {
    const urls = objectUrls.current;
    return () => urls.forEach((url) => URL.revokeObjectURL(url));
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
      .then(({ chats, messages, run, lastEventId: last }) => {
        if (run) setRunByProject((all) => ({ ...all, [projectId]: run }));
        if (last !== undefined) setLastEventId((all) => ({ ...all, [projectId]: last }));
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

  /** Loads a project's files and findings (local uploads are kept). */
  const loadProjectData = (projectId: string) =>
    Promise.all([listFiles(projectId), listFindings(projectId)]).then(([files, findings]) => {
      setFilesByProject((all) => {
        const local = (all[projectId] ?? []).filter((f) => f.url?.startsWith("blob:"));
        return { ...all, [projectId]: [...local, ...files] };
      });
      setFindingsByProject((all) => ({ ...all, [projectId]: findings }));
    });

  /** Loads a project's files and findings the first time its page is opened. */
  const ensureProjectData = (projectId: string) => {
    if (projectDataRequested.current.has(projectId)) return;
    projectDataRequested.current.add(projectId);
    loadProjectData(projectId)
      .catch((error) => {
        projectDataRequested.current.delete(projectId);
        console.error("Could not load project files and findings", error);
      });
  };

  /** Adds local files to a project (kept in memory until the backend accepts uploads). */
  const uploadFiles = (projectId: string, picked: File[]) => {
    const added: ProjectFile[] = picked.map((file) => {
      const url = URL.createObjectURL(file);
      objectUrls.current.push(url);
      return {
        id: newId(),
        project_id: projectId,
        name: file.name,
        kind: fileKind(file.name),
        size_bytes: file.size,
        url,
        added_at: new Date().toISOString(),
      };
    });
    setFilesByProject((all) => ({ ...all, [projectId]: [...added, ...(all[projectId] ?? [])] }));
    setPreviewFileId(added[0].id);
  };

  /** Re-reads files and findings after new results (only for projects already loaded). */
  const scheduleRefresh = (projectId: string) => {
    if (!projectDataRequested.current.has(projectId) || refreshTimers.current.has(projectId)) return;
    refreshTimers.current.set(
      projectId,
      setTimeout(() => {
        refreshTimers.current.delete(projectId);
        loadProjectData(projectId).catch((error) => console.error("Could not refresh project results", error));
      }, REFRESH_DELAY_MS),
    );
  };

  const setRun = (projectId: string, update: Partial<RunInfo>) =>
    setRunByProject((all) => ({ ...all, [projectId]: { ...(all[projectId] ?? { status: "idle", stage: null }), ...update } }));

  const handleRun = (projectId: string, action: "start" | "stop") => {
    setRunError((all) => ({ ...all, [projectId]: undefined }));
    (action === "start" ? startRun(projectId) : stopRun(projectId))
      .then((status) => setRun(projectId, action === "start" ? { status, stage: null } : { status }))
      .catch((error: Error) => setRunError((all) => ({ ...all, [projectId]: error.message })));
  };

  /** A note from the app (not the agents) shown in a chat, e.g. why a message wasn't taken. */
  const addNotice = (projectId: string, chatId: string, text: string) =>
    addMessages(chatId, [{ id: newId(), project_id: projectId, role: "assistant", content: `⚠️ ${text}`, created_at: new Date().toISOString() }]);

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

  /** Creates "Chat N" in a project and opens it (with the real backend: opens its one chat). */
  const newChat = (projectId: string): string => {
    ensureChats(projectId);
    if (!USE_MOCK) {
      const chat = mainChat(projectId);
      setChats(projectId, (chats) => (chats.some((c) => c.id === chat.id) ? chats : [chat, ...chats]));
      openChat(projectId, chat.id);
      return chat.id;
    }
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
    const id = newId();
    addMessages(chatId, [{ id, project_id: projectId, role: "user", content: text, created_at: new Date().toISOString() }]);
    const timer = startWaiting(projectId, chatId);
    sendMessage(projectId, text, id).catch((error: Error & { status?: number }) => {
      // A refusal the user can act on (e.g. 409 "start a new run") is shown in the chat, not an app error.
      const refused = error.status !== undefined && error.status < 500;
      (refused ? console.warn : console.error)("Could not send message", error);
      stopWaiting(projectId, timer);
      addNotice(projectId, chatId, error.message);
    });
  };

  const streamProjectId = view.kind === "home" ? expandedProjectId : view.projectId;
  /** Where an incoming message for a project goes when no chat is waiting for it. */
  const defaultChat = (projectId: string): string | undefined =>
    (view.kind === "chat" && view.projectId === projectId ? view.chatId : undefined) ??
    chatsRef.current[projectId]?.[0]?.id ??
    (USE_MOCK ? undefined : mainChat(projectId).id);

  const onStreamEvent = (event: StreamEvent) => {
    const projectId = event.project_id;
    switch (event.type) {
      case "chat_reply": {
        const chatId = waiting.current.get(projectId)?.[0]?.chatId ?? defaultChat(projectId);
        if (!chatId) return;
        if (!USE_MOCK && !chatsRef.current[projectId]?.length) setChats(projectId, () => [mainChat(projectId)]);
        if (addMessages(chatId, [event.payload]) && waiting.current.get(projectId)?.length) stopWaiting(projectId);
        return;
      }
      case "user_message": {
        // Sent from another tab (our own messages are already shown, same id).
        const chatId = defaultChat(projectId);
        if (chatId) addMessages(chatId, [event.payload]);
        return;
      }
      case "run_status":
        setRun(projectId, { status: event.payload.status });
        return;
      case "stage_done": {
        const final = FINAL_STAGE_STATUS[event.payload.stage];
        setRun(projectId, final ? { stage: event.payload.stage, status: final } : { stage: event.payload.stage });
        scheduleRefresh(projectId);
        return;
      }
      case "finding":
      case "hypothesis_status":
        scheduleRefresh(projectId);
        return;
    }
  };
  useProjectStream(streamProjectId, onStreamEvent, streamProjectId ? lastEventId[streamProjectId] : undefined);

  const closePreview = useCallback(() => setPreviewFileId(null), []);

  const project = view.kind === "home" ? undefined : projects.find((p) => p.id === view.projectId);
  const messages = view.kind === "chat" ? (messagesByChat[view.chatId] ?? []) : [];
  const awaitingReply = view.kind === "chat" && (pendingCount[view.chatId] ?? 0) > 0;
  const composer = <Composer onSend={handleSend} onAttach={() => console.info("[mock] attach dataset")} />;

  let content;
  let panel;
  if (view.kind === "project" && project) {
    const files = filesByProject[project.id] ?? [];
    const previewFile = files.find((f) => f.id === previewFileId);
    content = (
      <ProjectView
        project={project}
        files={files}
        findings={findingsByProject[project.id] ?? []}
        activeFileId={previewFile?.id ?? null}
        onOpenFile={(file) => setPreviewFileId((current) => (current === file.id ? null : file.id))}
        onUpload={(picked) => uploadFiles(project.id, picked)}
        run={USE_MOCK ? undefined : (runByProject[project.id] ?? { status: "idle", stage: null })}
        runError={runError[project.id]}
        onStartRun={() => handleRun(project.id, "start")}
        onStopRun={() => handleRun(project.id, "stop")}
      />
    );
    panel = previewFile && <FilePreview file={previewFile} onClose={closePreview} />;
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
        allowNewChat={USE_MOCK}
      />
      <SpiralBinding />
      <Page view={content} composer={view.kind === "project" ? undefined : composer} panel={panel} />
    </Workbook>
  );
}

function nextProjectName(taken: Set<string>): string {
  let n = 1;
  while (taken.has(`Project ${n}`)) n++;
  return `Project ${n}`;
}
