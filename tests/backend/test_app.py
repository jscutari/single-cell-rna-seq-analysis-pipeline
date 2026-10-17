"""backend/main.py: app factory and health check."""

from backend.config import Settings


def test_health(client, settings):
    expected_db = "ok" if settings.store == "postgres" else "memory"
    assert client.get("/api/health").json() == {"status": "ok", "agents": "fake", "db": expected_db}


def test_startup_creates_data_root(tmp_path, orchestrator):
    from fastapi.testclient import TestClient

    from backend.main import create_app

    root = tmp_path / "fresh"
    with TestClient(create_app(Settings(data_root=root), orchestrator=orchestrator)):
        assert root.is_dir()


def test_unknown_route_is_404(client):
    assert client.get("/api/nope").status_code == 404


def test_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SCRAP_AGENTS", "replay")
    monkeypatch.setenv("SCRAP_REPLAY_SPEED", "4")
    monkeypatch.setenv("SCRAP_HEARTBEAT_SECONDS", "2.5")
    s = Settings.from_env()
    assert (s.data_root, s.agents, s.replay_speed, s.heartbeat_seconds) == (tmp_path, "replay", 4.0, 2.5)
    assert s.preset == tmp_path / "raw" / "covid_pbmc_wilk2020.h5ad"


def test_settings_defaults(monkeypatch):
    for var in ("DATA_ROOT", "SCRAP_AGENTS", "SCRAP_PRESET_DATASET", "SCRAP_REPLAY_FILE"):
        monkeypatch.delenv(var, raising=False)
    s = Settings.from_env()
    assert str(s.data_root) == "/home/ubuntu/workspace/data" and s.agents == "real" and s.replay_file is None
