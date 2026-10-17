import logo from "../../assets/scrap-logo.png";
import type { ProjectSummary } from "../../types/schemas";
import { relativeTime } from "../../lib/relativeTime";
import { DotsIcon, FolderIcon, GearIcon, HelpIcon, PlusIcon } from "../icons/Icons";
import "./Sidebar.css";

interface SidebarProps {
  projects: ProjectSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNewProject: () => void;
}

export function Sidebar({ projects, selectedId, onSelect, onNewProject }: SidebarProps) {
  return (
    <aside className="sidebar" aria-label="Projects navigation">
      <header className="brand">
        <img className="brand-logo" src={logo} alt="SCRAP DNA wastebasket logo" />
        <div className="brand-copy">
          <strong className="brand-name">SCRAP</strong>
        </div>
      </header>

      <button className="new-project" type="button" onClick={onNewProject}>
        <PlusIcon />
        <span>New Project</span>
      </button>

      <h2 className="sidebar-heading">Recent Projects</h2>
      <nav className="projects" aria-label="Recent projects">
        {projects.map((project) => (
          <ProjectItem
            key={project.id}
            project={project}
            selected={project.id === selectedId}
            onSelect={() => onSelect(project.id)}
          />
        ))}
      </nav>

      <footer className="sidebar-foot">
        <button className="foot-link" type="button">
          <HelpIcon />
          <span>Help &amp; Docs</span>
        </button>
        <button className="foot-link" type="button">
          <GearIcon />
          <span>Settings</span>
        </button>
      </footer>
    </aside>
  );
}

function ProjectItem({
  project,
  selected,
  onSelect,
}: {
  project: ProjectSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      className={selected ? "project project-selected" : "project"}
      type="button"
      aria-current={selected ? "page" : undefined}
      title={project.name}
      onClick={onSelect}
    >
      <FolderIcon />
      <span className="project-meta">
        <span className="project-name">{project.name}</span>
        <span className="project-time">{relativeTime(project.created_at)}</span>
      </span>
      {selected && (
        <span className="project-more" aria-hidden="true">
          <DotsIcon />
        </span>
      )}
    </button>
  );
}
