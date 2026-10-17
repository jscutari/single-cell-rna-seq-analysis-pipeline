import {
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
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

const WIDTH_KEY = "scrap.panelWidth";
const MIN_PANEL = 300;
const MIN_VIEW = 360; // keep at least this much room for the chat or page
const EDGE = 18; // gap between the panel and the page's right edge
const STEP = 24; // keyboard resize step

function readWidth(): number | null {
  try {
    const n = Number(localStorage.getItem(WIDTH_KEY));
    return Number.isFinite(n) && n >= MIN_PANEL ? n : null;
  } catch {
    return null;
  }
}

function saveWidth(width: number | null) {
  try {
    if (width === null) localStorage.removeItem(WIDTH_KEY);
    else localStorage.setItem(WIDTH_KEY, String(Math.round(width)));
  } catch {
    /* storage unavailable: the width still applies for this session */
  }
}

export function Page({ view, composer, panel, filesOpen = false, onToggleFiles, onDropFiles, dropTarget }: PageProps) {
  const [dragging, setDragging] = useState(false);
  const main = useRef<HTMLElement>(null);
  /** Panel width chosen by dragging; null means the CSS default. */
  const [panelWidth, setPanelWidth] = useState<number | null>(readWidth);
  const [resizing, setResizing] = useState(false); // drives the dragging cursor/styles
  const resizingNow = useRef(false); // read by pointer handlers; never stale between events

  const clampWidth = (width: number) => {
    const pageWidth = main.current?.getBoundingClientRect().width || 0;
    const max = pageWidth ? Math.max(MIN_PANEL, pageWidth - MIN_VIEW - EDGE) : Infinity;
    return Math.min(Math.max(width, MIN_PANEL), max);
  };
  const setWidth = (width: number | null) => {
    if (width !== null && !Number.isFinite(width)) return;
    const next = width === null ? null : clampWidth(width);
    setPanelWidth(next);
    saveWidth(next);
  };
  const currentWidth = () =>
    panelWidth ?? (main.current?.querySelector(".preview-panel")?.getBoundingClientRect().width || 440);

  const resize = {
    onPointerDown: (e: PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      resizingNow.current = true;
      setResizing(true);
    },
    onPointerMove: (e: PointerEvent<HTMLDivElement>) => {
      if (!resizingNow.current || !main.current) return;
      const right = main.current.getBoundingClientRect().right;
      setWidth(right - EDGE - e.clientX);
    },
    onPointerUp: (e: PointerEvent<HTMLDivElement>) => {
      e.currentTarget.releasePointerCapture(e.pointerId);
      resizingNow.current = false;
      setResizing(false);
    },
    onDoubleClick: () => setWidth(null),
    onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "ArrowLeft") setWidth(currentWidth() + STEP);
      else if (e.key === "ArrowRight") setWidth(currentWidth() - STEP);
      else return;
      e.preventDefault();
    },
  };
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

  const classes = ["page", panel && "page--with-panel", resizing && "page--resizing"].filter(Boolean).join(" ");
  const style = panelWidth ? ({ "--preview-width": `${panelWidth}px` } as CSSProperties) : undefined;
  return (
    <main ref={main} className={classes} style={style} {...drop}>
      <TopBar filesOpen={filesOpen} onToggleFiles={onToggleFiles} />
      <div className="page-view">{view}</div>
      {composer}
      {panel}
      {panel && (
        <div
          className="panel-resizer"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize panel"
          aria-valuenow={Math.round(panelWidth ?? 0) || undefined}
          tabIndex={0}
          title="Drag to resize · double-click to reset"
          {...resize}
        />
      )}
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
