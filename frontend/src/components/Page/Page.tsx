import type { ReactNode } from "react";
import { DotsIcon, ShareIcon } from "../icons/Icons";
import "./Page.css";

interface PageProps {
  /** The active view (welcome card now; Chat, Trace, Findings… later). */
  view: ReactNode;
  /** Pinned to the bottom of the page across all views. */
  composer: ReactNode;
}

export function Page({ view, composer }: PageProps) {
  return (
    <main className="page">
      <TopBar />
      <div className="page-view">{view}</div>
      {composer}
    </main>
  );
}

function TopBar() {
  return (
    <header className="topbar" aria-label="Workspace actions">
      <div className="top-actions">
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
