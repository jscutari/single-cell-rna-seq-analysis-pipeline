-- Backend schema. Applied at every startup; every statement is idempotent.
-- Bump the version row when a change needs a migration step.

CREATE TABLE IF NOT EXISTS schema_version (
    version    integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

-- Projects (the folder under DATA_ROOT keeps the files; this is the list).
CREATE TABLE IF NOT EXISTS projects (
    id           text PRIMARY KEY,
    name         text NOT NULL,
    dataset_path text NOT NULL,
    created_at   timestamptz NOT NULL
);

-- Every event, in order. ids are assigned by the backend (the SSE ids).
-- llm_call payloads are stored without their prompt messages (see llm_calls).
CREATE TABLE IF NOT EXISTS events (
    id         bigint PRIMARY KEY,
    project_id text NOT NULL,
    type       text NOT NULL,
    payload    jsonb NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS events_project_id_idx ON events (project_id, id);

-- Full LLM calls, queryable for the trace and benchmarks.
CREATE TABLE IF NOT EXISTS llm_calls (
    id             text PRIMARY KEY,
    project_id     text NOT NULL,
    hypothesis_id  text,
    agent          text NOT NULL,
    reasoning      text,
    output         text NOT NULL DEFAULT '',
    messages       jsonb NOT NULL DEFAULT '[]',
    tool_calls     jsonb NOT NULL DEFAULT '[]',
    tokens_in      integer NOT NULL DEFAULT 0,
    tokens_out     integer NOT NULL DEFAULT 0,
    latency_ms     integer NOT NULL DEFAULT 0,
    parent_call_id text,
    created_at     timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS llm_calls_project_agent_idx ON llm_calls (project_id, agent);
CREATE INDEX IF NOT EXISTS llm_calls_hypothesis_idx ON llm_calls (hypothesis_id);

INSERT INTO schema_version (version) VALUES (1) ON CONFLICT DO NOTHING;
