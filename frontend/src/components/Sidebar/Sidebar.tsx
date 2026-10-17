import logo from "../../assets/scrap-logo.png";
import { relativeTime } from "../../lib/relativeTime";
import type { ProjectSummary } from "../../types/schemas";
import type { Chat, View } from "../../types/ui";
import { ChevronDownIcon, FolderIcon, GearIcon, HelpIcon, PlusIcon } from "../icons/Icons";
import "./Sidebar.css";

interface SidebarProps {
  projects: ProjectSummary[];
  chatsByProject: Record<string, Chat[]>;
  view: View;
  expandedProjectId: string | null;
  onSelectProject: (projectId: string) => void;
  onSelectChat: (projectId: string, chatId: string) => void;
  onNewChat: (projectId: string) => void;
  onNewProject: () => void;
}

export function Sidebar({
  projects,
  chatsByProject,
  view,
  expandedProjectId,
  onSelectProject,
  onSelectChat,
  onNewChat,
  onNewProject,
}: SidebarProps) {
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
        {projects.map((project) => {
          const expanded = project.id === expandedProjectId;
          const chats = chatsByProject[project.id] ?? [];
          return (
            <div className="project-group" key={project.id}>
              <ProjectItem
                project={project}
                selected={view.kind === "project" && view.projectId === project.id}
                expanded={expanded}
                onSelect={() => onSelectProject(project.id)}
              />
              {expanded && (
                <ul className="chat-list" aria-label={`${project.name} chats`}>
                  <li>
                    <button className="chat-item chat-item--new" type="button" onClick={() => onNewChat(project.id)}>
                      <PlusIcon />
                      <span>New chat</span>
                    </button>
                  </li>
                  {chats.map((chat) => {
                    const active = view.kind === "chat" && view.chatId === chat.id;
                    return (
                      <li key={chat.id}>
                        <button
                          className={active ? "chat-item chat-item--selected" : "chat-item"}
                          type="button"
                          aria-current={active ? "page" : undefined}
                          onClick={() => onSelectChat(project.id, chat.id)}
                        >
                          <span className="chat-title">{chat.title}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}
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
  expanded,
  onSelect,
}: {
  project: ProjectSummary;
  selected: boolean;
  expanded: boolean;
  onSelect: () => void;
}) {
  const classes = ["project", selected && "project-selected", expanded && "project-expanded"].filter(Boolean).join(" ");
  return (
    <button
      className={classes}
      type="button"
      aria-current={selected ? "page" : undefined}
      aria-expanded={expanded}
      title={project.name}
      onClick={onSelect}
    >
      <FolderIcon />
      <span className="project-meta">
        <span className="project-name">{project.name}</span>
        <span className="project-time">{relativeTime(project.created_at)}</span>
      </span>
      <span className="project-chevron" aria-hidden="true">
        <ChevronDownIcon />
      </span>
    </button>
  );
}
