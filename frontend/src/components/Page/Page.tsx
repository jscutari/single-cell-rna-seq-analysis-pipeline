import { useRef, useState, type DragEvent, type ReactNode } from "react";
import { DotsIcon, FilesIcon, ShareIcon } from "../icons/Icons";
import "./Page.css";

interface PageProps {
  /** The active view: welcome card, chat, or project page. */
  view: ReactNode;
  /** Chat box pinned to the bottom; omitted on the project page. */
  composer?: ReactNode;
  /** Side panel docked on the right (file preview); the view shrinks to make room. */
  panel?: ReactNode;
  /** Shows the Files button in the top bar. */
  filesOpen?: boolean;
  onToggleFiles?: () => void;
  /** Accept files dropped anywhere on the page; dropTarget names where they go. */
  onDropFiles?: (files: File[]) => void;
  dropTarget?: string;
}

export function Page({ view, composer, panel, filesOpen = false, onToggleFiles, onDropFiles, dropTarget }: PageProps) {
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0); // dragenter/leave fire for every child; count to know when we really left

  const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
  const drop = onDropFiles && {
    onDragEnter: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current += 1;
      setDragging(true);
    },
    onDragOver: (e: DragEvent) => {
      if (hasFiles(e)) e.preventDefault(); // required for the drop event to fire
    },
    onDragLeave: () => {
      depth.current = Math.max(0, depth.current - 1);
      if (!depth.current) setDragging(false);
    },
    onDrop: (e: DragEvent) => {
      e.preventDefault();
      depth.current = 0;
      setDragging(false);
      const files = Array.from(e.dataTransfer?.files ?? []);
      if (files.length) onDropFiles(files);
    },
  };

  return (
    <main className={panel ? "page page--with-panel" : "page"} {...drop}>
      <TopBar filesOpen={filesOpen} onToggleFiles={onToggleFiles} />
      <div className="page-view">{view}</div>
      {composer}
      {panel}
      {dragging && (
        <div className="drop-overlay" aria-hidden="true">
          <div className="drop-sheet">Drop files to add them to {dropTarget ?? "this project"}</div>
        </div>
      )}
    </main>
  );
}

function TopBar({ filesOpen, onToggleFiles }: { filesOpen: boolean; onToggleFiles?: () => void }) {
  return (
    <header className="topbar" aria-label="Workspace actions">
      <div className="top-actions">
        {onToggleFiles && (
          <button
            className={filesOpen ? "round-action round-action--on" : "round-action"}
            type="button"
            aria-label={filesOpen ? "Hide project files" : "Show project files"}
            aria-pressed={filesOpen}
            title="Files"
            onClick={onToggleFiles}
          >
            <FilesIcon />
          </button>
        )}
        <button className="round-action" type="button" aria-label="Share project">
          <ShareIcon />
        </button>
        <button className="round-action" type="button" aria-label="More options">
          <DotsIcon />
        </button>
      </div>
    </header>
  );
}
