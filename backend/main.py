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
from backend.routes import files, projects, runs, state
from backend.runs import RunManager
from backend.store import InMemoryStore

log = logging.getLogger("scrap.backend")


def create_app(settings: Settings | None = None, orchestrator=None, store: InMemoryStore | None = None) -> FastAPI:
    """Build the app. Tests pass their own settings, store and a fake orchestrator."""
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_root.mkdir(parents=True, exist_ok=True)
        if app.state.store is None:
            app.state.store = await open_store(settings)  # refuses to start if Postgres is unreachable
        app.state.hub = EventHub(app.state.store, settings.subscriber_queue_size)
        app.state.projects = ProjectRegistry(settings.data_root, settings.preset, pool=getattr(app.state.store, "pool", None))
        await app.state.projects.load_all()
        await app.state.projects.ensure_preset_project()
        stop_interrupted_runs(app.state.hub)
        if app.state.orchestrator is None:
            app.state.orchestrator = load_orchestrator(settings)
        app.state.runs = RunManager(app.state.hub, app.state.orchestrator, app.state.projects)
        app.state.hub.attach(asyncio.get_running_loop())
        try:
            yield
        finally:
            app.state.hub.detach()
            await app.state.store.close()

    app = FastAPI(title="SCRAP backend", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store  # None: opened at startup from settings.store
    app.state.orchestrator = orchestrator
    app.include_router(projects.router)
    app.include_router(state.router)
    app.include_router(sse.router)
    app.include_router(runs.router)
    app.include_router(files.router)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "agents": settings.agents, "db": app.state.store.db_status}

    return app


INTERRUPTED = "The backend restarted, so this run was interrupted. Start a new run to continue."


def stop_interrupted_runs(hub: EventHub) -> list[str]:
    """Runs saved as running belonged to the previous process; the agents' state is gone."""
    interrupted = hub.store.running_projects()
    for project_id in interrupted:
        hub.publish("stage_done", project_id, {"stage": "stopped", "summary": INTERRUPTED})
        log.warning("Marked the interrupted run of %s as stopped", project_id)
    return interrupted


async def open_store(settings: Settings) -> InMemoryStore:
    if settings.store == "memory":
        log.warning("SCRAP_STORE=memory: nothing is saved; data is lost when the backend restarts")
        return InMemoryStore()
    if settings.store == "postgres":
        from backend.pg_store import PgStore

        return await PgStore.open(settings)
    raise ValueError(f"Unknown SCRAP_STORE={settings.store!r} (expected 'postgres' or 'memory')")


def load_orchestrator(settings: Settings):
    """The real agents (imported lazily: they pull in torch) or a recorded-run replay."""
    if settings.agents == "real":
        from agents import orchestrator

        if orchestrator.DATA_ROOT != settings.data_root:
            log.warning("DATA_ROOT differs: backend %s, orchestrator %s", settings.data_root, orchestrator.DATA_ROOT)
        return orchestrator
    if settings.agents == "replay":
        from backend.dev.replay_orchestrator import ReplayOrchestrator

        return ReplayOrchestrator(settings.replay_file, settings.data_root, settings.replay_speed)
    raise ValueError(f"Unknown SCRAP_AGENTS={settings.agents!r} (expected 'real' or 'replay')")


def app_from_env() -> FastAPI:
    return create_app()


app = app_from_env()
