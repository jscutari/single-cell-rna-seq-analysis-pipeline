"""Backend fixtures: a temporary DATA_ROOT, a fake orchestrator and a test client."""

import asyncio
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


async def until(predicate, timeout: float = 2.0):
    """Wait for a condition set by background work."""
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met in time")
