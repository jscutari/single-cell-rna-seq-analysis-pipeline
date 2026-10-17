"""In-memory state built from the event log.

Every change goes through `append(event)`: agent events (shared.events) plus two
backend-only types, `user_message` and `run_status`. Views (messages, brief,
hypotheses, cells, findings, LLM calls, run status) are folded from those events,
so there is one write path. A database-backed store can replace this class
later without touching the routes.

Durable results live on disk in <project_dir>/project_state.json (written by
agents/results.py); this store holds what that file doesn't: the live event
log, chat history and run status. It is lost on restart for now.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

USER_MESSAGE = "user_message"  # payload: ChatMessage (role user)
RUN_STATUS = "run_status"  # payload: {"status": RunStatus}

# Final stage names emitted by agents/orchestrator.py as stage_done.
STAGE_TO_STATUS = {"report": "done", "stopped": "stopped", "failed": "failed"}
RUN_STATUSES = ("idle", "running", "done", "stopped", "failed")


@dataclass
class StoredEvent:
    id: int  # serial, assigned by the store; used as the SSE id
    type: str
    project_id: str
    payload: dict[str, Any]
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "project_id": self.project_id,
                "payload": self.payload, "created_at": self.created_at}


@dataclass
class ProjectView:
    messages: dict[str, dict] = field(default_factory=dict)  # id -> ChatMessage, in arrival order
    brief: dict | None = None
    hypotheses: dict[str, dict] = field(default_factory=dict)
    cells: dict[str, dict[str, dict]] = field(default_factory=lambda: defaultdict(dict))  # hid -> cell id -> cell
    findings: dict[str, dict] = field(default_factory=dict)
    llm_calls: dict[str, dict] = field(default_factory=dict)  # summaries (no messages)
    stage: str | None = None
    status: str = "idle"


def summarize_llm_call(call: dict) -> dict:
    """An LLM call without its (large) prompt messages. Idempotent: an already
    trimmed call (e.g. restored from the database) keeps its message_count."""
    summary = {k: v for k, v in call.items() if k != "messages"}
    if "messages" in call:
        summary["message_count"] = len(call["messages"] or [])
    else:
        summary.setdefault("message_count", 0)
    return summary


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryStore:
    def __init__(self) -> None:
        self._events: list[StoredEvent] = []
        self._by_project: dict[str, list[StoredEvent]] = defaultdict(list)
        self._views: dict[str, ProjectView] = defaultdict(ProjectView)
        self._llm_calls: dict[str, dict] = {}  # full calls, by id
        self._last_id = 0

    # --- writes ---

    def append(self, type: str, project_id: str, payload: dict[str, Any], created_at: str | None = None) -> StoredEvent | None:
        """Store one event and update the views. Returns None for a duplicate user message."""
        view = self._views[project_id]
        if type == USER_MESSAGE and payload["id"] in view.messages:
            return None  # same client id sent twice (a retry): keep the first
        event = StoredEvent(self._last_id + 1, type, project_id, payload, created_at or now_iso())
        self._add(event, view)
        return event

    def restore(self, event: StoredEvent) -> None:
        """Re-add an event saved earlier (startup), keeping its id."""
        if event.id <= self._last_id:
            raise ValueError(f"events must be restored in id order ({event.id} after {self._last_id})")
        self._add(event, self._views[event.project_id])

    def _add(self, event: StoredEvent, view: ProjectView) -> None:
        self._last_id = event.id
        self._events.append(event)
        self._by_project[event.project_id].append(event)
        self._apply(view, event)

    def _apply(self, view: ProjectView, event: StoredEvent) -> None:
        p = event.payload
        match event.type:
            case "chat_reply" | "user_message":
                view.messages.setdefault(p["id"], p)
            case "brief_updated":
                view.brief = p
            case "hypothesis_status":
                view.hypotheses[p["id"]] = p
            case "cell_started" | "cell_finished":
                view.cells[p["hypothesis_id"]][p["id"]] = p
            case "finding":
                view.findings[p["id"]] = p
            case "llm_call":
                if "messages" in p:  # a full call; restored events are already trimmed
                    self._llm_calls[p["id"]] = p
                view.llm_calls[p["id"]] = summarize_llm_call(p)
            case "stage_done":
                view.stage = p.get("stage")
                if view.stage in STAGE_TO_STATUS:
                    view.status = STAGE_TO_STATUS[view.stage]
            case "run_status":
                view.status = p["status"]

    # --- reads ---

    @property
    def last_event_id(self) -> int:
        return self._last_id

    def events_after(self, project_id: str, after: int) -> list[StoredEvent]:
        events = self._by_project.get(project_id, [])
        # Serials are global and increasing, so skip ahead without scanning everything.
        lo, hi = 0, len(events)
        while lo < hi:
            mid = (lo + hi) // 2
            if events[mid].id <= after:
                lo = mid + 1
            else:
                hi = mid
        return events[lo:]

    def view(self, project_id: str) -> ProjectView:
        return self._views[project_id]

    def status(self, project_id: str) -> str:
        return self._views[project_id].status if project_id in self._views else "idle"

    def messages(self, project_id: str) -> list[dict]:
        return list(self._views[project_id].messages.values()) if project_id in self._views else []

    def llm_call(self, call_id: str) -> dict | None:
        return self._llm_calls.get(call_id)

    async def fetch_llm_call(self, call_id: str) -> dict | None:
        """The full call; a database-backed store also looks in the database."""
        return self.llm_call(call_id)

    # Persistence hooks (no-ops here; see backend/pg_store.py).
    db_status = "memory"

    async def flush(self, timeout: float = 5.0) -> None:
        return None

    async def close(self) -> None:
        return None

    def known_projects(self) -> set[str]:
        return set(self._views)

    def running_projects(self) -> list[str]:
        return [pid for pid, v in self._views.items() if v.status == "running"]
