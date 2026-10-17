import { useEffect, useRef, useState } from "react";
import type { ProjectSummary } from "../../types/schemas";
import { ChevronDownIcon, FolderIcon, PlusIcon } from "../icons/Icons";

interface ProjectChipProps {
  projects: ProjectSummary[];
  selectedId: string | null;
  onSelect: (projectId: string) => void;
  onNewProject: () => void;
}

/** "in Project 1 ▾" above the home-screen composer: shows and changes where a new chat goes. */
export function ProjectChip({ projects, selectedId, onSelect, onNewProject }: ProjectChipProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const selected = projects.find((p) => p.id === selectedId);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="project-chip-wrap" ref={root}>
      <button
        className="project-chip"
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`New chat goes in ${selected?.name ?? "a new project"}. Change project`}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="project-chip-label">in</span>
        <FolderIcon />
        <span className="project-chip-name">{selected?.name ?? "New project"}</span>
        <ChevronDownIcon />
      </button>
      {open && (
        <ul className="project-menu" role="menu" aria-label="Choose a project">
          {projects.map((p) => (
            <li key={p.id} role="none">
              <button
                role="menuitemradio"
                aria-checked={p.id === selectedId}
                type="button"
                className={p.id === selectedId ? "project-menu-item project-menu-item--on" : "project-menu-item"}
                onClick={() => {
                  onSelect(p.id);
                  setOpen(false);
                }}
              >
                <FolderIcon />
                <span>{p.name}</span>
              </button>
            </li>
          ))}
          <li role="none" className="project-menu-sep">
            <button
              role="menuitem"
              type="button"
              className="project-menu-item project-menu-item--new"
              onClick={() => {
                onNewProject();
                setOpen(false);
              }}
            >
              <PlusIcon />
              <span>New project</span>
            </button>
          </li>
        </ul>
      )}
    </div>
  );
}
