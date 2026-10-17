"""Backend settings, read from the environment once at startup."""

import os
from dataclasses import dataclass
from pathlib import Path


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

    @property
    def preset(self) -> Path:
        return self.preset_dataset or self.data_root / "raw" / "covid_pbmc_wilk2020.h5ad"

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        return cls(
            data_root=Path(env.get("DATA_ROOT", cls.data_root)),
            preset_dataset=Path(env["SCRAP_PRESET_DATASET"]) if env.get("SCRAP_PRESET_DATASET") else None,
            agents=env.get("SCRAP_AGENTS", cls.agents),
            replay_file=Path(env["SCRAP_REPLAY_FILE"]) if env.get("SCRAP_REPLAY_FILE") else None,
            replay_speed=float(env.get("SCRAP_REPLAY_SPEED", cls.replay_speed)),
            heartbeat_seconds=float(env.get("SCRAP_HEARTBEAT_SECONDS", cls.heartbeat_seconds)),
            subscriber_queue_size=int(env.get("SCRAP_SUBSCRIBER_QUEUE", cls.subscriber_queue_size)),
        )
