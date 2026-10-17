"""/api/projects: list, create, get."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, StringConstraints

from backend.projects import PresetMissing, ProjectRegistry
from backend.store import InMemoryStore
from shared.schemas import Project, ProjectStatus

router = APIRouter(prefix="/api/projects", tags=["projects"])

# Run status (backend) -> ProjectStatus (shared contract).
_STATUS = {"idle": ProjectStatus.created, "done": ProjectStatus.done,
           "stopped": ProjectStatus.stopped, "failed": ProjectStatus.failed}


class NewProject(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


def registry(request: Request) -> ProjectRegistry:
    return request.app.state.projects


def with_status(project: Project, store: InMemoryStore) -> Project:
    view = store.view(project.id) if project.id in store.known_projects() else None
    if view is None:
        return project
    if view.status == "running":
        status = ProjectStatus.intake if view.stage in (None, "preprocess", "intake") else ProjectStatus.running
    else:
        status = _STATUS[view.status]
    return project.model_copy(update={"status": status})


def require_project(request: Request, project_id: str) -> Project:
    project = registry(request).get(project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


@router.get("", response_model=list[Project])
async def list_projects(request: Request) -> list[Project]:
    store = request.app.state.store
    return [with_status(p, store) for p in registry(request).list()]


@router.post("", response_model=Project, status_code=201)
async def create_project(body: NewProject, request: Request) -> Project:
    try:
        return registry(request).create(body.name)
    except PresetMissing:
        raise HTTPException(503, "The preset dataset is not available on this server") from None


@router.get("/{project_id}", response_model=Project)
async def get_project(project_id: str, request: Request) -> Project:
    return with_status(require_project(request, project_id), request.app.state.store)
