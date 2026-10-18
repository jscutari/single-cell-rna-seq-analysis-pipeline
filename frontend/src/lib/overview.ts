import type { ProjectOverview } from "../types/ui";

/** The parts of project_state.json the overview reads (agents/results.py). */
export interface ResultsState {
  brief?: { goals?: string | null; organism?: string | null } | null;
  dataset?: { n_cells?: number; n_donors?: number | null; conditions?: Record<string, number> | null } | null;
  report?: string | null;
}

/** First paragraph under the report's first heading, as plain text (no Markdown marks). */
export function reportSummary(markdown: string | null | undefined): string | null {
  if (!markdown) return null;
  const blocks = markdown.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
  const paragraph = blocks.find((b) => !b.startsWith("#"));
  if (!paragraph) return null;
  return paragraph.replace(/\*\*|__|\*|`/g, "").replace(/\s+/g, " ").trim();
}

export function toOverview(results: ResultsState | null | undefined): ProjectOverview | null {
  if (!results) return null;
  const overview: ProjectOverview = {
    goal: results.brief?.goals?.trim() || null,
    organism: results.brief?.organism ?? null,
    n_cells: results.dataset?.n_cells ?? null,
    n_donors: results.dataset?.n_donors ?? null,
    conditions: results.dataset?.conditions ?? null,
    summary: reportSummary(results.report),
  };
  return Object.values(overview).some((v) => v !== null) ? overview : null;
}

/** "44,649 cells · 13 donors · COVID-19 vs normal" */
export function datasetLine(o: ProjectOverview): string {
  const parts = [];
  if (o.n_cells !== null) parts.push(`${o.n_cells.toLocaleString("en-US")} cells`);
  if (o.n_donors !== null) parts.push(`${o.n_donors} donors`);
  if (o.conditions) parts.push(Object.keys(o.conditions).join(" vs "));
  if (o.organism) parts.push(o.organism);
  return parts.join(" · ");
}
