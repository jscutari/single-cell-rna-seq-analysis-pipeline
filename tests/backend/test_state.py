"""/state and LLM call routes: live views, durable results, file URLs, consistency."""

import json
import time

import pytest

from backend.projects import PRESET_ID
from shared.events import Event, EventType, emit
from shared.schemas import ChatMessage, CodeCell, Finding, Hypothesis, LLMCall, Role


def emit_and_wait(app, event: Event):
    """emit() from the test thread (not the app's loop) and wait for the store."""
    before = app.state.store.last_event_id
    emit(event)
    for _ in range(300):
        if app.state.store.last_event_id > before:
            return
        time.sleep(0.005)
    raise AssertionError("event not stored")


def state(client, pid=PRESET_ID):
    r = client.get(f"/api/projects/{pid}/state")
    assert r.status_code == 200
    return r.json()


def test_empty_state(client):
    s = state(client)
    assert s["project"]["id"] == PRESET_ID
    assert s["run"] == {"status": "idle", "stage": None}
    assert s["messages"] == [] and s["results"] is None
    assert s["live"] == {"brief": None, "hypotheses": [], "cells": {}, "findings": [], "llm_calls": []}
    assert s["last_event_id"] == 0


def test_state_unknown_project_is_404(client):
    assert client.get("/api/projects/nope/state").status_code == 404


def test_emitted_events_show_up_in_state(client, app):
    pid = PRESET_ID
    emit_and_wait(app, Event(type=EventType.chat_reply, project_id=pid,
                             payload=ChatMessage(project_id=pid, role=Role.assistant, content="Hello!")))
    emit_and_wait(app, Event(type=EventType.brief_updated, project_id=pid, payload={"project_id": pid, "organism": "human"}))
    emit_and_wait(app, Event(type=EventType.hypothesis_status, project_id=pid,
                             payload=Hypothesis(id="h1", project_id=pid, title="ISG up")))
    for index in (1, 0):
        emit_and_wait(app, Event(type=EventType.cell_finished, project_id=pid,
                                 payload=CodeCell(id=f"c{index}", hypothesis_id="h1", index=index, source="x")))
    emit_and_wait(app, Event(type=EventType.finding, project_id=pid,
                             payload=Finding(id="f1", hypothesis_id="h1", claim="ISG up", test="DESeq2")))
    emit_and_wait(app, Event(type=EventType.llm_call, project_id=pid,
                             payload=LLMCall(id="l1", project_id=pid, agent="critic", messages=[{"role": "user", "content": "long"}])))
    s = state(client)
    assert [m["content"] for m in s["messages"]] == ["Hello!"]
    assert s["live"]["brief"]["organism"] == "human"
    assert [h["title"] for h in s["live"]["hypotheses"]] == ["ISG up"]
    assert [c["index"] for c in s["live"]["cells"]["h1"]] == [0, 1]  # sorted by index
    assert s["live"]["findings"][0]["claim"] == "ISG up"
    assert "messages" not in s["live"]["llm_calls"][0]
    assert s["last_event_id"] == app.state.store.last_event_id == 7


def write_results(data_root, pid=PRESET_ID, **extra):
    state = {
        "project_id": pid, "stage": "analysis", "brief": None, "dataset": None, "background": "",
        "sources_searched": [], "hypotheses": [], "report": None,
        "findings": [{"finding": {"id": "f1"}, "hypothesis_title": "ISG up", "chart": None,
                      "figure": "hypotheses/h1/figures/cell001_0.png", "notebook": "hypotheses/h1/h1.ipynb"}],
        "files": [{"id": "a", "name": "report.md", "path": "report.md", "kind": "text"},
                  {"id": "b", "name": "weird name.png", "path": "hypotheses/h1/figures/weird name.png", "kind": "image"}],
        **extra,
    }
    (data_root / pid / "project_state.json").write_text(json.dumps(state))
    return state


def test_results_from_project_state_json_get_urls(client, data_root):
    write_results(data_root)
    results = state(client)["results"]
    assert results["stage"] == "analysis"
    assert [f["url"] for f in results["files"]] == [
        f"/api/projects/{PRESET_ID}/files/report.md",
        f"/api/projects/{PRESET_ID}/files/hypotheses/h1/figures/weird%20name.png",
    ]
    finding = results["findings"][0]
    assert finding["figure_url"] == f"/api/projects/{PRESET_ID}/files/hypotheses/h1/figures/cell001_0.png"
    assert finding["notebook_url"] == f"/api/projects/{PRESET_ID}/files/hypotheses/h1/h1.ipynb"


def test_results_without_figure_have_null_urls(client, data_root):
    write_results(data_root, findings=[{"finding": {"id": "f1"}, "figure": None, "notebook": None}], files=[])
    finding = state(client)["results"]["findings"][0]
    assert finding["figure_url"] is None and finding["notebook_url"] is None


@pytest.mark.parametrize("content", ["{broken", ""])
def test_unreadable_results_are_ignored(client, data_root, content):
    (data_root / PRESET_ID / "project_state.json").write_text(content)
    assert state(client)["results"] is None


def test_llm_call_routes(client, app):
    pid = PRESET_ID
    for i, (agent, hid) in enumerate([("critic", "h1"), ("coder", "h1"), ("critic", "h2")]):
        emit_and_wait(app, Event(type=EventType.llm_call, project_id=pid,
                                 payload=LLMCall(id=f"l{i}", project_id=pid, agent=agent, hypothesis_id=hid,
                                                 messages=[{"role": "user", "content": f"prompt {i}"}])))
    base = f"/api/projects/{pid}/llm_calls"
    assert [c["id"] for c in client.get(base).json()] == ["l0", "l1", "l2"]
    assert [c["id"] for c in client.get(base, params={"agent": "critic"}).json()] == ["l0", "l2"]
    assert [c["id"] for c in client.get(base, params={"hypothesis_id": "h1"}).json()] == ["l0", "l1"]
    assert [c["id"] for c in client.get(base, params={"agent": "critic", "hypothesis_id": "h2"}).json()] == ["l2"]
    full = client.get(f"{base}/l1").json()
    assert full["messages"] == [{"role": "user", "content": "prompt 1"}]
    assert client.get(f"{base}/missing").status_code == 404


def test_llm_call_from_another_project_is_404(client, app):
    other = client.post("/api/projects", json={"name": "Other"}).json()["id"]
    emit_and_wait(app, Event(type=EventType.llm_call, project_id=other,
                             payload=LLMCall(id="lx", project_id=other, agent="critic", messages=[])))
    assert client.get(f"/api/projects/{PRESET_ID}/llm_calls/lx").status_code == 404
    assert client.get(f"/api/projects/{other}/llm_calls/lx").status_code == 200


def test_llm_calls_for_project_without_events(client):
    assert client.get(f"/api/projects/{PRESET_ID}/llm_calls").json() == []
    assert client.get("/api/projects/nope/llm_calls").status_code == 404
