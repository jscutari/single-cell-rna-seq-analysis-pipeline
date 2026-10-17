import { useEffect, useRef, useState } from "react";
import logo from "../../assets/scrap-logo.svg";
import { relativeTime } from "../../lib/relativeTime";
import type { ProjectSummary } from "../../types/schemas";
import type { Chat, View } from "../../types/ui";
import { ChevronDownIcon, FolderIcon, GearIcon, HelpIcon, PencilIcon, PlusIcon, SidebarIcon } from "../icons/Icons";
import "./Sidebar.css";

interface SidebarProps {
  projects: ProjectSummary[];
  chatsByProject: Record<string, Chat[]>;
  view: View;
  expandedProjectId: string | null;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  onSelectProject: (projectId: string) => void;
  onSelectChat: (projectId: string, chatId: string) => void;
  onNewChat: (projectId: string) => void;
  onRenameChat?: (projectId: string, chatId: string, title: string) => void;
  onNewProject: () => void;
  /** Logo click: back to the start screen, as when the app opens. */
  onHome?: () => void;
}

export function Sidebar({
  projects,
  chatsByProject,
  view,
  expandedProjectId,
  collapsed = false,
  onToggleCollapsed,
  onSelectProject,
  onSelectChat,
  onNewChat,
  onRenameChat,
  onNewProject,
  onHome,
}: SidebarProps) {
  return (
    <aside className={collapsed ? "sidebar sidebar--collapsed" : "sidebar"} aria-label="Projects navigation">
      <header className="brand">
        <button className="brand-home" type="button" aria-label="SCRAP home" title="SCRAP · Single-cell RNA-seq Analysis Pipeline" onClick={onHome}>
          <img className="brand-logo" src={logo} alt="" />
          <span className="brand-copy">
            <strong className="brand-name">SCRAP</strong>
          </span>
        </button>
        {onToggleCollapsed && (
          <button
            className="sidebar-toggle"
            type="button"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!collapsed}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={onToggleCollapsed}
          >
            <SidebarIcon />
          </button>
        )}
      </header>

      <button className="new-project" type="button" onClick={onNewProject} title="New Project">
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
              {expanded && !collapsed && (
                <ul className="chat-list" aria-label={`${project.name} chats`}>
                  <li>
                    <button className="chat-item chat-item--new" type="button" onClick={() => onNewChat(project.id)}>
                      <PlusIcon />
                      <span>New chat</span>
                    </button>
                  </li>
                  {chats.map((chat) => (
                    <ChatItem
                      key={chat.id}
                      chat={chat}
                      active={view.kind === "chat" && view.chatId === chat.id}
                      onSelect={() => onSelectChat(project.id, chat.id)}
                      onRename={onRenameChat && ((title) => onRenameChat(project.id, chat.id, title))}
                    />
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </nav>

      <footer className="sidebar-foot">
        <button className="foot-link" type="button" title="Help & Docs">
          <HelpIcon />
          <span>Help &amp; Docs</span>
        </button>
        <button className="foot-link" type="button" title="Settings">
          <GearIcon />
          <span>Settings</span>
        </button>
      </footer>
    </aside>
  );
}

function ChatItem({
  chat,
  active,
  onSelect,
  onRename,
}: {
  chat: Chat;
  active: boolean;
  onSelect: () => void;
  onRename?: (title: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(chat.title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  const startEditing = () => {
    if (!onRename) return;
    setDraft(chat.title);
    setEditing(true);
  };
  const finish = (save: boolean) => {
    setEditing(false);
    const title = draft.trim();
    if (save && title && title !== chat.title) onRename?.(title);
  };

  if (editing) {
    return (
      <li>
        <input
          ref={inputRef}
          className="chat-rename"
          aria-label={`Rename ${chat.title}`}
          value={draft}
          maxLength={80}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => finish(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter") finish(true);
            if (e.key === "Escape") finish(false);
          }}
        />
      </li>
    );
  }
  return (
    <li className="chat-row-item">
      <button
        className={active ? "chat-item chat-item--selected" : "chat-item"}
        type="button"
        aria-current={active ? "page" : undefined}
        title={chat.title}
        onClick={onSelect}
        onDoubleClick={startEditing}
      >
        <span className="chat-title">{chat.title}</span>
      </button>
      {onRename && (
        <button className="chat-rename-button" type="button" aria-label={`Rename ${chat.title}`} onClick={startEditing}>
          <PencilIcon />
        </button>
      )}
    </li>
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
