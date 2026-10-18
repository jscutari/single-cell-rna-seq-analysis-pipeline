"""backend/pg_store.py: batched writes, outages and recovery, restart rebuild, LLM calls."""

import asyncio
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import replace

import asyncpg
import pytest
from fastapi.testclient import TestClient

from backend import pg_store
from backend.config import Settings
from backend.db import DatabaseUnavailable, _init_connection
from backend.main import create_app
from backend.pg_store import PgStore
from backend.projects import PRESET_ID
from shared.events import Event, EventType, emit
from shared.schemas import ChatMessage, LLMCall, Role

BASE = f"/api/projects/{PRESET_ID}"


# --- unit tests with a fake pool (no Docker) ---

class FakePool:
    """Records committed batches; can be switched off to simulate an outage."""

    def __init__(self) -> None:
        self.down = False
        self.events: list[tuple] = []
        self.calls: list[tuple] = []
        self.transactions = 0
        self.closed = False

    @asynccontextmanager
    async def acquire(self):
        if self.down:
            raise OSError("connection refused")
        yield self

    @asynccontextmanager
    async def transaction(self):
        staged_e, staged_c = [], []
        self._stage = (staged_e, staged_c)
        yield
        self.events += staged_e
        self.calls += staged_c
        self.transactions += 1

    async def executemany(self, sql, rows):
        (self._stage[0] if "INTO events" in sql else self._stage[1]).extend(rows)

    async def close(self):
        self.closed = True


def make_store(pool, **kw) -> PgStore:
    store = PgStore(pool, write_interval=kw.get("interval", 0.01), write_batch=kw.get("batch", 200))
    store.start()
    return store


def stage(i: int) -> dict:
    return {"stage": f"s{i}", "summary": ""}


async def test_events_are_saved_in_order_in_batches():
    pool = FakePool()
    store = make_store(pool)
    for i in range(50):
        store.append("stage_done", "p1", stage(i))
    await store.flush()
    assert [row[0] for row in pool.events] == list(range(1, 51))
    assert pool.transactions <= 5  # batched, not one transaction per event
    await store.close()
    assert pool.closed


async def test_a_full_batch_is_written_without_waiting_for_the_interval():
    pool = FakePool()
    store = make_store(pool, interval=60, batch=5)
    for i in range(5):
        store.append("stage_done", "p1", stage(i))
    for _ in range(100):
        if len(pool.events) == 5:
            break
        await asyncio.sleep(0.01)
    assert len(pool.events) == 5
    await store.close()


async def test_llm_calls_go_to_their_own_table_and_events_keep_a_summary():
    pool = FakePool()
    store = make_store(pool)
    call = LLMCall(id="l1", project_id="p1", agent="critic", messages=[{"role": "user", "content": "long prompt"}],
                   tokens_in=10, tokens_out=3, latency_ms=42).model_dump(mode="json")
    store.append("llm_call", "p1", call)
    await store.flush()
    (_, _, type_, payload, _), = pool.events
    assert type_ == "llm_call" and "messages" not in payload and payload["message_count"] == 1
    (row,) = pool.calls
    assert row[0] == "l1" and row[3] == "critic" and row[6] == [{"role": "user", "content": "long prompt"}]
    assert (row[8], row[9], row[10]) == (10, 3, 42)
    await store.close()


async def test_outage_keeps_events_queued_reports_down_then_catches_up(caplog):
    pool = FakePool()
    store = make_store(pool)
    pool.down = True
    for i in range(3):
        store.append("stage_done", "p1", stage(i))
    with pytest.raises(TimeoutError):
        await store.flush(timeout=0.3)
    assert store.db_status == "down" and store.unsaved == 3
    assert "Could not save 3 events" in caplog.text
    store.append("stage_done", "p1", stage(3))  # the app keeps working in memory
    assert store.last_event_id == 4
    pool.down = False
    await store.flush(timeout=10)
    assert [row[0] for row in pool.events] == [1, 2, 3, 4]
    assert store.db_status == "ok" and store.unsaved == 0
    assert "saving resumed" in caplog.text
    await store.close()


async def test_close_saves_what_is_left():
    pool = FakePool()
    store = make_store(pool, interval=60)
    store.append("stage_done", "p1", stage(0))
    await store.close()
    assert len(pool.events) == 1


async def test_close_gives_up_when_the_database_stays_down(caplog, monkeypatch):
    pool = FakePool()
    pool.down = True
    store = make_store(pool)
    store.append("stage_done", "p1", stage(0))
    original = asyncio.wait_for

    async def short_wait(aw, timeout):
        return await original(aw, timeout=min(timeout, 0.3))

    monkeypatch.setattr(pg_store.asyncio, "wait_for", short_wait)
    await store.close()
    assert "Shutting down with 1 unsaved events" in caplog.text


async def test_too_many_unsaved_events_drops_the_oldest_loudly(monkeypatch, caplog):
    monkeypatch.setattr(pg_store, "MAX_PENDING", 3)
    pool = FakePool()
    pool.down = True
    store = make_store(pool)
    for i in range(5):
        store.append("stage_done", "p1", stage(i))
    assert [e.id for e in store._pending] == [3, 4, 5]
    assert "dropped 1 unsaved events" in caplog.text
    assert store.last_event_id == 5  # still in memory for this session
    store._task.cancel()


async def test_duplicate_user_messages_are_not_queued_twice():
    pool = FakePool()
    store = make_store(pool)
    msg = {"id": "m1", "project_id": "p1", "role": "user", "content": "hi", "created_at": "2026-10-17T00:00:00+00:00"}
    store.append("user_message", "p1", msg)
    assert store.append("user_message", "p1", msg) is None
    await store.flush()
    assert len(pool.events) == 1
    await store.close()


# --- against the real Postgres ---

@pytest.fixture
def pg_settings(data_root, pg_url) -> Settings:
    return Settings(data_root=data_root, agents="fake", heartbeat_seconds=0.2, store="postgres",
                    database_url=pg_url, write_interval=0.02, db_connect_timeout=3)


async def rows(url: str, sql: str):
    conn = await asyncpg.connect(url)
    await _init_connection(conn)  # jsonb as Python objects, like the app
    try:
        return await conn.fetch(sql)
    finally:
        await conn.close()


def emit_and_wait(app, event: Event):
    before = app.state.store.last_event_id
    emit(event)
    deadline = time.monotonic() + 3
    while app.state.store.last_event_id <= before and time.monotonic() < deadline:
        time.sleep(0.005)


@pytest.mark.db
def test_everything_survives_a_restart(pg_settings, orchestrator, pg_url):
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        c.post(f"{BASE}/messages", json={"content": "Compare COVID vs healthy", "id": "user_msg_00001"})
        emit_and_wait(c.app, Event(type=EventType.chat_reply, project_id=PRESET_ID,
                                   payload=ChatMessage(project_id=PRESET_ID, role=Role.assistant, content="On it.")))
        emit_and_wait(c.app, Event(type=EventType.llm_call, project_id=PRESET_ID,
                                   payload=LLMCall(id="call_1", project_id=PRESET_ID, agent="intake",
                                                   messages=[{"role": "user", "content": "the full prompt"}])))
        emit_and_wait(c.app, Event(type=EventType.hypothesis_status, project_id=PRESET_ID,
                                   payload={"id": "h1", "project_id": PRESET_ID, "title": "ISG up", "rationale": "",
                                            "plan_steps": [], "status": "approved"}))
        before = c.get(f"{BASE}/state").json()
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:  # a new process, same database
        after = c.get(f"{BASE}/state").json()
        assert after["messages"] == before["messages"]
        assert [m["content"] for m in after["messages"]] == ["Compare COVID vs healthy", "On it."]
        assert after["live"]["hypotheses"] == before["live"]["hypotheses"]
        assert after["live"]["llm_calls"] == before["live"]["llm_calls"]
        # The first message started a run; the restart marked it stopped (one new event).
        assert after["run"]["status"] == "stopped"
        assert after["last_event_id"] == before["last_event_id"] + 1
        # The full prompt comes back from the llm_calls table.
        full = c.get(f"{BASE}/llm_calls/call_1").json()
        assert full["messages"] == [{"role": "user", "content": "the full prompt"}] and full["agent"] == "intake"
        # New events continue the id sequence.
        emit_and_wait(c.app, Event(type=EventType.stage_done, project_id=PRESET_ID, payload=stage(9)))
        assert c.app.state.store.last_event_id == before["last_event_id"] + 2
    ids = [r["id"] for r in asyncio.run(rows(pg_url, "SELECT id FROM events ORDER BY id"))]
    assert ids == list(range(1, len(ids) + 1))


@pytest.mark.db
def test_stream_replay_works_across_a_restart(pg_settings, orchestrator):
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        for i in range(3):
            emit_and_wait(c.app, Event(type=EventType.stage_done, project_id=PRESET_ID, payload=stage(i)))
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        events = c.app.state.store.events_after(PRESET_ID, 1)
        assert [e.payload["stage"] for e in events] == ["s1", "s2"]


@pytest.mark.db
def test_message_is_saved_before_the_server_says_sent(pg_settings, orchestrator, pg_url):
    with TestClient(create_app(replace(pg_settings, write_interval=5.0), orchestrator=orchestrator)) as c:
        assert c.post(f"{BASE}/messages", json={"content": "keep me", "id": "durable_msg_1"}).status_code == 204
        saved = asyncio.run(rows(pg_url, "SELECT payload FROM events WHERE type = 'user_message'"))
        assert [r["payload"]["content"] for r in saved] == ["keep me"]


@pytest.mark.db
def test_message_when_the_database_is_down_is_503_and_a_retry_delivers_once(pg_settings, orchestrator):
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        store = c.app.state.store
        real_flush = store.flush

        async def failing_flush(timeout=5.0):
            raise TimeoutError

        store.flush = failing_flush
        body = {"content": "hello", "id": "retry_msg_0001"}
        r = c.post(f"{BASE}/messages", json=body)
        assert r.status_code == 503 and "database is unavailable" in r.json()["detail"]
        assert "handle_user_message" not in orchestrator.names()
        store.flush = real_flush
        assert c.post(f"{BASE}/messages", json=body).status_code == 204
        assert c.post(f"{BASE}/messages", json=body).status_code == 204
        assert orchestrator.names().count("handle_user_message") == 1
        assert [m["content"] for m in c.get(f"{BASE}/messages").json()] == ["hello"]


@pytest.mark.db
def test_concurrent_events_are_saved_complete_and_ordered(pg_settings, orchestrator, pg_url):
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        def worker(n):
            for i in range(200):
                emit(Event(type=EventType.stage_done, project_id=f"t{n}", payload={"stage": str(i), "summary": ""}))

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        deadline = time.monotonic() + 5
        while c.app.state.store.last_event_id < 1600 and time.monotonic() < deadline:
            time.sleep(0.01)
    saved = asyncio.run(rows(pg_url, "SELECT id, project_id, payload FROM events ORDER BY id"))
    assert [r["id"] for r in saved] == list(range(1, 1601))
    for n in range(8):
        assert [r["payload"]["stage"] for r in saved if r["project_id"] == f"t{n}"] == [str(i) for i in range(200)]


@pytest.mark.db
def test_llm_calls_are_queryable_with_sql(pg_settings, orchestrator, pg_url):
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        for i, (agent, hid, tokens) in enumerate([("critic", "h1", 100), ("coder", "h1", 50), ("critic", "h2", 30)]):
            emit_and_wait(c.app, Event(type=EventType.llm_call, project_id=PRESET_ID,
                                       payload=LLMCall(id=f"c{i}", project_id=PRESET_ID, agent=agent, hypothesis_id=hid,
                                                       messages=[], tokens_in=tokens)))
    totals = asyncio.run(rows(pg_url, "SELECT agent, sum(tokens_in) AS t FROM llm_calls GROUP BY agent ORDER BY agent"))
    assert [(r["agent"], r["t"]) for r in totals] == [("coder", 50), ("critic", 130)]


@pytest.mark.db
def test_health_reports_a_database_outage(pg_settings, orchestrator):
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        c.app.state.store._healthy = False
        assert c.get("/api/health").json()["db"] == "down"


def test_startup_refuses_when_postgres_is_unreachable(data_root, orchestrator):
    settings = Settings(data_root=data_root, store="postgres", database_url="postgresql://u:p@127.0.0.1:1/x",
                        db_connect_timeout=0.5)
    with pytest.raises(DatabaseUnavailable, match="Is it running"):
        with TestClient(create_app(settings, orchestrator=orchestrator)):
            pass


def test_startup_refuses_without_a_database_url(data_root, orchestrator):
    with pytest.raises(DatabaseUnavailable, match="DATABASE_URL is not set"):
        with TestClient(create_app(Settings(data_root=data_root, store="postgres"), orchestrator=orchestrator)):
            pass


def test_unknown_store_is_rejected(data_root, orchestrator):
    with pytest.raises(ValueError, match="SCRAP_STORE"):
        with TestClient(create_app(Settings(data_root=data_root, store="sqlite"), orchestrator=orchestrator)):
            pass
