"""Starting/stopping runs and routing chat to the orchestrator.

The orchestrator (agents/orchestrator.py, or a replay/fake with the same three
functions) keeps run state in memory, so the backend tracks each project's run
status from events and enforces:
  - one active run at a time (the box has one GPU);
  - start/stop are idempotent;
  - the first chat message on a fresh project starts its run;
  - chatting with a run that is no longer in memory (stopped, failed, or
    finished before a server restart) asks the user to start a new run instead
    of silently re-running the whole analysis.
"""

import logging

from fastapi import HTTPException

from backend.hub import EventHub
from backend.results import read_state

log = logging.getLogger("scrap.backend.runs")


class RunManager:
    def __init__(self, hub: EventHub, orchestrator, projects) -> None:
        self.hub = hub
        self.orchestrator = orchestrator
        self.projects = projects

    @property
    def store(self):
        return self.hub.store

    def _check_capacity(self, project_id: str) -> None:
        others = [p for p in self.store.running_projects() if p != project_id]
        if others:
            raise HTTPException(409, {"message": "Another project's run is in progress.", "running_project_id": others[0]})

    async def start(self, project_id: str) -> str:
        if self.store.status(project_id) == "running":
            return "running"
        self._check_capacity(project_id)
        self.hub.publish("run_status", project_id, {"status": "running"})
        try:
            await self.orchestrator.start_run(project_id)
        except Exception as error:
            log.exception("start_run failed for %s", project_id)
            self.hub.publish("run_status", project_id, {"status": "failed"})
            raise HTTPException(502, f"Could not start the run: {error}") from None
        return self.store.status(project_id)

    async def stop(self, project_id: str) -> str:
        if self.store.status(project_id) != "running":
            return self.store.status(project_id)
        await self.orchestrator.stop_run(project_id)
        if self.store.status(project_id) == "running":  # the orchestrator had no run to stop
            self.hub.publish("run_status", project_id, {"status": "stopped"})
        return self.store.status(project_id)

    def check_can_chat(self, project_id: str) -> bool:
        """Raise 409 if a message can't be handled now; return True if the run must be started first."""
        status = self.store.status(project_id)
        if status in ("running", "done"):
            return False
        if status in ("stopped", "failed"):
            raise HTTPException(409, f"This project's run {status}. Start a new run to keep chatting.")
        # idle: never run since the server started
        if read_state(self.projects.project_dir(project_id)) is not None:
            raise HTTPException(409, "This project's earlier run isn't active anymore. Start a new run to keep chatting.")
        self._check_capacity(project_id)
        return True

    async def send(self, project_id: str, message: dict) -> bool:
        """Record the user's message and hand it to the orchestrator. False if it was a duplicate."""
        must_start = self.check_can_chat(project_id)
        if self.hub.publish("user_message", project_id, message) is None:
            return False  # retry of a message we already have
        if must_start:
            await self.start(project_id)
        try:
            await self.orchestrator.handle_user_message(project_id, message["content"])
        except KeyError:
            raise HTTPException(409, "The run isn't active. Start a new run to keep chatting.") from None
        except Exception as error:
            log.exception("handle_user_message failed for %s", project_id)
            raise HTTPException(502, f"The agents could not take the message: {error}") from None
        return True
