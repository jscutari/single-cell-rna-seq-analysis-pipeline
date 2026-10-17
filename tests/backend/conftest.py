"""Backend fixtures: a temporary DATA_ROOT, a fake orchestrator and a test client."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from shared import events as events_module


class FakeOrchestrator:
    """Same three functions as agents/orchestrator.py; records calls, emits nothing by itself."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail_message: Exception | None = None

    async def start_run(self, project_id: str) -> None:
        self.calls.append(("start_run", project_id))

    async def handle_user_message(self, project_id: str, text: str) -> None:
        if self.fail_message:
            raise self.fail_message
        self.calls.append(("handle_user_message", project_id, text))

    async def stop_run(self, project_id: str) -> None:
        self.calls.append(("stop_run", project_id))

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]


@pytest.fixture(autouse=True)
def restore_sink():
    """The app replaces the global emit() sink; put the console sink back after each test."""
    original = events_module._sink
    yield
    events_module.set_sink(original)


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    (root / "raw").mkdir(parents=True)
    (root / "raw" / "covid_pbmc_wilk2020.h5ad").write_bytes(b"fake h5ad")
    return root


@pytest.fixture
def settings(data_root: Path) -> Settings:
    return Settings(data_root=data_root, agents="fake", heartbeat_seconds=0.2)


@pytest.fixture
def orchestrator() -> FakeOrchestrator:
    return FakeOrchestrator()


@pytest.fixture
def app(settings, orchestrator):
    return create_app(settings, orchestrator=orchestrator)


@pytest.fixture
def client(app):
    with TestClient(app) as c:  # runs startup/shutdown
        yield c


@pytest.fixture
def live_server(settings, orchestrator):
    """The app on a real uvicorn server in a thread (for streaming over HTTP)."""
    import socket
    import threading
    import time

    import uvicorn

    app = create_app(settings, orchestrator=orchestrator)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(500):
        if server.started:
            break
        time.sleep(0.01)
    assert server.started, "server did not start"
    yield app, f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


# --- Postgres (tests marked `db`; skipped when no server is reachable) ---

def _server_url() -> str | None:
    import os

    from backend.config import REPO_ROOT, read_env_file

    return os.environ.get("DATABASE_URL") or read_env_file(REPO_ROOT / ".env").get("DATABASE_URL")


def _run(coro):
    import asyncio

    return asyncio.run(coro)


@pytest.fixture(scope="session")
def pg_test_db():
    """A throwaway database on the compose Postgres for this test session."""
    import uuid

    import asyncpg

    url = _server_url()
    if not url:
        pytest.skip("no DATABASE_URL (start Postgres: docker compose up -d db)")

    async def admin(sql: str) -> None:
        conn = await asyncpg.connect(url, timeout=3)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    name = f"scrap_test_{uuid.uuid4().hex[:10]}"
    try:
        _run(admin(f'CREATE DATABASE "{name}"'))
    except Exception as error:  # server not running
        pytest.skip(f"Postgres not reachable ({error})")
    base, _ = url.rsplit("/", 1)
    yield f"{base}/{name}"
    _run(admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture
def pg_url(pg_test_db):
    """The session database, emptied before each test."""
    import asyncpg

    async def reset():
        conn = await asyncpg.connect(pg_test_db)
        try:
            await conn.execute("DROP TABLE IF EXISTS events, llm_calls, projects, schema_version")
        finally:
            await conn.close()

    _run(reset())
    return pg_test_db
