"""Projects: a row in Postgres plus one folder per project under DATA_ROOT.

    projects table                         the list (source of truth with Postgres)
    $DATA_ROOT/<project_id>/project.json   {id, name, dataset_path, status, created_at} (readable backup)
    $DATA_ROOT/<project_id>/dataset.h5ad   hard link to the preset (what the orchestrator reads)

Without a database (SCRAP_STORE=memory) the folders are the registry. With one,
folders that aren't in the table yet (e.g. from before the database existed)
are imported once at startup. Folders without project.json (raw/, _cache/, ...)
are not projects.
"""

import json
import logging
import os
import re
import shutil
from pathlib import Path

from shared.schemas import Project, new_id

log = logging.getLogger("scrap.backend.projects")

PROJECT_ID = re.compile(r"^[a-z0-9_]{1,64}$")
PRESET_ID = "covid_pbmc"
PRESET_NAME = "COVID-19 PBMC (Wilk et al. 2020)"


class PresetMissing(Exception):
    """The dataset new projects start from isn't on disk."""


def valid_id(project_id: str) -> bool:
    return bool(PROJECT_ID.match(project_id))


class ProjectRegistry:
    def __init__(self, data_root: Path, preset: Path, pool=None) -> None:
        self.data_root = data_root
        self.preset = preset
        self.pool = pool  # asyncpg pool when projects live in Postgres
        self._projects: dict[str, Project] = {}

    async def load_all(self) -> None:
        """Load the list from Postgres (importing new folders once), or from the folders."""
        if self.pool is None:
            self.load()
            return
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, name, dataset_path, created_at FROM projects")
        self._projects = {r["id"]: Project(**dict(r)) for r in rows}
        on_disk = self._read_folders()
        new = [p for pid, p in on_disk.items() if pid not in self._projects]
        if new:
            async with self.pool.acquire() as conn:
                await conn.executemany(
                    "INSERT INTO projects (id, name, dataset_path, created_at) VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO NOTHING",
                    [(p.id, p.name, p.dataset_path, p.created_at) for p in new],
                )
            log.info("Imported %d project folder(s) into Postgres: %s", len(new), ", ".join(p.id for p in new))
            self._projects.update({p.id: p for p in new})
        for pid in self._projects.keys() - on_disk.keys():
            log.warning("Project %s is in the database but its folder %s is missing", pid, self.data_root / pid)

    def load(self) -> None:
        """Read every <id>/project.json under DATA_ROOT (the registry without a database)."""
        self._projects = self._read_folders()

    def _read_folders(self) -> dict[str, Project]:
        found: dict[str, Project] = {}
        for meta in sorted(self.data_root.glob("*/project.json")):
            try:
                project = Project.model_validate_json(meta.read_text())
            except (OSError, ValueError) as error:
                log.warning("Skipping unreadable %s: %s", meta, error)
                continue
            if project.id != meta.parent.name or not valid_id(project.id):
                log.warning("Skipping %s: id does not match its folder", meta)
                continue
            found[project.id] = project
        return found

    async def ensure_preset_project(self) -> None:
        """Create the COVID demo project once, if its dataset is available."""
        if PRESET_ID in self._projects:
            return
        try:
            await self.create(PRESET_NAME, project_id=PRESET_ID)
        except PresetMissing:
            log.warning("Preset dataset %s not found; not seeding %s", self.preset, PRESET_ID)

    async def create(self, name: str, project_id: str | None = None) -> Project:
        if not self.preset.is_file():
            raise PresetMissing(str(self.preset))
        project_id = project_id or new_id()
        folder = self.project_dir(project_id)
        folder.mkdir(parents=True, exist_ok=False)
        try:
            dataset = folder / "dataset.h5ad"
            _link_or_copy(self.preset, dataset)
            project = Project(id=project_id, name=name, dataset_path=str(dataset))
            _write_json(folder / "project.json", project.model_dump(mode="json"))
            if self.pool is not None:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO projects (id, name, dataset_path, created_at) VALUES ($1, $2, $3, $4)",
                        project.id, project.name, project.dataset_path, project.created_at,
                    )
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)  # don't leave half a project behind
            raise
        self._projects[project_id] = project
        return project

    def get(self, project_id: str) -> Project | None:
        return self._projects.get(project_id) if valid_id(project_id) else None

    def list(self) -> list[Project]:
        return sorted(self._projects.values(), key=lambda p: p.created_at, reverse=True)

    def project_dir(self, project_id: str) -> Path:
        if not valid_id(project_id):
            raise ValueError(f"invalid project id: {project_id!r}")
        return self.data_root / project_id


def _link_or_copy(source: Path, dest: Path) -> None:
    # A hard link costs no space and, unlike a symlink, resolves inside the sandbox containers.
    try:
        os.link(source, dest)
    except OSError as error:  # e.g. a different filesystem
        log.warning("Hard link %s -> %s failed (%s); copying instead", source, dest, error)
        shutil.copy2(source, dest)


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)
