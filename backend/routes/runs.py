"""Run control and chat: /start, /stop, /messages."""

from typing import Annotated

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, StringConstraints

from backend.routes.projects import require_project
from shared.schemas import ChatMessage, Role

router = APIRouter(prefix="/api/projects/{project_id}", tags=["runs"])


class NewMessage(BaseModel):
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000)]
    # Client-chosen id: lets the app match its local bubble and makes retries safe.
    id: Annotated[str | None, Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$")] = None


def runs(request: Request):
    return request.app.state.runs


@router.post("/start")
async def start(project_id: str, request: Request) -> dict:
    require_project(request, project_id)
    return {"status": await runs(request).start(project_id)}


@router.post("/stop")
async def stop(project_id: str, request: Request) -> dict:
    require_project(request, project_id)
    return {"status": await runs(request).stop(project_id)}


@router.get("/messages")
async def list_messages(project_id: str, request: Request) -> list[dict]:
    require_project(request, project_id)
    return request.app.state.store.messages(project_id)


@router.post("/messages", status_code=204)
async def send_message(project_id: str, body: NewMessage, request: Request) -> Response:
    require_project(request, project_id)
    fields = {"project_id": project_id, "role": Role.user, "content": body.content}
    message = ChatMessage(**fields, **({"id": body.id} if body.id else {}))
    await runs(request).send(project_id, message.model_dump(mode="json"))
    return Response(status_code=204)
