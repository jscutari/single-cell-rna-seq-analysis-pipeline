"""Live event stream to the browser (server-sent events).

GET /api/projects/{id}/events streams `id: <serial>`, `event: <type>` and
`data: <event JSON>` blocks. It starts after `Last-Event-ID` (sent by the
browser when it reconnects), else after `?after=`, else from now - the app
loads /state first and passes its last_event_id, so nothing is missed between
the snapshot and the stream.
"""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.hub import EventHub
from backend.routes.projects import require_project
from backend.store import StoredEvent, summarize_llm_call

RETRY_MS = 3000
router = APIRouter(prefix="/api/projects/{project_id}", tags=["events"])


def format_event(event: StoredEvent) -> str:
    """One SSE block. LLM calls go out without their prompt messages (fetch those on demand)."""
    payload = summarize_llm_call(event.payload) if event.type == "llm_call" else event.payload
    data = {"id": str(event.id), "type": event.type, "project_id": event.project_id,
            "payload": payload, "created_at": event.created_at}
    return f"id: {event.id}\nevent: {event.type}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def event_stream(hub: EventHub, project_id: str, after: int, heartbeat: float) -> AsyncIterator[str]:
    """Stored events after `after`, then live ones, with heartbeats while idle.

    Subscribes before reading the backlog, and skips queued events it already
    sent, so the switch from backlog to live loses and repeats nothing. Ends when
    the subscriber falls behind; the browser then reconnects with Last-Event-ID.
    """
    sub = hub.subscribe(project_id)
    try:
        yield f"retry: {RETRY_MS}\n\n"
        last = after
        for event in hub.store.events_after(project_id, after):
            yield format_event(event)
            last = event.id
        while not sub.overflowed:
            try:
                event = await asyncio.wait_for(sub.queue.get(), timeout=heartbeat)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if event.id <= last:
                continue
            yield format_event(event)
            last = event.id
    finally:
        hub.unsubscribe(sub)


def _start_after(last_event_id: str | None, after: int | None, now: int) -> int:
    if last_event_id is not None:
        try:
            return max(0, int(last_event_id))
        except ValueError:
            raise HTTPException(400, "Last-Event-ID must be an integer") from None
    return now if after is None else after


@router.get("/events")
async def stream_events(project_id: str, request: Request, after: int | None = None,
                        last_event_id: str | None = Header(default=None)) -> StreamingResponse:
    require_project(request, project_id)
    if after is not None and after < 0:
        raise HTTPException(400, "after must be >= 0")
    hub: EventHub = request.app.state.hub
    start = _start_after(last_event_id, after, hub.store.last_event_id)
    return StreamingResponse(
        event_stream(hub, project_id, start, request.app.state.settings.heartbeat_seconds),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
