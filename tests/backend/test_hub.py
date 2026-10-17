"""backend/hub.py: the emit() sink, thread safety, fan-out and slow subscribers."""

import asyncio
import threading

import pytest

from backend.hub import EventHub
from backend.store import InMemoryStore
from shared import events as events_module
from shared.events import Event, EventType, emit
from shared.schemas import ChatMessage, Role


def reply(project_id="p1", content="hi"):
    return Event(type=EventType.chat_reply, project_id=project_id,
                 payload=ChatMessage(project_id=project_id, role=Role.assistant, content=content))


@pytest.fixture
async def hub():
    h = EventHub(InMemoryStore(), queue_size=3)
    h.attach(asyncio.get_running_loop())
    yield h
    h.detach()


async def test_emit_on_the_loop_is_stored_immediately(hub):
    emit(reply(content="now"))
    assert [m["content"] for m in hub.store.messages("p1")] == ["now"]


async def test_emit_from_threads_is_safe_and_ordered_per_thread(hub):
    def worker(n):
        for i in range(200):
            emit(reply(project_id=f"t{n}", content=str(i)))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        await asyncio.to_thread(t.join)
    for _ in range(200):  # let the loop run the queued callbacks
        if hub.store.last_event_id == 1600:
            break
        await asyncio.sleep(0.01)
    assert hub.store.last_event_id == 1600
    for n in range(8):
        assert [m["content"] for m in hub.store.messages(f"t{n}")] == [str(i) for i in range(200)]
    ids = [e.id for n in range(8) for e in hub.store.events_after(f"t{n}", 0)]
    assert sorted(ids) == list(range(1, 1601))


async def test_publish_fans_out_to_the_projects_subscribers_only(hub):
    a, b, other = hub.subscribe("p1"), hub.subscribe("p1"), hub.subscribe("p2")
    event = hub.publish("stage_done", "p1", {"stage": "intake", "summary": ""})
    assert a.queue.get_nowait() is event and b.queue.get_nowait() is event
    assert other.queue.empty()


async def test_unsubscribe_stops_delivery(hub):
    sub = hub.subscribe("p1")
    hub.unsubscribe(sub)
    hub.unsubscribe(sub)  # twice is harmless
    hub.publish("stage_done", "p1", {"stage": "intake", "summary": ""})
    assert sub.queue.empty() and hub.subscriber_count("p1") == 0


async def test_slow_subscriber_is_closed_not_buffered_forever(hub):
    slow, fast = hub.subscribe("p1"), hub.subscribe("p1")
    for i in range(4):  # queue_size is 3
        hub.publish("stage_done", "p1", {"stage": f"s{i}", "summary": ""})
        if not fast.queue.empty():
            fast.queue.get_nowait()
    assert slow.overflowed and not fast.overflowed
    assert hub.subscriber_count("p1") == 1
    assert hub.store.last_event_id == 4  # nothing lost from the store


async def test_duplicate_user_message_is_not_fanned_out(hub):
    sub = hub.subscribe("p1")
    msg = {"id": "m1", "project_id": "p1", "role": "user", "content": "hi", "created_at": "x"}
    assert hub.publish("user_message", "p1", msg) is not None
    assert hub.publish("user_message", "p1", msg) is None
    assert sub.queue.qsize() == 1


async def test_bad_event_from_a_thread_does_not_break_the_loop(hub, caplog):
    hub.loop.call_soon_threadsafe(hub._publish_safely, "hypothesis_status", "p1", {"no": "id"}, None)
    await asyncio.sleep(0.05)
    assert "Could not publish" in caplog.text
    emit(reply(content="still works"))
    assert hub.store.messages("p1")[-1]["content"] == "still works"


def test_detach_restores_the_console_sink(capsys):
    h = EventHub(InMemoryStore())
    loop = asyncio.new_event_loop()
    h.attach(loop)
    assert events_module._sink == h.ingest
    h.detach()
    loop.close()
    emit(reply(content="to console"))
    assert "to console" in capsys.readouterr().out
    assert h.store.last_event_id == 0


def test_detach_does_not_remove_a_newer_hubs_sink():
    old, new = EventHub(InMemoryStore()), EventHub(InMemoryStore())
    loop = asyncio.new_event_loop()
    old.attach(loop)
    new.attach(loop)  # a second app started before the first finished shutting down
    old.detach()
    assert events_module._sink == new.ingest
    new.detach()
    assert events_module._sink == events_module._print_sink
    loop.close()


def test_ingest_without_a_loop_is_dropped_with_a_warning(caplog):
    h = EventHub(InMemoryStore())
    h.ingest(reply())
    assert h.store.last_event_id == 0 and "hub not attached" in caplog.text
