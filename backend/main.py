"""FastAPI app: the bridge between the web app and the agents (PLAN.md section 4).

Run on the Brev box (one worker, no reload; the orchestrator keeps run state in memory):
    uv run uvicorn backend.main:app --host 127.0.0.1 --port 8080
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.config import Settings
from backend.hub import EventHub
from backend.projects import ProjectRegistry
from backend import sse
from backend.routes import projects, state
from backend.store import InMemoryStore

log = logging.getLogger("scrap.backend")


def create_app(settings: Settings | None = None, orchestrator=None, store: InMemoryStore | None = None) -> FastAPI:
    """Build the app. Tests pass their own settings, store and a fake orchestrator."""
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_root.mkdir(parents=True, exist_ok=True)
        app.state.projects.load()
        app.state.projects.ensure_preset_project()
        app.state.hub.attach(asyncio.get_running_loop())
        try:
            yield
        finally:
            app.state.hub.detach()

    app = FastAPI(title="SCRAP backend", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store or InMemoryStore()
    app.state.orchestrator = orchestrator
    app.state.projects = ProjectRegistry(settings.data_root, settings.preset)
    app.state.hub = EventHub(app.state.store, settings.subscriber_queue_size)
    app.include_router(projects.router)
    app.include_router(state.router)
    app.include_router(sse.router)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "agents": settings.agents}

    return app


def app_from_env() -> FastAPI:
    return create_app()


app = app_from_env()
