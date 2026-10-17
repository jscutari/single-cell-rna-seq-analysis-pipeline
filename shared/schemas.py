"""Pydantic models shared by agents and backend (PLAN.md section 5)."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def new_id() -> str:
    return uuid4().hex


def now() -> datetime:
    return datetime.now(timezone.utc)


class ProjectStatus(StrEnum):
    created = "created"
    intake = "intake"
    running = "running"
    done = "done"
    stopped = "stopped"
    failed = "failed"


class HypothesisStatus(StrEnum):
    planning = "planning"
    coding = "coding"
    running = "running"
    critiquing = "critiquing"
    approved = "approved"
    rejected = "rejected"
    failed = "failed"


class CellStatus(StrEnum):
    queued = "queued"
    running = "running"
    ok = "ok"
    error = "error"
    timeout = "timeout"


class SourceKind(StrEnum):
    upload = "upload"
    europe_pmc = "europe_pmc"


class CriticVerdict(StrEnum):
    approve = "approve"
    revise = "revise"
    reject = "reject"


class Novelty(StrEnum):
    known = "known"
    partly_known = "partly_known"
    not_found_in_sources = "not_found_in_sources"


class Role(StrEnum):
    user = "user"
    assistant = "assistant"


class Project(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    dataset_path: str
    status: ProjectStatus = ProjectStatus.created
    created_at: datetime = Field(default_factory=now)


class Source(BaseModel):
    """A paper the literature agent can search: an uploaded PDF or an online abstract."""

    id: str = Field(default_factory=new_id)
    project_id: str
    kind: SourceKind
    title: str
    path_or_url: str
    pmid: str | None = None
    added_at: datetime = Field(default_factory=now)


class Brief(BaseModel):
    project_id: str
    organism: str | None = None
    condition_column: str | None = None
    condition_labels: list[str] = []
    donor_column: str | None = None
    celltype_column: str | None = None
    gene_id_format: str | None = None  # e.g. "symbol", "ensembl"
    prior_analyses: list[str] = []
    goals: str = ""
    notes: str = ""
    online_search: bool = False  # let the literature agent query Europe PMC


class Hypothesis(BaseModel):
    id: str = Field(default_factory=new_id)
    project_id: str
    title: str
    rationale: str = ""
    plan_steps: list[str] = []
    status: HypothesisStatus = HypothesisStatus.planning


class CodeCell(BaseModel):
    id: str = Field(default_factory=new_id)
    hypothesis_id: str
    index: int
    source: str
    stdout: str = ""
    stderr: str = ""
    figure_paths: list[str] = []
    status: CellStatus = CellStatus.queued
    started_at: datetime | None = None
    ended_at: datetime | None = None


class LLMCall(BaseModel):
    id: str = Field(default_factory=new_id)
    project_id: str
    hypothesis_id: str | None = None
    agent: str
    messages: list[dict[str, Any]]
    reasoning: str | None = None  # the model's working notes, not a guaranteed explanation
    output: str = ""
    tool_calls: list[dict[str, Any]] = []
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    parent_call_id: str | None = None
    created_at: datetime = Field(default_factory=now)


class Finding(BaseModel):
    id: str = Field(default_factory=new_id)
    hypothesis_id: str
    claim: str
    test: str
    statistic: float | None = None
    p_adj: float | None = None
    effect_size: float | None = None
    figure_path: str | None = None
    critic_verdict: CriticVerdict | None = None
    critic_notes: str = ""
    novelty: Novelty | None = None
    citations: list[str] = []  # source ids or PMIDs
    sources_searched: list[str] = []  # source ids checked for novelty
    notebook_path: str | None = None


class ChatMessage(BaseModel):
    id: str = Field(default_factory=new_id)
    project_id: str
    role: Role
    content: str
    created_at: datetime = Field(default_factory=now)
