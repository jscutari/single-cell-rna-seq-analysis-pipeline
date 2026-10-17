"""Store backed by Postgres: the in-memory views plus a durable event log.

Reads are served from memory exactly like InMemoryStore. Every appended event is
also queued for a background writer that commits batches (every
`write_interval` seconds or `write_batch` events) in one transaction, so the
live stream never waits on the database. On startup the saved events are
replayed into memory, so chat, trace and run state survive a restart.

Full LLM calls (with prompts) go to the llm_calls table; events keep only the
summary. `flush()` waits until everything appended so far is committed; the
chat route uses it so a message the user sees as sent is never lost.
"""

import asyncio
import logging
from datetime import datetime

import asyncpg

from backend import db
from backend.config import Settings
from backend.store import InMemoryStore, StoredEvent, summarize_llm_call

log = logging.getLogger("scrap.backend.pg_store")

MAX_BACKOFF = 5.0
MAX_PENDING = 200_000  # beyond this, the oldest unsaved events are dropped (logged loudly)

INSERT_EVENT = "INSERT INTO events (id, project_id, type, payload, created_at) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (id) DO NOTHING"
INSERT_LLM_CALL = """
INSERT INTO llm_calls (id, project_id, hypothesis_id, agent, reasoning, output, messages, tool_calls,
                       tokens_in, tokens_out, latency_ms, parent_call_id, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
ON CONFLICT (id) DO NOTHING"""


def _ts(value: str | None) -> datetime:
    return datetime.fromisoformat(value) if value else datetime.now().astimezone()


class PgStore(InMemoryStore):
    def __init__(self, pool: asyncpg.Pool, write_interval: float = 0.1, write_batch: int = 200) -> None:
        super().__init__()
        self.pool = pool
        self.write_interval = write_interval
        self.write_batch = write_batch
        self._pending: list[StoredEvent] = []
        self._persisted_id = 0
        self._failures = 0
        self._healthy = True
        self._wake = asyncio.Event()
        self._saved = asyncio.Condition()
        self._task: asyncio.Task | None = None
        self._closing = False

    @classmethod
    async def open(cls, settings: Settings) -> "PgStore":
        """Connect (waiting for the container), apply the schema, replay saved events, start writing."""
        pool = await db.connect(settings.database_url, timeout=settings.db_connect_timeout)
        try:
            await db.apply_schema(pool)
            store = cls(pool, settings.write_interval, settings.write_batch)
            await store.load()
        except BaseException:
            await pool.close()
            raise
        store.start()
        return store

    # --- startup ---

    async def load(self) -> int:
        """Replay every saved event into memory (ids preserved). Returns how many."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, project_id, type, payload, created_at FROM events ORDER BY id")
        for r in rows:
            self.restore(StoredEvent(r["id"], r["type"], r["project_id"], r["payload"], r["created_at"].isoformat()))
        self._persisted_id = self.last_event_id
        log.info("Restored %d events from Postgres", len(rows))
        return len(rows)

    def start(self) -> None:
        self._task = asyncio.create_task(self._writer(), name="pg-writer")

    # --- writes ---

    def append(self, type, project_id, payload, created_at=None):
        event = super().append(type, project_id, payload, created_at)
        if event is not None:
            self._pending.append(event)
            if len(self._pending) > MAX_PENDING:
                dropped = self._pending[: len(self._pending) - MAX_PENDING]
                del self._pending[: len(dropped)]
                log.error("Database unreachable for too long: dropped %d unsaved events (ids %d-%d)",
                          len(dropped), dropped[0].id, dropped[-1].id)
            if len(self._pending) >= self.write_batch:
                self._wake.set()
        return event

    async def _writer(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.write_interval)
            except TimeoutError:
                pass
            self._wake.clear()
            if not await self._write_once() and not self._closing:
                await asyncio.sleep(min(MAX_BACKOFF, 0.1 * 2 ** min(self._failures, 6)))
            if self._closing and not self._pending:
                return

    async def _write_once(self) -> bool:
        """Commit one batch. False if the database refused it (the batch stays queued)."""
        if not self._pending:
            return True
        batch = self._pending[: self.write_batch]
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                await conn.executemany(INSERT_EVENT, [
                    (e.id, e.project_id, e.type, summarize_llm_call(e.payload) if e.type == "llm_call" else e.payload,
                     _ts(e.created_at)) for e in batch])
                calls = [e.payload for e in batch if e.type == "llm_call"]
                if calls:
                    await conn.executemany(INSERT_LLM_CALL, [
                        (c["id"], c["project_id"], c.get("hypothesis_id"), c.get("agent", ""), c.get("reasoning"),
                         c.get("output", ""), c.get("messages") or [], c.get("tool_calls") or [], c.get("tokens_in", 0),
                         c.get("tokens_out", 0), c.get("latency_ms", 0), c.get("parent_call_id"), _ts(c.get("created_at")))
                        for c in calls])
        except Exception as error:  # connection lost, server down, ...
            self._failures += 1
            if self._healthy or self._failures % 20 == 0:
                log.error("Could not save %d events to Postgres (attempt %d): %s", len(batch), self._failures, error)
            self._healthy = False
            return False
        del self._pending[: len(batch)]
        if not self._healthy:
            log.warning("Postgres is back; saving resumed")
        self._failures = 0
        self._healthy = True
        async with self._saved:
            self._persisted_id = batch[-1].id
            self._saved.notify_all()
        if self._pending:
            self._wake.set()  # more queued: keep going without waiting
        return True

    async def flush(self, timeout: float = 5.0) -> None:
        """Wait until everything appended so far is saved. TimeoutError if the database is down."""
        target = self.last_event_id
        self._wake.set()
        async with self._saved:
            await asyncio.wait_for(self._saved.wait_for(lambda: self._persisted_id >= target), timeout)

    async def close(self) -> None:
        """Save what's left (best effort) and close the pool."""
        self._closing = True
        self._wake.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except TimeoutError:
                self._task.cancel()
                log.error("Shutting down with %d unsaved events (database unreachable)", len(self._pending))
        await self.pool.close()

    # --- reads that may need the database ---

    async def fetch_llm_call(self, call_id: str) -> dict | None:
        call = self.llm_call(call_id)  # appended in this process
        if call is not None:
            return call
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM llm_calls WHERE id = $1", call_id)
        if row is None:
            return None
        call = dict(row)
        call["created_at"] = call["created_at"].isoformat()
        return call

    @property
    def db_status(self) -> str:
        return "ok" if self._healthy else "down"

    @property
    def unsaved(self) -> int:
        return len(self._pending)
