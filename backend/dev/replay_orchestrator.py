"""Play back a recorded run through emit(), with the orchestrator's three functions.

Lets the backend and the app run without the GPU box (SCRAP_AGENTS=replay).

Recording format (JSONL, one object per line):
  {"t": seconds_from_start, "type": "<event type>", "payload": {...}}
  {"t": ..., "type": "_await_user"}        pause until the user sends a message
  {"t": ..., "type": "_project_state", "payload": {...}}  write project_state.json
  {"t": ..., "type": "_file", "payload": {"path": "rel/path", "text": "..."}}  write a project file
Project ids inside payloads are rewritten to the project being run. Timing is
divided by `speed`.
"""

import asyncio
import json
import logging
from pathlib import Path

from shared.events import Event, emit
from shared.schemas import ChatMessage, Role, new_id

log = logging.getLogger("scrap.backend.replay")

DEFAULT_RECORDING = Path(__file__).parent / "recordings" / "sample_run.jsonl"


def load_recording(path: Path) -> list[dict]:
    records = []
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as error:
            raise ValueError(f"{path}:{n}: not JSON ({error})") from None
        if "type" not in record:
            raise ValueError(f"{path}:{n}: missing 'type'")
        records.append(record)
    return records


def _retarget(value, project_id: str):
    """Rewrite every project_id field in a payload."""
    if isinstance(value, dict):
        return {k: (project_id if k == "project_id" else _retarget(v, project_id)) for k, v in value.items()}
    if isinstance(value, list):
        return [_retarget(v, project_id) for v in value]
    return value


class _Replay:
    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.user_turn = asyncio.Event()
        self.finished = False


class ReplayOrchestrator:
    def __init__(self, recording: Path | None, data_root: Path, speed: float = 10.0) -> None:
        self.records = load_recording(recording or DEFAULT_RECORDING)
        self.data_root = Path(data_root)
        self.speed = max(speed, 0.001)
        self._runs: dict[str, _Replay] = {}

    async def start_run(self, project_id: str) -> None:
        run = self._runs.get(project_id)
        if run and run.task and not run.task.done():
            return
        run = self._runs[project_id] = _Replay()
        run.task = asyncio.create_task(self._play(project_id, run))

    async def handle_user_message(self, project_id: str, text: str) -> None:
        run = self._runs.get(project_id)
        if run is None:
            raise KeyError(f"No run for project {project_id}; call start_run first.")
        if not run.user_turn.is_set() and not run.finished:
            run.user_turn.set()  # the recording was waiting for this
            return
        reply = ChatMessage(project_id=project_id, role=Role.assistant,
                            content=f"(Replay) This is a recorded run, so new questions can't be answered. You asked: {text}")
        emit(Event(type="chat_reply", project_id=project_id, payload=reply))

    async def stop_run(self, project_id: str) -> None:
        run = self._runs.get(project_id)
        if run is None:
            return
        if run.task and not run.task.done():
            run.task.cancel()
            await asyncio.gather(run.task, return_exceptions=True)
        run.finished = True
        emit(Event(type="stage_done", project_id=project_id, payload={"stage": "stopped", "summary": "Run stopped by the user."}))

    async def _play(self, project_id: str, run: _Replay) -> None:
        clock = 0.0
        try:
            for record in self.records:
                t = float(record.get("t", clock))
                if t > clock:
                    await asyncio.sleep((t - clock) / self.speed)
                    clock = t
                kind = record["type"]
                if kind == "_await_user":
                    await run.user_turn.wait()
                elif kind == "_project_state":
                    self._write_state(project_id, _retarget(record["payload"], project_id))
                elif kind == "_file":
                    self._write_file(project_id, record["payload"]["path"], record["payload"]["text"])
                else:
                    payload = _retarget(record.get("payload", {}), project_id)
                    if "id" in payload and kind in ("chat_reply",):
                        payload["id"] = new_id()  # replies are unique per replay
                    emit(Event(type=kind, project_id=project_id, payload=payload))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.exception("Replay failed for %s", project_id)
            emit(Event(type="stage_done", project_id=project_id, payload={"stage": "failed", "summary": str(error)}))
        finally:
            run.finished = True

    def _write_file(self, project_id: str, relative: str, text: str) -> None:
        folder = (self.data_root / project_id).resolve()
        target = (folder / relative).resolve()
        if not target.is_relative_to(folder):
            raise ValueError(f"recording file path escapes the project: {relative!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def _write_state(self, project_id: str, state: dict) -> None:
        folder = self.data_root / project_id
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / "project_state.json.tmp"
        tmp.write_text(json.dumps(state))
        tmp.replace(folder / "project_state.json")
