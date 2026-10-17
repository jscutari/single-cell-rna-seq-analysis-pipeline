import type { ProjectSummary } from "../../types/schemas";
import "./ProjectView.css";

interface ProjectViewProps {
  project: ProjectSummary;
}

/** A project's page: its files and key findings. */
export function ProjectView({ project }: ProjectViewProps) {
  return (
    <div className="project-page">
      <header className="project-page-header">
        <h1 className="project-page-title">{project.name}</h1>
        <p className="project-page-meta">Created {new Date(project.created_at).toLocaleDateString()}</p>
      </header>
    </div>
  );
}
