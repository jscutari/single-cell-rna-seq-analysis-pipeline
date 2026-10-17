// Mirrors shared/schemas.py (PLAN.md §5). Keep in sync when the shared contract changes.

export type ProjectStatus = "draft" | "intake" | "running" | "done" | "stopped" | "failed";

export interface Project {
  id: string;
  name: string;
  dataset_path: string;
  paper_path: string | null;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
}

export interface Brief {
  project_id: string;
  organism: string;
  condition_column: string;
  condition_labels: string[];
  donor_column: string;
  celltype_column: string;
  gene_id_format: string;
  prior_analyses: string[];
  goals: string;
  notes: string;
}

export type HypothesisStatus =
  | "planning"
  | "coding"
  | "running"
  | "critiquing"
  | "approved"
  | "rejected"
  | "failed";

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
  status: string;
  started_at: string | null;
  ended_at: string | null;
}

export interface LLMCall {
  id: string;
  project_id: string;
  hypothesis_id: string | null;
  agent: string;
  messages: unknown;
  reasoning: string | null;
  output: string;
  tool_calls: unknown;
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
  critic_verdict: string;
  critic_notes: string;
  novelty: string | null;
  citations: string[];
  notebook_path: string | null;
}

export interface ChatMessage {
  id: string;
  project_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

/** What the sidebar needs to list a project. */
export type ProjectSummary = Pick<Project, "id" | "name" | "updated_at">;
