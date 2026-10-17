import type { ProjectSummary } from "../types/schemas";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

// Sample list from the design reference; replaced by GET /api/projects once the backend exists.
export const mockProjects: ProjectSummary[] = [
  { id: "p1", name: "Project 1", created_at: ago(0) },
  { id: "p2", name: "scRNA-seq Analysis", created_at: ago(2 * HOUR) },
  { id: "p3", name: "Differential Expression", created_at: ago(DAY) },
  { id: "p4", name: "Pathway Analysis", created_at: ago(3 * DAY) },
  { id: "p5", name: "GWAS Exploration", created_at: ago(7 * DAY) },
  { id: "p6", name: "Metagenomics Study", created_at: ago(14 * DAY) },
  { id: "p7", name: "Protein Structure", created_at: ago(14 * DAY) },
];
