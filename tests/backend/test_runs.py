"""Run control and chat: one active run, idempotency, auto-start, retries, restart rules."""

import json

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.projects import PRESET_ID
from shared.events import Event, EventType, emit

BASE = f"/api/projects/{PRESET_ID}"


class EmittingOrchestrator:
    """Behaves like the real one: stop_run reports 'stopped' when a run exists."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.started: set[str] = set()

    async def start_run(self, pid):
        self.calls.append(("start_run", pid))
        self.started.add(pid)

    async def handle_user_message(self, pid, text):
        if pid not in self.started:
            raise KeyError(pid)
        self.calls.append(("handle_user_message", pid, text))

    async def stop_run(self, pid):
        self.calls.append(("stop_run", pid))
        if pid in self.started:
            emit(Event(type=EventType.stage_done, project_id=pid, payload={"stage": "stopped", "summary": ""}))


@pytest.fixture
def orch():
    return EmittingOrchestrator()


@pytest.fixture
def c(settings, orch):
    with TestClient(create_app(settings, orchestrator=orch)) as client:
        yield client


def other_project(c) -> str:
    return c.post("/api/projects", json={"name": "Other"}).json()["id"]


def status(c, pid=PRESET_ID) -> str:
    return c.get(f"/api/projects/{pid}/state").json()["run"]["status"]


# --- start / stop ---

def test_start_runs_the_orchestrator(c, orch):
    assert c.post(f"{BASE}/start").json() == {"status": "running"}
    assert orch.calls == [("start_run", PRESET_ID)]
    assert status(c) == "running"


def test_start_twice_is_a_no_op(c, orch):
    c.post(f"{BASE}/start")
    assert c.post(f"{BASE}/start").json() == {"status": "running"}
    assert orch.calls == [("start_run", PRESET_ID)]


def test_only_one_active_run(c, orch):
    c.post(f"{BASE}/start")
    other = other_project(c)
    r = c.post(f"/api/projects/{other}/start")
    assert r.status_code == 409
    assert r.json()["detail"]["running_project_id"] == PRESET_ID
    assert ("start_run", other) not in orch.calls


def test_another_run_can_start_after_the_first_ends(c, orch):
    c.post(f"{BASE}/start")
    c.post(f"{BASE}/stop")
    other = other_project(c)
    assert c.post(f"/api/projects/{other}/start").status_code == 200


@pytest.mark.parametrize("final_stage", ["report", "failed", "stopped"])
def test_finished_runs_free_the_slot(c, final_stage):
    c.post(f"{BASE}/start")
    c.app.state.hub.publish("stage_done", PRESET_ID, {"stage": final_stage, "summary": ""})
    assert c.post(f"/api/projects/{other_project(c)}/start").status_code == 200


def test_restarting_after_a_stop(c, orch):
    c.post(f"{BASE}/start")
    c.post(f"{BASE}/stop")
    assert c.post(f"{BASE}/start").json() == {"status": "running"}
    assert [x[0] for x in orch.calls] == ["start_run", "stop_run", "start_run"]


def test_stop(c, orch):
    c.post(f"{BASE}/start")
    assert c.post(f"{BASE}/stop").json() == {"status": "stopped"}
    assert orch.calls[-1] == ("stop_run", PRESET_ID)


def test_stop_when_not_running_is_a_no_op(c, orch):
    assert c.post(f"{BASE}/stop").json() == {"status": "idle"}
    assert orch.calls == []


def test_stop_marks_stopped_even_if_the_orchestrator_had_no_run(c, orch):
    c.app.state.hub.publish("run_status", PRESET_ID, {"status": "running"})  # e.g. state from before a restart
    assert c.post(f"{BASE}/stop").json() == {"status": "stopped"}


def test_start_failure_marks_failed_and_returns_502(c, orch):
    async def boom(pid):
        raise RuntimeError("docker not running")

    orch.start_run = boom
    r = c.post(f"{BASE}/start")
    assert r.status_code == 502 and "docker not running" in r.json()["detail"]
    assert status(c) == "failed"


@pytest.mark.parametrize("path", ["start", "stop", "messages"])
def test_unknown_project_is_404(c, path):
    method = c.get if path == "messages" else c.post
    assert method(f"/api/projects/nope/{path}").status_code == 404


# --- chat ---

def test_first_message_starts_the_run_then_delivers(c, orch):
    r = c.post(f"{BASE}/messages", json={"content": "  Compare COVID vs healthy  ", "id": "msg_00000001"})
    assert r.status_code == 204
    assert orch.calls == [("start_run", PRESET_ID), ("handle_user_message", PRESET_ID, "Compare COVID vs healthy")]
    messages = c.get(f"{BASE}/messages").json()
    assert [(m["id"], m["role"], m["content"]) for m in messages] == [("msg_00000001", "user", "Compare COVID vs healthy")]


def test_message_during_a_run_is_delivered_without_restarting(c, orch):
    c.post(f"{BASE}/start")
    c.post(f"{BASE}/messages", json={"content": "hi"})
    assert [x[0] for x in orch.calls] == ["start_run", "handle_user_message"]


def test_message_after_the_run_finished_goes_to_qa(c, orch):
    c.post(f"{BASE}/start")
    c.app.state.hub.publish("stage_done", PRESET_ID, {"stage": "report", "summary": ""})
    assert c.post(f"{BASE}/messages", json={"content": "Which finding is strongest?"}).status_code == 204
    assert orch.calls[-1][0] == "handle_user_message"


def test_retried_message_is_stored_and_delivered_once(c, orch):
    body = {"content": "hello", "id": "retry_key_123"}
    assert c.post(f"{BASE}/messages", json=body).status_code == 204
    assert c.post(f"{BASE}/messages", json=body).status_code == 204
    assert len(c.get(f"{BASE}/messages").json()) == 1
    assert [x[0] for x in orch.calls].count("handle_user_message") == 1


def test_server_generates_an_id_when_none_is_given(c):
    c.post(f"{BASE}/messages", json={"content": "a"})
    c.post(f"{BASE}/messages", json={"content": "a"})  # same text, different messages
    ids = [m["id"] for m in c.get(f"{BASE}/messages").json()]
    assert len(set(ids)) == 2 and all(len(i) == 32 for i in ids)


def test_history_interleaves_user_messages_and_replies(c):
    c.post(f"{BASE}/messages", json={"content": "question"})
    c.app.state.hub.publish("chat_reply", PRESET_ID, {"id": "r1", "project_id": PRESET_ID, "role": "assistant",
                                                       "content": "answer", "created_at": "x"})
    c.post(f"{BASE}/messages", json={"content": "follow-up"})
    assert [m["content"] for m in c.get(f"{BASE}/messages").json()] == ["question", "answer", "follow-up"]


@pytest.mark.parametrize(
    "body",
    [{}, {"content": ""}, {"content": "   "}, {"content": "x" * 10_001}, {"content": "ok", "id": "short"},
     {"content": "ok", "id": "has spaces in it"}, {"content": "ok", "id": "x" * 65}, {"content": 3}],
)
def test_invalid_messages_are_rejected(c, orch, body):
    assert c.post(f"{BASE}/messages", json=body).status_code == 422
    assert orch.calls == []


@pytest.mark.parametrize("final", ["stopped", "failed"])
def test_chatting_with_a_stopped_or_failed_run_is_409(c, orch, final):
    c.post(f"{BASE}/start")
    c.app.state.hub.publish("stage_done", PRESET_ID, {"stage": final, "summary": ""})
    r = c.post(f"{BASE}/messages", json={"content": "hi"})
    assert r.status_code == 409 and final in r.json()["detail"]
    assert c.get(f"{BASE}/messages").json() == []  # not stored


def test_chatting_with_a_run_from_before_a_restart_is_409(c, orch, data_root):
    (data_root / PRESET_ID / "project_state.json").write_text(json.dumps({"stage": "report", "files": [], "findings": []}))
    r = c.post(f"{BASE}/messages", json={"content": "hi"})
    assert r.status_code == 409 and "Start a new run" in r.json()["detail"]
    assert orch.calls == []


def test_first_message_while_another_project_runs_is_409(c, orch):
    other = other_project(c)
    c.post(f"/api/projects/{other}/start")
    assert c.post(f"{BASE}/messages", json={"content": "hi"}).status_code == 409
    assert c.get(f"{BASE}/messages").json() == []


def test_orchestrator_without_the_run_is_409(c, orch):
    c.app.state.hub.publish("run_status", PRESET_ID, {"status": "running"})  # backend thinks it runs; orchestrator lost it
    r = c.post(f"{BASE}/messages", json={"content": "hi"})
    assert r.status_code == 409


def test_orchestrator_error_is_502_but_the_message_is_kept(c, orch):
    async def boom(pid, text):
        raise RuntimeError("vLLM down")

    c.post(f"{BASE}/start")
    orch.handle_user_message = boom
    r = c.post(f"{BASE}/messages", json={"content": "hi"})
    assert r.status_code == 502 and "vLLM down" in r.json()["detail"]
    assert [m["content"] for m in c.get(f"{BASE}/messages").json()] == ["hi"]


def test_user_messages_and_run_status_are_streamed(c):
    c.post(f"{BASE}/messages", json={"content": "hi"})
    types = [e.type for e in c.app.state.store.events_after(PRESET_ID, 0)]
    assert types == ["user_message", "run_status"]


def test_unknown_agents_mode_fails_at_startup(settings):
    from dataclasses import replace

    with pytest.raises(ValueError, match="SCRAP_AGENTS"):
        with TestClient(create_app(replace(settings, agents="bogus"))):
            pass
