// Mirrors shared/schemas.py, which is the source of truth (owned with Alexandre).
// Same names and order as the Python file. Datetimes arrive as ISO strings
// because payloads are serialized with model_dump(mode="json").

export type ProjectStatus = "created" | "intake" | "running" | "done" | "stopped" | "failed";

export type HypothesisStatus =
  | "planning"
  | "coding"
  | "running"
  | "critiquing"
  | "approved"
  | "rejected"
  | "failed";

export type CellStatus = "queued" | "running" | "ok" | "error" | "timeout";

export type SourceKind = "upload" | "europe_pmc";

export type CriticVerdict = "approve" | "revise" | "reject";

export type Novelty = "known" | "partly_known" | "not_found_in_sources";

export type Role = "user" | "assistant";

export interface Project {
  id: string;
  name: string;
  dataset_path: string;
  status: ProjectStatus;
  created_at: string;
}

/** A paper the literature agent can search: an uploaded PDF or an online abstract. */
export interface Source {
  id: string;
  project_id: string;
  kind: SourceKind;
  title: string;
  path_or_url: string;
  pmid: string | null;
  added_at: string;
}

export interface Brief {
  project_id: string;
  organism: string | null;
  condition_column: string | null;
  condition_labels: string[];
  donor_column: string | null;
  celltype_column: string | null;
  gene_id_format: string | null; // e.g. "symbol", "ensembl"
  prior_analyses: string[];
  goals: string;
  notes: string;
  online_search: boolean; // let the literature agent query Europe PMC
}

export interface Hypothesis {
  id: string;
  project_id: string;
  title: string;
  rationale: string;
  plan_steps: string[];
  status: HypothesisStatus;
}

export interface CodeCell {
  id: string;
  hypothesis_id: string;
  index: number;
  source: string;
  stdout: string;
  stderr: string;
  figure_paths: string[];
  status: CellStatus;
  started_at: string | null;
  ended_at: string | null;
}

export interface LLMCall {
  id: string;
  project_id: string;
  hypothesis_id: string | null;
  agent: string;
  messages: Record<string, unknown>[];
  reasoning: string | null; // the model's working notes, not a guaranteed explanation
  output: string;
  tool_calls: Record<string, unknown>[];
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  parent_call_id: string | null;
  created_at: string;
}

export interface Finding {
  id: string;
  hypothesis_id: string;
  claim: string;
  test: string;
  statistic: number | null;
  p_adj: number | null;
  effect_size: number | null;
  figure_path: string | null;
  critic_verdict: CriticVerdict | null;
  critic_notes: string;
  novelty: Novelty | null;
  citations: string[]; // source ids or PMIDs
  sources_searched: string[]; // source ids checked for novelty
  notebook_path: string | null;
}

export interface ChatMessage {
  id: string;
  project_id: string;
  role: Role;
  content: string;
  created_at: string;
}

/** What the sidebar needs to list a project (frontend-only view of Project). */
export type ProjectSummary = Pick<Project, "id" | "name" | "created_at">;
