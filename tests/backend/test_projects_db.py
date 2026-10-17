"""Projects in Postgres: source of truth, one-time folder import, failure cleanup."""

import asyncio
import json

import asyncpg
import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.db import _init_connection
from backend.main import create_app
from backend.projects import PRESET_ID

pytestmark = pytest.mark.db


@pytest.fixture
def pg_settings(data_root, pg_url) -> Settings:
    return Settings(data_root=data_root, agents="fake", store="postgres", database_url=pg_url,
                    write_interval=0.02, db_connect_timeout=3)


def sql(url: str, query: str, *args):
    async def run():
        conn = await asyncpg.connect(url)
        await _init_connection(conn)
        try:
            return await conn.fetch(query, *args)
        finally:
            await conn.close()

    return asyncio.run(run())


def write_folder(data_root, pid: str, name: str, created_at="2026-10-01T00:00:00+00:00"):
    folder = data_root / pid
    folder.mkdir()
    (folder / "project.json").write_text(json.dumps(
        {"id": pid, "name": name, "dataset_path": str(folder / "dataset.h5ad"), "status": "created", "created_at": created_at}))


def test_created_projects_are_rows(pg_settings, orchestrator, pg_url):
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        created = c.post("/api/projects", json={"name": "Row please"}).json()
    rows = sql(pg_url, "SELECT id, name FROM projects ORDER BY name")
    assert [(r["id"], r["name"]) for r in rows] == sorted([(PRESET_ID, "COVID-19 PBMC (Wilk et al. 2020)"), (created["id"], "Row please")], key=lambda x: x[1])


def test_existing_folders_are_imported_once(pg_settings, orchestrator, pg_url, data_root):
    write_folder(data_root, "legacy_project", "From before the database")
    for _ in range(2):  # two restarts
        with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
            names = [p["name"] for p in c.get("/api/projects").json()]
            assert "From before the database" in names
    rows = sql(pg_url, "SELECT count(*) AS n FROM projects WHERE id = 'legacy_project'")
    assert rows[0]["n"] == 1


def test_the_database_is_the_source_of_truth(pg_settings, orchestrator, pg_url, data_root):
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)):
        pass
    sql(pg_url, "UPDATE projects SET name = 'Renamed in the database' WHERE id = $1", PRESET_ID)
    (data_root / PRESET_ID / "project.json").unlink()  # the backup file is gone; the row still counts
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        assert [p["name"] for p in c.get("/api/projects").json()] == ["Renamed in the database"]


def test_a_row_whose_folder_is_missing_is_kept_and_logged(pg_settings, orchestrator, pg_url, data_root, caplog):
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        pid = c.post("/api/projects", json={"name": "Folder will vanish"}).json()["id"]
    import shutil

    shutil.rmtree(data_root / pid)
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        assert pid in [p["id"] for p in c.get("/api/projects").json()]
    assert f"Project {pid} is in the database but its folder" in caplog.text


def test_failed_insert_removes_the_new_folder(pg_settings, orchestrator, pg_url, data_root):
    with TestClient(create_app(pg_settings, orchestrator=orchestrator)) as c:
        sql(pg_url, "ALTER TABLE projects ADD CONSTRAINT short_names CHECK (length(name) < 5) NOT VALID")
        before = {p.name for p in data_root.iterdir()}
        with pytest.raises(asyncpg.CheckViolationError):
            c.post("/api/projects", json={"name": "Far too long"})
        assert {p.name for p in data_root.iterdir()} == before
        assert [p["name"] for p in c.get("/api/projects").json()] == ["COVID-19 PBMC (Wilk et al. 2020)"]


def test_preset_seeded_once_into_the_table(pg_settings, orchestrator, pg_url):
    for _ in range(2):
        with TestClient(create_app(pg_settings, orchestrator=orchestrator)):
            pass
    assert sql(pg_url, "SELECT count(*) AS n FROM projects")[0]["n"] == 1
