"""Live event stream: backlog + live handoff, heartbeats, trimming, overflow, HTTP behaviour."""

import asyncio
import json
import threading
import time

import httpx
import pytest

from backend.hub import EventHub
from backend.projects import PRESET_ID
from backend.sse import _start_after, event_stream, format_event
from backend.store import InMemoryStore
from shared.events import Event, EventType, emit
from shared.schemas import ChatMessage, LLMCall, Role


def parse(block: str) -> dict:
    fields = dict(line.split(": ", 1) for line in block.strip().splitlines() if not line.startswith(":"))
    return {"id": int(fields["id"]), "event": fields["event"], "data": json.loads(fields["data"])}


def stage(name: str) -> dict:
    return {"stage": name, "summary": ""}


@pytest.fixture
async def hub():
    h = EventHub(InMemoryStore(), queue_size=5)
    h.attach(asyncio.get_running_loop())
    yield h
    h.detach()


async def take(stream, n: int) -> list[str]:
    return [await asyncio.wait_for(stream.__anext__(), 1) for _ in range(n)]


# --- the generator ---

async def test_backlog_then_live_in_order(hub):
    for i in range(3):
        hub.publish("stage_done", "p1", stage(f"old{i}"))
    stream = event_stream(hub, "p1", after=1, heartbeat=5)
    retry, *backlog = await take(stream, 3)
    assert retry == "retry: 3000\n\n"
    assert [parse(b)["data"]["payload"]["stage"] for b in backlog] == ["old1", "old2"]
    hub.publish("stage_done", "p1", stage("live"))
    live = parse((await take(stream, 1))[0])
    assert (live["id"], live["event"], live["data"]["payload"]["stage"]) == (4, "stage_done", "live")
    await stream.aclose()


async def test_events_published_during_the_handoff_are_sent_once(hub):
    stream = event_stream(hub, "p1", after=0, heartbeat=5)
    await take(stream, 1)  # subscribed; backlog not read yet
    hub.publish("stage_done", "p1", stage("a"))  # lands in the store AND the queue
    hub.publish("stage_done", "p1", stage("b"))
    blocks = await take(stream, 2)
    hub.publish("stage_done", "p1", stage("c"))
    blocks += await take(stream, 1)
    assert [parse(b)["id"] for b in blocks] == [1, 2, 3]
    await stream.aclose()


async def test_other_projects_are_not_streamed(hub):
    stream = event_stream(hub, "p1", after=0, heartbeat=5)
    await take(stream, 1)
    hub.publish("stage_done", "p2", stage("other"))
    hub.publish("stage_done", "p1", stage("mine"))
    assert parse((await take(stream, 1))[0])["data"]["payload"]["stage"] == "mine"
    await stream.aclose()


async def test_heartbeat_when_idle(hub):
    stream = event_stream(hub, "p1", after=0, heartbeat=0.05)
    assert (await take(stream, 2))[1] == ": ping\n\n"
    await stream.aclose()


async def test_closing_the_stream_unsubscribes(hub):
    stream = event_stream(hub, "p1", after=0, heartbeat=5)
    await take(stream, 1)
    assert hub.subscriber_count("p1") == 1
    await stream.aclose()
    assert hub.subscriber_count("p1") == 0


async def test_slow_stream_ends_so_the_browser_reconnects(hub):
    stream = event_stream(hub, "p1", after=0, heartbeat=5)
    await take(stream, 1)
    for i in range(6):  # queue_size is 5
        hub.publish("stage_done", "p1", stage(f"s{i}"))
    blocks = []
    async for block in stream:  # drains what was sent before the overflow, then ends
        blocks.append(block)
    assert len(blocks) <= 6 and hub.subscriber_count("p1") == 0
    # Reconnecting from the last id received replays the rest from the store.
    last = parse(blocks[-1])["id"]
    rest = event_stream(hub, "p1", after=last, heartbeat=5)
    replay = await take(rest, 1 + 6 - last)
    assert [parse(b)["id"] for b in replay[1:]] == list(range(last + 1, 7))
    await rest.aclose()


def test_format_trims_llm_calls():
    store = InMemoryStore()
    call = LLMCall(id="l1", project_id="p1", agent="critic", messages=[{"role": "user", "content": "x" * 5000}])
    event = store.append("llm_call", "p1", call.model_dump(mode="json"))
    block = format_event(event)
    assert "x" * 100 not in block
    data = parse(block)["data"]
    assert data["payload"]["message_count"] == 1 and "messages" not in data["payload"]
    assert data["id"] == "1" and data["type"] == "llm_call" and data["project_id"] == "p1"


@pytest.mark.parametrize(
    ("header", "after", "now", "expected"),
    [(None, None, 9, 9), (None, 3, 9, 3), ("5", 3, 9, 5), ("-2", None, 9, 0), ("0", None, 9, 0)],
)
def test_start_position(header, after, now, expected):
    assert _start_after(header, after, now) == expected


# --- over HTTP (real uvicorn server) ---

def read_blocks(response, n: int, timeout: float = 3.0) -> list[dict]:
    blocks, buf, deadline = [], "", time.monotonic() + timeout
    for chunk in response.iter_text():
        buf += chunk
        while "\n\n" in buf:
            block, buf = buf.split("\n\n", 1)
            if block.startswith("id:"):
                blocks.append(parse(block))
        if len(blocks) >= n or time.monotonic() > deadline:
            break
    return blocks


def emit_later(*events: Event, delay: float = 0.2) -> None:
    def run():
        time.sleep(delay)
        for e in events:
            emit(e)

    threading.Thread(target=run, daemon=True).start()


def reply(content: str) -> Event:
    return Event(type=EventType.chat_reply, project_id=PRESET_ID,
                 payload=ChatMessage(project_id=PRESET_ID, role=Role.assistant, content=content))


def test_http_stream_headers_and_live_events(live_server):
    app, base = live_server
    with httpx.Client(base_url=base, timeout=5) as http:
        with http.stream("GET", f"/api/projects/{PRESET_ID}/events") as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            assert r.headers["cache-control"] == "no-cache"
            assert r.headers["x-accel-buffering"] == "no"
            emit_later(reply("one"), reply("two"))
            blocks = read_blocks(r, 2)
    assert [b["data"]["payload"]["content"] for b in blocks] == ["one", "two"]
    assert [b["event"] for b in blocks] == ["chat_reply", "chat_reply"]


def test_http_stream_replays_from_last_event_id(live_server):
    app, base = live_server
    for i in range(4):
        emit(reply(f"m{i}"))
    deadline = time.monotonic() + 2
    while app.state.store.last_event_id < 4 and time.monotonic() < deadline:
        time.sleep(0.01)
    with httpx.Client(base_url=base, timeout=5) as http:
        # Last-Event-ID (sent by a reconnecting browser) wins over ?after.
        with http.stream("GET", f"/api/projects/{PRESET_ID}/events?after=0", headers={"Last-Event-ID": "2"}) as r:
            assert [b["data"]["payload"]["content"] for b in read_blocks(r, 2)] == ["m2", "m3"]
        with http.stream("GET", f"/api/projects/{PRESET_ID}/events?after=1") as r:
            assert [b["id"] for b in read_blocks(r, 3)] == [2, 3, 4]


def test_http_stream_starts_from_now_by_default(live_server):
    app, base = live_server
    emit(reply("before"))
    time.sleep(0.1)
    with httpx.Client(base_url=base, timeout=5) as http:
        with http.stream("GET", f"/api/projects/{PRESET_ID}/events") as r:
            emit_later(reply("after"))
            blocks = read_blocks(r, 1)
    assert [b["data"]["payload"]["content"] for b in blocks] == ["after"]


def test_http_disconnect_removes_the_subscriber(live_server):
    app, base = live_server
    with httpx.Client(base_url=base, timeout=5) as http:
        with http.stream("GET", f"/api/projects/{PRESET_ID}/events") as r:
            next(r.iter_text())  # connected
            assert app.state.hub.subscriber_count(PRESET_ID) == 1
    deadline = time.monotonic() + 3
    while app.state.hub.subscriber_count(PRESET_ID) and time.monotonic() < deadline:
        emit(reply("nudge"))  # the server notices the closed socket on its next write
        time.sleep(0.1)
    assert app.state.hub.subscriber_count(PRESET_ID) == 0


@pytest.mark.parametrize(
    ("path", "headers", "status"),
    [("/api/projects/nope/events", {}, 404),
     (f"/api/projects/{PRESET_ID}/events?after=-1", {}, 400),
     (f"/api/projects/{PRESET_ID}/events", {"Last-Event-ID": "abc"}, 400)],
)
def test_http_stream_errors(live_server, path, headers, status):
    _, base = live_server
    assert httpx.get(base + path, headers=headers, timeout=5).status_code == status
