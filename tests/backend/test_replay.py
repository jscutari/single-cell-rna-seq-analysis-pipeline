"""Replay mode: a recorded run through the real backend, and recording one over HTTP."""

import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.dev import record as recorder
from backend.dev.replay_orchestrator import DEFAULT_RECORDING, ReplayOrchestrator, _retarget, load_recording
from backend.main import create_app
from backend.projects import PRESET_ID

BASE = f"/api/projects/{PRESET_ID}"


@pytest.fixture
def replay_settings(settings):
    return replace(settings, agents="replay", replay_speed=500.0)


@pytest.fixture
def rc(replay_settings):
    with TestClient(create_app(replay_settings)) as client:  # orchestrator loaded from settings
        yield client


def wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def state(c):
    return c.get(f"{BASE}/state").json()


# --- recording format ---

def test_sample_recording_is_valid():
    records = load_recording(DEFAULT_RECORDING)
    types = [r["type"] for r in records]
    assert types.count("_await_user") == 1 and types[-1] == "_project_state"
    assert [r["t"] for r in records] == sorted(r["t"] for r in records)


@pytest.mark.parametrize(("content", "error"), [("{bad\n", "not JSON"), ('{"t": 1}\n', "missing 'type'")])
def test_load_recording_reports_bad_lines(tmp_path, content, error):
    path = tmp_path / "r.jsonl"
    path.write_text('{"type": "stage_done", "payload": {}}\n\n' + content)
    with pytest.raises(ValueError, match=rf"r.jsonl:3: {error}"):
        load_recording(path)


def test_retarget_rewrites_nested_project_ids():
    data = {"project_id": "old", "items": [{"project_id": "old", "x": 1}], "other": "old"}
    assert _retarget(data, "new") == {"project_id": "new", "items": [{"project_id": "new", "x": 1}], "other": "old"}


# --- full replay through the backend ---

def test_replay_waits_for_the_user_then_finishes(rc, data_root):
    assert rc.post(f"{BASE}/start").json() == {"status": "running"}
    wait(lambda: len(state(rc)["messages"]) == 1)
    time.sleep(0.2)
    s = state(rc)
    assert s["run"]["stage"] == "preprocess" and s["live"]["brief"] is None  # paused for the user's answer
    assert "dataset" in s["messages"][0]["content"]

    assert rc.post(f"{BASE}/messages", json={"content": "Yes, go ahead", "id": "user_msg_0001"}).status_code == 204
    wait(lambda: state(rc)["run"]["status"] == "done")
    s = state(rc)
    assert [m["role"] for m in s["messages"]] == ["assistant", "user", "assistant", "assistant"]
    assert s["live"]["brief"]["project_id"] == PRESET_ID  # retargeted
    assert {h["status"] for h in s["live"]["hypotheses"]} == {"approved", "rejected"}
    assert [len(cells) for cells in s["live"]["cells"].values()] == [2, 2, 2]
    assert len(s["live"]["findings"]) == 2 and len(s["live"]["llm_calls"]) == 14

    results = s["results"]
    assert results["project_id"] == PRESET_ID and results["stage"] == "report"
    on_disk = json.loads((data_root / PRESET_ID / "project_state.json").read_text())
    assert on_disk["project_id"] == PRESET_ID

    cards = rc.get(f"{BASE}/findings").json()
    assert [c["chart"]["type"] for c in cards] == ["volcano", "bar"]
    assert cards[0]["figure_url"].endswith("hypotheses/h1/figures/cell001_0.svg")
    assert "<svg" in rc.get(cards[0]["figure_url"]).text
    files = {f["name"]: f["url"] for f in rc.get(f"{BASE}/files").json()}
    assert rc.get(files["report.md"]).text.startswith("# SCRAP report")
    assert rc.get(files["de_01.csv"]).text.startswith("gene,log2FoldChange")


def test_questions_after_the_replay_get_a_canned_answer(rc):
    rc.post(f"{BASE}/start")
    rc.post(f"{BASE}/messages", json={"content": "go"})
    wait(lambda: state(rc)["run"]["status"] == "done")
    rc.post(f"{BASE}/messages", json={"content": "Which finding is strongest?"})
    wait(lambda: "Which finding is strongest?" in state(rc)["messages"][-1]["content"]
         and state(rc)["messages"][-1]["role"] == "assistant")


def test_first_message_on_a_fresh_project_starts_the_replay(rc):
    assert rc.post(f"{BASE}/messages", json={"content": "Analyze this"}).status_code == 204
    wait(lambda: state(rc)["run"]["status"] == "done")


def test_stop_mid_replay(replay_settings):
    with TestClient(create_app(replace(replay_settings, replay_speed=1.0))) as c:
        c.post(f"{BASE}/start")
        wait(lambda: len(state(c)["messages"]) == 1)
        assert c.post(f"{BASE}/stop").json() == {"status": "stopped"}
        n = c.app.state.store.last_event_id
        c.post(f"/api/projects/{PRESET_ID}/messages", json={"content": "too late"})  # 409: stopped
        time.sleep(0.3)
        assert c.app.state.store.last_event_id == n
        assert state(c)["run"] == {"status": "stopped", "stage": "stopped"}


async def test_replay_start_is_idempotent_and_message_needs_a_run(tmp_path):
    orch = ReplayOrchestrator(None, tmp_path, speed=1.0)
    with pytest.raises(KeyError):
        await orch.handle_user_message("p", "hi")
    await orch.start_run("p")
    task = orch._runs["p"].task
    await orch.start_run("p")
    assert orch._runs["p"].task is task
    await orch.stop_run("p")
    await orch.stop_run("missing")  # no run: nothing to do


async def test_a_file_record_escaping_the_project_fails_the_run(tmp_path, monkeypatch):
    emitted = []
    monkeypatch.setattr("backend.dev.replay_orchestrator.emit", emitted.append)
    rec = tmp_path / "r.jsonl"
    rec.write_text(json.dumps({"type": "_file", "payload": {"path": "../../evil.txt", "text": "x"}}) + "\n")
    orch = ReplayOrchestrator(rec, tmp_path / "data", speed=1000)
    await orch.start_run("p")
    await orch._runs["p"].task
    assert emitted[-1].payload == {"stage": "failed", "summary": "recording file path escapes the project: '../../evil.txt'"}
    assert not (tmp_path / "evil.txt").exists()


# --- recording over HTTP ---

def test_record_a_replayed_run_and_replay_it_again(replay_settings, tmp_path, monkeypatch):
    import socket
    import threading

    import uvicorn

    app = create_app(replace(replay_settings, replay_speed=200.0))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    wait(lambda: server.started)
    base = f"http://127.0.0.1:{port}"
    try:
        import httpx

        httpx.post(f"{base}{BASE}/messages", json={"content": "go"}, timeout=5)
        out = tmp_path / "recorded.jsonl"
        n = recorder.record(base, PRESET_ID, out, timeout=20)
    finally:
        server.should_exit = True
    records = load_recording(out)
    assert n == len(records)
    types = [r["type"] for r in records]
    assert types[-2:] == ["stage_done", "_project_state"] and records[-2]["payload"]["stage"] == "report"
    assert "user_message" not in types and "run_status" not in types
    original = [r["type"] for r in load_recording(DEFAULT_RECORDING) if not r["type"].startswith("_")]
    assert [t for t in types if not t.startswith("_")] == original
    assert all("messages" not in r["payload"] for r in records if r["type"] == "llm_call")


def test_record_cli_parses_arguments(monkeypatch, tmp_path, capsys):
    seen = {}

    def fake_record(base, pid, out):
        seen.update(base=base, pid=pid, out=out)
        return 3

    monkeypatch.setattr(recorder, "record", fake_record)
    recorder.main(["p1", str(tmp_path / "x.jsonl"), "--base", "http://h:1"])
    assert seen == {"base": "http://h:1", "pid": "p1", "out": tmp_path / "x.jsonl"}
    assert "Recorded 3 records" in capsys.readouterr().err


def test_parse_block():
    assert recorder.parse_block('id: 1\nevent: x\ndata: {"a": 1}') == {"a": 1}
    assert recorder.parse_block(": ping") is None
