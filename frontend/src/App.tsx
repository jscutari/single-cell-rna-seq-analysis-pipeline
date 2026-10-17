import { useEffect, useState } from "react";
import { createProject, listProjects, sendMessage } from "./api/client";
import { ChatView } from "./components/ChatView/ChatView";
import { Composer } from "./components/Composer/Composer";
import { Page } from "./components/Page/Page";
import { Sidebar } from "./components/Sidebar/Sidebar";
import { SpiralBinding } from "./components/SpiralBinding";
import { WelcomeView } from "./components/WelcomeCard/WelcomeView";
import { Workbook } from "./components/Workbook";
import type { ChatMessage, ProjectSummary } from "./types/schemas";

export default function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messagesByProject, setMessagesByProject] = useState<Record<string, ChatMessage[]>>({});
  const [pendingReply, setPendingReply] = useState<Set<string>>(new Set());

  useEffect(() => {
    listProjects().then((list) => {
      setProjects(list);
      setSelectedId((current) => current ?? list[0]?.id ?? null);
    });
  }, []);

  const handleNewProject = async () => {
    const project = await createProject(nextProjectName(projects));
    setProjects((list) => [project, ...list]);
    setSelectedId(project.id);
  };

  const appendMessage = (message: ChatMessage) =>
    setMessagesByProject((all) => ({
      ...all,
      [message.project_id]: [...(all[message.project_id] ?? []), message],
    }));

  const setPending = (projectId: string, pending: boolean) =>
    setPendingReply((current) => {
      const next = new Set(current);
      if (pending) next.add(projectId);
      else next.delete(projectId);
      return next;
    });

  const handleSend = async (text: string) => {
    console.info("[shell] send clicked", { projectId: selectedId, text });
    if (!selectedId || !text) return;
    const projectId = selectedId;
    appendMessage({
      id: crypto.randomUUID(),
      project_id: projectId,
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
    });
    setPending(projectId, true);
    try {
      appendMessage(await sendMessage(projectId, text));
    } finally {
      setPending(projectId, false);
    }
  };

  const messages = selectedId ? (messagesByProject[selectedId] ?? []) : [];
  const awaitingReply = selectedId !== null && pendingReply.has(selectedId);

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

function nextProjectName(projects: ProjectSummary[]): string {
  const taken = new Set(projects.map((p) => p.name));
  let n = 1;
  while (taken.has(`Project ${n}`)) n++;
  return `Project ${n}`;
}
