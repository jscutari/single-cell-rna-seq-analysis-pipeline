"""Project files and findings, from project_state.json, and serving files safely."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from backend.results import read_state, with_urls
from backend.routes.projects import require_project

router = APIRouter(prefix="/api/projects/{project_id}", tags=["files"])

_MEDIA_TYPES = {".ipynb": "application/json", ".md": "text/markdown; charset=utf-8", ".h5ad": "application/octet-stream"}


def _results(request: Request, project_id: str) -> dict | None:
    require_project(request, project_id)
    state = read_state(request.app.state.projects.project_dir(project_id))
    return with_urls(state, project_id) if state else None


@router.get("/files")
async def list_files(project_id: str, request: Request) -> list[dict]:
    """Every file worth showing, in the app's ProjectFile shape with a url."""
    state = _results(request, project_id)
    return state["files"] if state else []


@router.get("/findings")
async def list_findings(project_id: str, request: Request) -> list[dict]:
    """FindingCards: the Finding plus chart data (null when no result table backs it) and file URLs."""
    state = _results(request, project_id)
    return [
        {"finding": f["finding"], "chart": f.get("chart"), "hypothesis_title": f.get("hypothesis_title"),
         "figure_url": f.get("figure_url"), "notebook_url": f.get("notebook_url"), "mock": False}
        for f in (state["findings"] if state else [])
    ]


def resolve_inside(root: Path, relative: str) -> Path | None:
    """The file at root/relative, or None if it is missing or resolves outside root (.., absolute, symlinks)."""
    if not relative or relative.startswith(("/", "\\")) or "\x00" in relative:
        return None
    base = root.resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        return None
    return target


@router.get("/files/{path:path}")
async def get_file(project_id: str, path: str, request: Request) -> FileResponse:
    require_project(request, project_id)
    target = resolve_inside(request.app.state.projects.project_dir(project_id), path)
    if target is None:
        raise HTTPException(404, "File not found")
    return FileResponse(target, media_type=_MEDIA_TYPES.get(target.suffix.lower()))
