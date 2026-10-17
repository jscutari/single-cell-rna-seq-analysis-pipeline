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
        self._delivered: set[str] = set()  # user message ids handed to the orchestrator

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
        """Record the user's message, save it, and hand it to the orchestrator.

        False if it was a retry of a message already delivered. A retry of one
        that was recorded but not delivered (e.g. the save failed) is delivered.
        """
        if message["id"] in self._delivered:
            return False
        must_start = self.check_can_chat(project_id)
        self.hub.publish("user_message", project_id, message)  # None for a retry: already recorded
        try:
            await self.store.flush()  # a message the user sees as sent must be saved
        except TimeoutError:
            raise HTTPException(503, "Couldn't save your message (the database is unavailable). Try again.") from None
        self._delivered.add(message["id"])
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
