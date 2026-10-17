"""/api/projects/{id}/state and LLM call lookups."""

from fastapi import APIRouter, HTTPException, Request

from backend.results import read_state, with_urls
from backend.routes.projects import require_project, with_status

router = APIRouter(prefix="/api/projects/{project_id}", tags=["state"])


@router.get("/state")
async def project_state(project_id: str, request: Request) -> dict:
    """Everything the app shows for a project, plus the serial to stream from.

    Built synchronously (no await) so `last_event_id` matches the data exactly:
    opening /events?after=<last_event_id> then misses and repeats nothing.
    """
    project = require_project(request, project_id)
    store = request.app.state.store
    view = store.view(project_id) if project_id in store.known_projects() else None
    results = read_state(request.app.state.projects.project_dir(project_id))
    return {
        "project": with_status(project, store).model_dump(mode="json"),
        "run": {"status": view.status if view else "idle", "stage": view.stage if view else None},
        "last_event_id": store.last_event_id,
        "messages": store.messages(project_id),
        "live": {
            "brief": view.brief if view else None,
            "hypotheses": list(view.hypotheses.values()) if view else [],
            "cells": {hid: sorted(cells.values(), key=lambda c: c["index"]) for hid, cells in view.cells.items()} if view else {},
            "findings": list(view.findings.values()) if view else [],
            "llm_calls": list(view.llm_calls.values()) if view else [],
        },
        "results": with_urls(results, project_id) if results else None,
    }


@router.get("/llm_calls")
async def list_llm_calls(project_id: str, request: Request, agent: str | None = None,
                         hypothesis_id: str | None = None) -> list[dict]:
    """Trace entries without their prompt messages; filter by agent and/or hypothesis."""
    require_project(request, project_id)
    store = request.app.state.store
    if project_id not in store.known_projects():
        return []
    calls = store.view(project_id).llm_calls.values()
    return [c for c in calls
            if (agent is None or c.get("agent") == agent) and (hypothesis_id is None or c.get("hypothesis_id") == hypothesis_id)]


@router.get("/llm_calls/{call_id}")
async def get_llm_call(project_id: str, call_id: str, request: Request) -> dict:
    """One LLM call in full, including its prompt messages."""
    require_project(request, project_id)
    call = request.app.state.store.llm_call(call_id)
    if call is None or call.get("project_id") != project_id:
        raise HTTPException(404, "LLM call not found")
    return call
