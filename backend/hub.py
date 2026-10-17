"""Event hub: receives every emit(), stores it, and fans it out to live streams.

shared.events.set_sink() needs a synchronous function that never blocks. Agents
call emit() on the server's event loop, but some work (preprocessing) runs in
threads, so events from other threads are handed to the loop with
call_soon_threadsafe. Each subscriber (one per open stream) has a bounded queue;
one that falls behind is closed rather than buffering forever, and the browser
reconnects with Last-Event-ID to catch up from the store.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from backend.store import InMemoryStore, StoredEvent
from shared import events as events_module
from shared.events import Event

log = logging.getLogger("scrap.backend.hub")


@dataclass(eq=False)
class Subscription:
    project_id: str
    queue: asyncio.Queue
    overflowed: bool = field(default=False)


class EventHub:
    def __init__(self, store: InMemoryStore, queue_size: int = 1000) -> None:
        self.store = store
        self.queue_size = queue_size
        self.loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: dict[str, set[Subscription]] = {}

    # --- wiring ---

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        events_module.set_sink(self.ingest)

    def detach(self) -> None:
        events_module.set_sink(events_module._print_sink)
        self.loop = None

    # --- the emit() sink ---

    def ingest(self, event: Event) -> None:
        args = (str(event.type), event.project_id, event.payload, event.created_at.isoformat())
        loop = self.loop
        if loop is None or loop.is_closed():
            log.warning("Dropping %s event for %s: hub not attached", event.type, event.project_id)
            return
        try:
            on_loop = asyncio.get_running_loop() is loop
        except RuntimeError:
            on_loop = False
        if on_loop:
            self.publish(*args)
        else:
            loop.call_soon_threadsafe(self._publish_safely, *args)

    def _publish_safely(self, *args) -> None:
        try:
            self.publish(*args)
        except Exception:  # never let one bad event break the loop's callback
            log.exception("Could not publish event %s", args[:2])

    # --- publishing (on the loop) ---

    def publish(self, type: str, project_id: str, payload: dict[str, Any], created_at: str | None = None) -> StoredEvent | None:
        """Store an event and push it to the project's live streams. None if it was a duplicate."""
        event = self.store.append(type, project_id, payload, created_at)
        if event is None:
            return None
        for sub in list(self._subscribers.get(project_id, ())):
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                sub.overflowed = True
                self.unsubscribe(sub)
                log.warning("Closing a slow stream for %s", project_id)
        return event

    def subscribe(self, project_id: str) -> Subscription:
        sub = Subscription(project_id, asyncio.Queue(maxsize=self.queue_size))
        self._subscribers.setdefault(project_id, set()).add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        subs = self._subscribers.get(sub.project_id)
        if subs is not None:
            subs.discard(sub)
            if not subs:
                del self._subscribers[sub.project_id]

    def subscriber_count(self, project_id: str) -> int:
        return len(self._subscribers.get(project_id, ()))
