"""Project files and findings, from project_state.json, and serving files safely."""

import os
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


# Written by preprocessing from dataset.h5ad; stale once the dataset changes.
_DERIVED = ("processed.h5ad", "dataset_summary.json", "umap_overview.png", "umap_points.json")
MAX_DATASET_BYTES = 20 * 1024**3


@router.put("/dataset")
async def upload_dataset(project_id: str, request: Request) -> dict:
    """Replace the project's dataset with the request body (an .h5ad file, sent as raw bytes).

    The upload streams to a temporary file and then replaces dataset.h5ad, so a
    preset hard link is swapped out rather than written through. Preprocessing
    runs again on the next start (cached by file hash, so a known file is instant).
    """
    require_project(request, project_id)
    if request.app.state.store.status(project_id) == "running":
        raise HTTPException(409, "Stop the run before changing the dataset.")
    root = request.app.state.projects.project_dir(project_id)
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / "dataset.h5ad.uploading"
    size = 0
    try:
        with open(tmp, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_DATASET_BYTES:
                    raise HTTPException(413, "Dataset is larger than 20 GB.")
                fh.write(chunk)
        with open(tmp, "rb") as fh:
            if fh.read(8) != b"\x89HDF\r\n\x1a\n":
                raise HTTPException(422, "That file is not an .h5ad (HDF5) file.")
        os.replace(tmp, root / "dataset.h5ad")
    finally:
        tmp.unlink(missing_ok=True)
    for name in _DERIVED:
        (root / name).unlink(missing_ok=True)
    return {"size_bytes": size}
