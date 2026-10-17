"""FastAPI app: the bridge between the web app and the agents (PLAN.md section 4).

Run on the Brev box (one worker, no reload; the orchestrator keeps run state in memory):
    uv run uvicorn backend.main:app --host 127.0.0.1 --port 8080
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.config import Settings
from backend.projects import ProjectRegistry
from backend.routes import projects
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
        yield

    app = FastAPI(title="SCRAP backend", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store or InMemoryStore()
    app.state.orchestrator = orchestrator
    app.state.projects = ProjectRegistry(settings.data_root, settings.preset)
    app.include_router(projects.router)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "agents": settings.agents}

    return app


def app_from_env() -> FastAPI:
    return create_app()


app = app_from_env()
