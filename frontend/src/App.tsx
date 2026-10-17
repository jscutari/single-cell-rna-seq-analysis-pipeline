import { useEffect, useState } from "react";
import { createProject, listProjects, sendMessage } from "./api/client";
import { Composer } from "./components/Composer/Composer";
import { Page } from "./components/Page/Page";
import { Sidebar } from "./components/Sidebar/Sidebar";
import { SpiralBinding } from "./components/SpiralBinding";
import { WelcomeView } from "./components/WelcomeCard/WelcomeView";
import { Workbook } from "./components/Workbook";
import type { ProjectSummary } from "./types/schemas";

export default function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

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

  const handleSend = (text: string) => {
    console.info("[shell] send clicked", { projectId: selectedId, text });
    if (selectedId && text) void sendMessage(selectedId, text);
  };

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
        view={<WelcomeView />}
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
