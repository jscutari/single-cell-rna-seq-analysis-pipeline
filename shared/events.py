"""emit() and event types (PLAN.md section 6).

Agents call emit() and never touch the database. By default events print to
the console; the backend calls set_sink() at startup to save them to Postgres
and push them over SSE instead.
"""

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from shared.schemas import new_id, now


class EventType(StrEnum):
    llm_call = "llm_call"  # payload: LLMCall
    brief_updated = "brief_updated"  # payload: Brief
    hypothesis_status = "hypothesis_status"  # payload: Hypothesis
    cell_started = "cell_started"  # payload: CodeCell
    cell_finished = "cell_finished"  # payload: CodeCell
    finding = "finding"  # payload: Finding
    chat_reply = "chat_reply"  # payload: ChatMessage
    stage_done = "stage_done"  # payload: {"stage": str, "summary": str}


class Event(BaseModel):
    id: str = Field(default_factory=new_id)
    type: EventType
    project_id: str
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=now)

    @field_validator("payload", mode="before")
    @classmethod
    def _dump_model(cls, v: Any) -> Any:
        # Accept a schema model directly: Event(type=..., payload=finding)
        return v.model_dump(mode="json") if isinstance(v, BaseModel) else v


Sink = Callable[[Event], None]


def _print_sink(event: Event) -> None:
    print(event.model_dump_json(), flush=True)


_sink: Sink = _print_sink


def set_sink(sink: Sink) -> None:
    """Route every future emit() to `sink`. It must not block; schedule async work instead."""
    global _sink
    _sink = sink


def emit(event: Event) -> None:
    _sink(event)
