import { useCallback, useEffect, useRef, useState } from "react";
import {
  USE_MOCK,
  createProject,
  listChats,
  listFiles,
  listFindings,
  getOverview,
  listProjects,
  mainChat,
  sendMessage,
  startRun,
  stopRun,
  uploadDataset,
} from "./api/client";
import { useProjectStream } from "./api/useProjectStream";
import { chatTitle } from "./lib/chatTitle";
import { fileKind } from "./lib/files";
import { formatBytes } from "./lib/format";
import { newId } from "./lib/ids";
import { ChatView } from "./components/ChatView/ChatView";
import { Composer, type Attachment } from "./components/Composer/Composer";
import { ProjectChip } from "./components/Composer/ProjectChip";
import { FilePreview } from "./components/FilePreview/FilePreview";
import { FilesPanel, type PanelItem } from "./components/FilesPanel/FilesPanel";
import { Page } from "./components/Page/Page";
import { ProjectView } from "./components/ProjectView/ProjectView";
import { Sidebar } from "./components/Sidebar/Sidebar";
import { SpiralBinding } from "./components/SpiralBinding";
import { WelcomeView } from "./components/WelcomeCard/WelcomeView";
import { Workbook } from "./components/Workbook";
import type { ChatMessage, ProjectSummary } from "./types/schemas";
import type { Chat, FindingCard, ProjectFile, RunInfo, StreamEvent, View, ProjectOverview } from "./types/ui";

/** Give up waiting for a reply after this long, so the typing dots don't spin forever. */
const REPLY_TIMEOUT_MS = 60_000;
/** Coalesce bursts of result events into one refresh of files and findings. */
const REFRESH_DELAY_MS = 400;
const FINAL_STAGE_STATUS: Record<string, RunInfo["status"]> = { report: "done", stopped: "stopped", failed: "failed" };

type Timer = ReturnType<typeof setTimeout>;

const SIDEBAR_KEY = "scrap.sidebarCollapsed";
const LAST_PROJECT_KEY = "scrap.lastProjectId";

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function store(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: fine for this session */
  }
}
// The backend keeps one conversation per project. Extra chats live in this browser:
// their list per project, and which chat each message went to (default: the project's main chat).
const CHATS_KEY = "scrap.chats";
const CHAT_OF_KEY = "scrap.chatOfMessage";
function readJson<T>(key: string): Partial<Record<string, T>> {
  try {
    return JSON.parse(localStorage.getItem(key) ?? "{}") ?? {};
  } catch {
    return {};
  }
}
function storeJson(key: string, value: unknown) {
  store(key, JSON.stringify(value));
}

function readSidebarCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === "1";
  } catch {
    return false;
  }
}

export default function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [view, setView] = useState<View>({ kind: "home" });
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(null);
  const [chatsByProject, setChatsByProject] = useState<Record<string, Chat[]>>({});
  const [messagesByChat, setMessagesByChat] = useState<Record<string, ChatMessage[]>>({});
  const [filesByProject, setFilesByProject] = useState<Record<string, ProjectFile[]>>({});
  const [findingsByProject, setFindingsByProject] = useState<Record<string, FindingCard[]>>({});
  const [overviewByProject, setOverviewByProject] = useState<Record<string, ProjectOverview | null>>({});
  const [previewFileId, setPreviewFileId] = useState<string | null>(null);
  /** Messages sent per chat that are still waiting for a reply. */
  const [pendingCount, setPendingCount] = useState<Record<string, number>>({});
  const [runByProject, setRunByProject] = useState<Record<string, RunInfo>>({});
  const [runError, setRunError] = useState<Record<string, string | undefined>>({});
  /** Last event id in each project's /state snapshot; the stream continues from it. */
  const [lastEventId, setLastEventId] = useState<Record<string, number>>({});
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsed);
  /** Files panel next to the chat, and what it shows (the list, a file, or a chart). */
  const [filesPanelOpen, setFilesPanelOpen] = useState(false);
  const [panelItem, setPanelItem] = useState<PanelItem>(null);
  /** Files attached in a chat, waiting to go out with the next message. */
  const [attachmentsByChat, setAttachmentsByChat] = useState<Record<string, Attachment[]>>({});
  /** The project you last worked in (remembered across visits); the start screen's default target. */
  const [lastProjectId, setLastProjectId] = useState<string | null>(() => readStored(LAST_PROJECT_KEY));
  /** Project picked in the start screen's chip; null means "use the default". */
  const [homeProjectId, setHomeProjectId] = useState<string | null>(null);
  /** Bumped by the logo to give the start screen a fresh composer. */
  const [homeResets, setHomeResets] = useState(0);

  // Synchronous bookkeeping that must not wait for a re-render.
  const seenMessageIds = useRef(new Set<string>()); // drops SSE replays / history overlap
  // Per project, in send order: which chat is waiting. Replies carry only project_id
  // (the contract has no chat_id yet), so the oldest waiting chat gets the next reply.
  const waiting = useRef(new Map<string, { chatId: string; timer: Timer }[]>());
  const chatsRequested = useRef(new Set<string>());
  /** Dataset uploads in flight per project; a message waits for them so the run sees the new data. */
  const pendingUploads = useRef(new Map<string, Promise<void>[]>());
  /** Projects whose saved chats are loaded (until then, don't overwrite what this browser saved). */
  const chatsLoaded = useRef(new Set<string>());
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
  // The files panel lives next to a chat; leaving the chat view closes it.
  useEffect(() => {
    if (view.kind !== "chat") setFilesPanelOpen(false);
  }, [view.kind]);

  const markUsed = (projectId: string) => {
    setLastProjectId(projectId);
    store(LAST_PROJECT_KEY, projectId);
  };

  /** Where a chat started from the start screen goes: the chip's pick, else the last-used project, else the newest. */
  const homeTargetId =
    [homeProjectId, lastProjectId].find((id) => id && projects.some((p) => p.id === id)) ?? projects[0]?.id ?? null;

  /** Logo: back to the start screen, as when the app opens. Projects and chats are kept. */
  const goHome = () => {
    setView({ kind: "home" });
    setExpandedProjectId(null);
    setFilesPanelOpen(false);
    setPanelItem(null);
    setPreviewFileId(null);
    setHomeProjectId(null);
    setHomeResets((n) => n + 1);
  };

  const toggleSidebar = () =>
    setSidebarCollapsed((collapsed) => {
      try {
        localStorage.setItem(SIDEBAR_KEY, collapsed ? "0" : "1");
      } catch {
        /* private mode etc.: the toggle still works for this session */
      }
      return !collapsed;
    });

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
    if (!USE_MOCK && chatsLoaded.current.has(projectId)) {
      const main = mainChat(projectId).id;
      storeJson(CHATS_KEY, { ...readJson<Chat[]>(CHATS_KEY), [projectId]: next.filter((c) => c.id !== main) });
    }
  };

  /** Adds messages to a chat, skipping ids already shown. Returns how many were new. */
  const addMessages = (chatId: string, incoming: ChatMessage[], position: "append" | "prepend" = "append") => {
    const fresh = incoming.filter((m) => !seenMessageIds.current.has(m.id));
    fresh.forEach((m) => seenMessageIds.current.add(m.id));
    if (!fresh.length) return 0;
    if (!USE_MOCK && chatId !== mainChat(fresh[0].project_id).id) {
      const chatOf = readJson<string>(CHAT_OF_KEY);
      fresh.forEach((m) => (chatOf[m.id] = chatId));
      storeJson(CHAT_OF_KEY, chatOf);
    }
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
      .then(({ chats: loaded, messages: loadedMessages, run, lastEventId: last }) => {
        if (run) setRunByProject((all) => ({ ...all, [projectId]: run }));
        if (last !== undefined) setLastEventId((all) => ({ ...all, [projectId]: last }));
        let chats = loaded;
        let messages = loadedMessages;
        if (!USE_MOCK) {
          // Put back the chats made in this browser, and each saved message in its chat.
          chats = [...loaded, ...(readJson<Chat[]>(CHATS_KEY)[projectId] ?? [])];
          const chatOf = readJson<string>(CHAT_OF_KEY);
          const known = new Set(chats.map((c) => c.id));
          messages = {};
          for (const [chatId, history] of Object.entries(loadedMessages))
            for (const m of history) {
              const target = chatOf[m.id] && known.has(chatOf[m.id]!) ? chatOf[m.id]! : chatId;
              (messages[target] ??= []).push(m);
            }
          chatsLoaded.current.add(projectId);
        }
        setChats(projectId, (local) => {
          // Chats created before the saved ones arrived go after them; numbered ones are renumbered.
          const extra = local.filter((c) => !chats.some((x) => x.id === c.id));
          return [
            ...chats,
            ...extra.map((c, i) =>
              c.title_source === "auto" || c.title_source === "user" ? c : { ...c, title: `Chat ${chats.length + i + 1}` },
            ),
          ];
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
    Promise.all([listFiles(projectId), listFindings(projectId), getOverview(projectId)]).then(([files, findings, overview]) => {
      setOverviewByProject((all) => ({ ...all, [projectId]: overview }));
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
  const uploadFiles = (
    projectId: string,
    picked: File[],
    preview = true,
    onDataset?: (error?: Error) => void,
  ): ProjectFile[] => {
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
    if (preview) setPreviewFileId(added[0].id);
    added.forEach((f, i) => {
      if (f.kind === "h5ad" && !USE_MOCK) sendDataset(projectId, f, picked[i], onDataset);
    });
    return added;
  };

  const setFileSummary = (projectId: string, fileId: string, summary: string) =>
    setFilesByProject((all) => ({
      ...all,
      [projectId]: (all[projectId] ?? []).map((f) => (f.id === fileId ? { ...f, summary } : f)),
    }));

  /** Sends an .h5ad to the backend as the project's dataset. Messages wait for it (see handleSend). */
  const sendDataset = (projectId: string, file: ProjectFile, raw: File, onDone?: (error?: Error) => void) => {
    setFileSummary(projectId, file.id, "Uploading dataset…");
    const upload = uploadDataset(projectId, raw).then(
      () => {
        setFileSummary(projectId, file.id, "Dataset · the next run analyzes this file");
        onDone?.();
      },
      (error: Error) => {
        console.error("Could not upload dataset", error);
        setFileSummary(projectId, file.id, `Upload failed: ${error.message}`);
        onDone?.(error);
      },
    );
    pendingUploads.current.set(projectId, [...(pendingUploads.current.get(projectId) ?? []), upload]);
    upload.finally(() =>
      pendingUploads.current.set(projectId, (pendingUploads.current.get(projectId) ?? []).filter((u) => u !== upload)),
    );
  };

  /** Files dropped or picked in a chat: added to the project and attached to the next message. */
  const attachFiles = (projectId: string, chatId: string, picked: File[]) => {
    const datasets = picked.filter((f) => fileKind(f.name) === "h5ad" && !USE_MOCK);
    const status = (text: string) =>
      addMessages(chatId, [{ id: newId(), project_id: projectId, role: "assistant", content: text, created_at: new Date().toISOString() }]);
    datasets.forEach((f) => status(`Uploading dataset ${f.name} (${formatBytes(f.size)})…`));
    const added = uploadFiles(projectId, picked, false, (error) =>
      status(
        error
          ? `⚠️ The dataset upload failed: ${error.message}`
          : "✅ Dataset uploaded. Tell me what you'd like to learn from it, or press Start run on the project page.",
      ),
    );
    setAttachmentsByChat((all) => ({
      ...all,
      [chatId]: [...(all[chatId] ?? []), ...added.map((f) => ({ id: f.id, name: f.name }))],
    }));
  };

  const renameChat = (projectId: string, chatId: string, title: string) =>
    setChats(projectId, (chats) => chats.map((c) => (c.id === chatId ? { ...c, title, title_source: "user" } : c)));

  const toggleFilesPanel = (projectId: string) => {
    if (!filesPanelOpen) ensureProjectData(projectId);
    setPanelItem(null);
    setFilesPanelOpen((open) => !open);
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
    const uploads = action === "start" ? (pendingUploads.current.get(projectId) ?? []) : [];
    const act = () => (action === "start" ? startRun(projectId) : stopRun(projectId));
    (uploads.length ? Promise.allSettled(uploads).then(act) : act())
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
    markUsed(projectId);
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
    markUsed(projectId);
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
      title_source: "default",
    };
    setChats(projectId, (chats) => [...chats, chat]);
    openChat(projectId, chat.id);
    return chat.id;
  };

  /** Creates "Project N"; returns it, or undefined if the backend refused. */
  const addProject = async (): Promise<ProjectSummary | undefined> => {
    const name = nextProjectName(takenNames.current);
    takenNames.current.add(name); // reserve now so a quick second click gets the next number
    try {
      const project = await createProject(name);
      chatsRequested.current.add(project.id); // brand new: nothing to load
      chatsLoaded.current.add(project.id);
      projectDataRequested.current.add(project.id);
      setChats(project.id, () => []);
      setProjects((list) => [project, ...list]);
      return project;
    } catch (error) {
      takenNames.current.delete(name);
      console.error("Could not create project", error);
      return undefined;
    }
  };

  const handleNewProject = async () => {
    const project = await addProject();
    if (!project) return;
    markUsed(project.id);
    setView({ kind: "project", projectId: project.id });
    setExpandedProjectId(project.id);
  };

  /** "New project" from the start-screen chip: create it and aim the chip at it, staying on the start screen. */
  const newProjectFromChip = async () => {
    const project = await addProject();
    if (project) setHomeProjectId(project.id);
  };

  const handleSend = (text: string) => {
    let projectId: string;
    let chatId: string;
    if (view.kind === "chat") {
      ({ projectId, chatId } = view);
    } else {
      // From the start screen: start a new chat in the project shown in the chip.
      if (!homeTargetId) return false; // projects not loaded yet: keep the text in the box
      if (!text) return;
      projectId = homeTargetId;
      chatId = newChat(projectId);
    }
    // Attached files go out as a line the agents can read; the files are already in the project.
    const attached = attachmentsByChat[chatId] ?? [];
    const content = [text, attached.length ? `📎 Attached: ${attached.map((a) => a.name).join(", ")}` : ""]
      .filter(Boolean)
      .join("\n\n");
    if (!content) return;
    nameChatFromFirstMessage(projectId, chatId, text || attached[0].name);
    if (attached.length) setAttachmentsByChat((all) => ({ ...all, [chatId]: [] }));
    const id = newId();
    addMessages(chatId, [{ id, project_id: projectId, role: "user", content, created_at: new Date().toISOString() }]);
    const timer = startWaiting(projectId, chatId);
    const uploads = pendingUploads.current.get(projectId) ?? [];
    const send = () => sendMessage(projectId, content, id);
    (uploads.length ? Promise.allSettled(uploads).then(send) : send()).catch((error: Error & { status?: number }) => {
      // A refusal the user can act on (e.g. 409 "start a new run") is shown in the chat, not an app error.
      const refused = error.status !== undefined && error.status < 500;
      (refused ? console.warn : console.error)("Could not send message", error);
      stopWaiting(projectId, timer);
      addNotice(projectId, chatId, error.message);
    });
  };

  /** A numbered chat ("Chat 3") gets a title from its first message, unless it already has history. */
  const nameChatFromFirstMessage = (projectId: string, chatId: string, text: string) => {
    const chat = chatsRef.current[projectId]?.find((c) => c.id === chatId);
    const hasUserMessages = (messagesByChat[chatId] ?? []).some((m) => m.role === "user");
    if (!chat || chat.title_source !== "default" || hasUserMessages) return;
    setChats(projectId, (chats) =>
      chats.map((c) => (c.id === chatId ? { ...c, title: chatTitle(text), title_source: "auto" } : c)),
    );
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
  const closeFilesPanel = useCallback(() => setFilesPanelOpen(false), []);

  const project = view.kind === "home" ? undefined : projects.find((p) => p.id === view.projectId);
  const messages = view.kind === "chat" ? (messagesByChat[view.chatId] ?? []) : [];
  const awaitingReply = view.kind === "chat" && (pendingCount[view.chatId] ?? 0) > 0;
  const chatView = view.kind === "chat" ? view : undefined;
  const composer = (
    <Composer
      key={view.kind === "home" ? `home-${homeResets}` : "chat"}
      onSend={handleSend}
      context={
        view.kind === "home" && projects.length > 0 ? (
          <ProjectChip
            projects={projects}
            selectedId={homeTargetId}
            onSelect={setHomeProjectId}
            onNewProject={newProjectFromChip}
          />
        ) : undefined
      }
      onAttach={() => console.info("[mock] attach dataset")}
      onAttachFiles={chatView && ((picked) => attachFiles(chatView.projectId, chatView.chatId, picked))}
      attachments={chatView ? attachmentsByChat[chatView.chatId] : undefined}
      onRemoveAttachment={
        chatView &&
        ((id) =>
          setAttachmentsByChat((all) => ({ ...all, [chatView.chatId]: (all[chatView.chatId] ?? []).filter((a) => a.id !== id) })))
      }
    />
  );

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
        overview={overviewByProject[project.id] ?? null}
        activeFileId={previewFile?.id ?? null}
        onOpenFile={(file) => setPreviewFileId((current) => (current === file.id ? null : file.id))}
        onUpload={(picked) => uploadFiles(project.id, picked)}
        run={USE_MOCK ? undefined : (runByProject[project.id] ?? { status: "idle", stage: null })}
        runError={runError[project.id]}
        onStartRun={() => handleRun(project.id, "start")}
        onStopRun={() => handleRun(project.id, "stop")}
        onNewChat={() => newChat(project.id)}
      />
    );
    panel = previewFile && <FilePreview file={previewFile} onClose={closePreview} />;
  } else if (view.kind === "chat" && (messages.length || awaitingReply)) {
    content = <ChatView messages={messages} awaitingReply={awaitingReply} />;
  } else {
    content = <WelcomeView />;
  }
  if (chatView && project && filesPanelOpen) {
    panel = (
      <FilesPanel
        projectName={project.name}
        files={filesByProject[project.id] ?? []}
        findings={findingsByProject[project.id] ?? []}
        selected={panelItem}
        onSelect={setPanelItem}
        onClose={closeFilesPanel}
      />
    );
  }

  return (
    <Workbook>
      <Sidebar
        projects={projects}
        chatsByProject={chatsByProject}
        view={view}
        expandedProjectId={expandedProjectId}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={toggleSidebar}
        onSelectProject={openProject}
        onSelectChat={openChat}
        onNewChat={newChat}
        onRenameChat={renameChat}
        onNewProject={handleNewProject}
        onHome={goHome}
      />
      <SpiralBinding />
      <Page
        view={content}
        composer={view.kind === "project" ? undefined : composer}
        panel={panel}
        filesOpen={filesPanelOpen}
        onToggleFiles={chatView && (() => toggleFilesPanel(chatView.projectId))}
        onDropFiles={
          view.kind === "project"
            ? (picked) => uploadFiles(view.projectId, picked)
            : chatView && ((picked) => attachFiles(chatView.projectId, chatView.chatId, picked))
        }
        dropTarget={project?.name}
      />
    </Workbook>
  );
}

function nextProjectName(taken: Set<string>): string {
  let n = 1;
  while (taken.has(`Project ${n}`)) n++;
  return `Project ${n}`;
}
