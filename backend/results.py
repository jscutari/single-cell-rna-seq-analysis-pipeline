"""Read the durable results the orchestrator writes (agents/results.py) for the API.

<project_dir>/project_state.json holds relative paths; the API adds URLs the
browser can fetch from /api/projects/<id>/files/<path>.
"""

import json
import logging
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger("scrap.backend.results")


def file_url(project_id: str, path: str | None) -> str | None:
    return f"/api/projects/{project_id}/files/{quote(path)}" if path else None


def read_state(project_dir: Path) -> dict | None:
    """project_state.json as written by agents/results.py, or None if absent or unreadable."""
    path = project_dir / "project_state.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as error:
        log.warning("Ignoring unreadable %s: %s", path, error)
        return None


def with_urls(state: dict, project_id: str) -> dict:
    """Add browser URLs next to every relative path (files[].url, findings[].figure_url/notebook_url)."""
    state = dict(state)
    state["files"] = [{**f, "url": file_url(project_id, f.get("path"))} for f in state.get("files") or []]
    state["findings"] = [
        {**f, "figure_url": file_url(project_id, f.get("figure")), "notebook_url": file_url(project_id, f.get("notebook"))}
        for f in state.get("findings") or []
    ]
    return state
