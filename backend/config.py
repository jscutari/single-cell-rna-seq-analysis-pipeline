"""Backend settings, read from the environment once at startup."""

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=value lines from a .env file (comments and blanks ignored)."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Settings:
    # Same default as agents/orchestrator.py: project folders live here.
    data_root: Path = Path("/home/ubuntu/workspace/data")
    # Dataset a new project starts from (the only dataset for the demo).
    preset_dataset: Path | None = None
    # "real" drives agents/orchestrator.py; "replay" plays back a recorded run.
    agents: str = "real"
    replay_file: Path | None = None
    replay_speed: float = 10.0
    # Live stream: keep-alive interval and per-subscriber buffer.
    heartbeat_seconds: float = 15.0
    subscriber_queue_size: int = 1000
    # "postgres" keeps everything across restarts; "memory" keeps nothing (tests, quick runs).
    store: str = "memory"
    database_url: str | None = None
    # Batched writes: commit every `write_interval` seconds or `write_batch` events.
    write_interval: float = 0.1
    write_batch: int = 200
    # How long startup waits for the database (e.g. while the container boots).
    db_connect_timeout: float = 30.0

    @property
    def preset(self) -> Path:
        return self.preset_dataset or self.data_root / "raw" / "covid_pbmc_wilk2020.h5ad"

    @classmethod
    def from_env(cls, env_file: Path | None = REPO_ROOT / ".env") -> "Settings":
        # Real environment variables win over the .env file.
        env = {**(read_env_file(env_file) if env_file else {}), **os.environ}
        return cls(
            data_root=Path(env.get("DATA_ROOT", cls.data_root)),
            preset_dataset=Path(env["SCRAP_PRESET_DATASET"]) if env.get("SCRAP_PRESET_DATASET") else None,
            agents=env.get("SCRAP_AGENTS", cls.agents),
            replay_file=Path(env["SCRAP_REPLAY_FILE"]) if env.get("SCRAP_REPLAY_FILE") else None,
            replay_speed=float(env.get("SCRAP_REPLAY_SPEED", cls.replay_speed)),
            heartbeat_seconds=float(env.get("SCRAP_HEARTBEAT_SECONDS", cls.heartbeat_seconds)),
            subscriber_queue_size=int(env.get("SCRAP_SUBSCRIBER_QUEUE", cls.subscriber_queue_size)),
            store=env.get("SCRAP_STORE", "postgres"),
            database_url=env.get("DATABASE_URL") or None,
            write_interval=float(env.get("SCRAP_WRITE_INTERVAL", cls.write_interval)),
            write_batch=int(env.get("SCRAP_WRITE_BATCH", cls.write_batch)),
            db_connect_timeout=float(env.get("SCRAP_DB_CONNECT_TIMEOUT", cls.db_connect_timeout)),
        )
