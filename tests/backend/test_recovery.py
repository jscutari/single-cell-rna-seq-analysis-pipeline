"""Restart recovery with Postgres, and the backup script."""

import gzip
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import REPO_ROOT, Settings
from backend.main import INTERRUPTED, create_app
from backend.projects import PRESET_ID

pytestmark = pytest.mark.db
BASE = f"/api/projects/{PRESET_ID}"


@pytest.fixture
def pg_settings(data_root, pg_url) -> Settings:
    return Settings(data_root=data_root, agents="fake", store="postgres", database_url=pg_url,
                    write_interval=0.02, db_connect_timeout=3)


def run_state(c):
    return c.get(f"{BASE}/state").json()


def test_a_run_interrupted_by_a_restart_is_marked_stopped(pg_settings, orchestrator):
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        c.post(f"{BASE}/messages", json={"content": "Analyze", "id": "msg_before_crash"})
        assert run_state(c)["run"]["status"] == "running"
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        s = run_state(c)
        assert s["run"] == {"status": "stopped", "stage": "stopped"}
        assert [m["content"] for m in s["messages"]] == ["Analyze"]  # history kept
        stopped = [e for e in c.app.state.store.events_after(PRESET_ID, 0) if e.type == "stage_done"]
        assert stopped[-1].payload == {"stage": "stopped", "summary": INTERRUPTED}
        r = c.post(f"{BASE}/messages", json={"content": "still there?"})
        assert r.status_code == 409 and "Start a new run" in r.json()["detail"]
        assert c.post(f"{BASE}/start").json() == {"status": "running"}  # a new run works


def test_finished_and_idle_runs_are_left_alone(pg_settings, orchestrator):
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        other = c.post("/api/projects", json={"name": "Idle"}).json()["id"]
        c.post(f"{BASE}/start")
        c.app.state.hub.publish("stage_done", PRESET_ID, {"stage": "report", "summary": "done"})
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        assert run_state(c)["run"]["status"] == "done"
        assert c.get(f"/api/projects/{other}/state").json()["run"]["status"] == "idle"
        assert len([e for e in c.app.state.store.events_after(PRESET_ID, 0) if e.payload.get("stage") == "stopped"]) == 0


def test_recovery_is_not_repeated_on_the_next_restart(pg_settings, orchestrator):
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        c.post(f"{BASE}/start")
    for _ in range(2):
        with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
            pass
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        stops = [e for e in c.app.state.store.events_after(PRESET_ID, 0) if e.payload.get("stage") == "stopped"]
        assert len(stops) == 1


def test_asking_a_finished_run_after_a_restart_explains(pg_settings, orchestrator):
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        c.post(f"{BASE}/start")
        c.app.state.hub.publish("stage_done", PRESET_ID, {"stage": "report", "summary": ""})

    class Forgetful(type(orchestrator)):
        async def handle_user_message(self, pid, text):
            raise KeyError(pid)  # the real orchestrator after a restart

    with TestClient(create_app(pg_settings, orchestrator=Forgetful())) as c:
        r = c.post(f"{BASE}/messages", json={"content": "Which finding is strongest?"})
        assert r.status_code == 409


# --- backup script (needs the compose database) ---

def compose_db_running() -> bool:
    if not shutil.which("docker"):
        return False
    out = subprocess.run(["docker", "compose", "ps", "--status", "running", "--services"],
                         cwd=REPO_ROOT, capture_output=True, text=True)
    return "db" in out.stdout.split()


@pytest.mark.skipif(not compose_db_running(), reason="docker compose db is not running")
def test_backup_script_dumps_and_keeps_the_newest(tmp_path):
    old = []
    for i in range(12):
        f = tmp_path / f"scrap-2026010{i % 10}T00000{i % 10}Z-{i:02d}.sql.gz"
        f.write_bytes(b"")
        os.utime(f, (1_000_000 + i, 1_000_000 + i))
        old.append(f)
    env = {**os.environ, "BACKUP_DIR": str(tmp_path), "BACKUP_KEEP": "10"}
    out = subprocess.run([str(REPO_ROOT / "backend/scripts/backup_db.sh")], env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    dump = Path(out.stdout.strip())
    assert dump.exists() and not dump.with_name(dump.name + ".part").exists()
    sql = gzip.decompress(dump.read_bytes()).decode()
    assert sql.startswith("--\n-- PostgreSQL database dump") and "PostgreSQL database dump complete" in sql
    remaining = sorted(tmp_path.glob("scrap-*.sql.gz"))
    assert len(remaining) == 10 and dump in remaining
    assert old[0] not in remaining and old[1] not in remaining and old[2] not in remaining
