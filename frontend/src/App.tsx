import { useEffect, useRef, useState } from "react";
import { createProject, listMessages, listProjects, sendMessage } from "./api/client";
import { useProjectStream } from "./api/useProjectStream";
import { newId } from "./lib/ids";
import { ChatView } from "./components/ChatView/ChatView";
import { Composer } from "./components/Composer/Composer";
import { Page } from "./components/Page/Page";
import { Sidebar } from "./components/Sidebar/Sidebar";
import { SpiralBinding } from "./components/SpiralBinding";
import { WelcomeView } from "./components/WelcomeCard/WelcomeView";
import { Workbook } from "./components/Workbook";
import type { ScrapEvent } from "./types/events";
import type { ChatMessage, ProjectSummary } from "./types/schemas";

/** Give up waiting for a reply after this long, so the typing dots don't spin forever. */
const REPLY_TIMEOUT_MS = 60_000;

export default function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messagesByProject, setMessagesByProject] = useState<Record<string, ChatMessage[]>>({});
  /** Messages sent per project that are still waiting for a reply. */
  const [pendingCount, setPendingCount] = useState<Record<string, number>>({});

  // Synchronous bookkeeping that must not wait for a re-render.
  const seenMessageIds = useRef(new Set<string>()); // drops SSE replays / history overlap
  const replyTimers = useRef(new Map<string, ReturnType<typeof setTimeout>[]>()); // per project, oldest first
  const historyLoaded = useRef(new Set<string>());
  const takenNames = useRef(new Set<string>());

  useEffect(() => {
    listProjects()
      .then((list) => {
        list.forEach((p) => takenNames.current.add(p.name));
        setProjects(list);
        setSelectedId((current) => current ?? list[0]?.id ?? null);
      })
      .catch((error) => console.error("Could not load projects", error));
  }, []);

  useEffect(() => {
    const timers = replyTimers.current;
    return () => timers.forEach((list) => list.forEach(clearTimeout));
  }, []);

  /** Adds messages to their project, skipping ids already shown. */
  const addMessages = (incoming: ChatMessage[], position: "append" | "prepend" = "append") => {
    const fresh = incoming.filter((m) => !seenMessageIds.current.has(m.id));
    fresh.forEach((m) => seenMessageIds.current.add(m.id));
    if (!fresh.length) return 0;
    setMessagesByProject((all) => {
      const next = { ...all };
      for (const m of fresh) {
        const list = next[m.project_id] ?? [];
        next[m.project_id] = position === "append" ? [...list, m] : [m, ...list];
      }
      return next;
    });
    return fresh.length;
  };

  const changePending = (projectId: string, delta: number) =>
    setPendingCount((all) => ({ ...all, [projectId]: Math.max(0, (all[projectId] ?? 0) + delta) }));

  const startWaiting = (projectId: string) => {
    const timer = setTimeout(() => {
      stopWaiting(projectId, timer);
      console.warn(`No reply for project ${projectId} after ${REPLY_TIMEOUT_MS / 1000}s`);
    }, REPLY_TIMEOUT_MS);
    replyTimers.current.set(projectId, [...(replyTimers.current.get(projectId) ?? []), timer]);
    changePending(projectId, 1);
    return timer;
  };

  /** Stops one wait: a specific timer, or the oldest one when a reply arrives. */
  const stopWaiting = (projectId: string, timer?: ReturnType<typeof setTimeout>) => {
    const timers = replyTimers.current.get(projectId) ?? [];
    const target = timer ?? timers[0];
    if (target === undefined || !timers.includes(target)) return;
    clearTimeout(target);
    replyTimers.current.set(projectId, timers.filter((t) => t !== target));
    changePending(projectId, -1);
  };

  // Load each project's saved conversation the first time it is opened.
  useEffect(() => {
    if (!selectedId || historyLoaded.current.has(selectedId)) return;
    const projectId = selectedId;
    historyLoaded.current.add(projectId);
    listMessages(projectId)
      .then((history) => addMessages([...history].reverse(), "prepend"))
      .catch((error) => {
        historyLoaded.current.delete(projectId); // retry next time it is opened
        console.error("Could not load messages", error);
      });
  }, [selectedId]);

  const handleNewProject = async () => {
    const name = nextProjectName(takenNames.current);
    takenNames.current.add(name); // reserve now so a quick second click gets the next number
    try {
      const project = await createProject(name);
      setProjects((list) => [project, ...list]);
      setSelectedId(project.id);
    } catch (error) {
      takenNames.current.delete(name);
      console.error("Could not create project", error);
    }
  };

  const handleSend = (text: string) => {
    if (!selectedId) return false; // projects not loaded yet: keep the text in the box
    if (!text) return;
    const projectId = selectedId;
    addMessages([{ id: newId(), project_id: projectId, role: "user", content: text, created_at: new Date().toISOString() }]);
    const timer = startWaiting(projectId);
    sendMessage(projectId, text).catch((error) => {
      console.error("Could not send message", error);
      stopWaiting(projectId, timer);
    });
  };

  useProjectStream(selectedId, (event: ScrapEvent) => {
    if (event.type === "chat_reply" && addMessages([event.payload])) {
      stopWaiting(event.project_id);
    }
  });

  const messages = selectedId ? (messagesByProject[selectedId] ?? []) : [];
  const awaitingReply = selectedId !== null && (pendingCount[selectedId] ?? 0) > 0;

  return (
    <Workbook>
      <Sidebar
        projects={projects}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onNewProject={handleNewProject}
      />
      <SpiralBinding />
      <Page
        view={messages.length ? <ChatView messages={messages} awaitingReply={awaitingReply} /> : <WelcomeView />}
        composer={<Composer onSend={handleSend} onAttach={() => console.info("[mock] attach dataset")} />}
      />
    </Workbook>
  );
}

function nextProjectName(taken: Set<string>): string {
  let n = 1;
  while (taken.has(`Project ${n}`)) n++;
  return `Project ${n}`;
}
