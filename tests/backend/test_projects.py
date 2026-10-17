"""Projects: folders as the registry, preset seeding, hard links, validation, status."""

import json
import os

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.projects import PRESET_ID, ProjectRegistry, valid_id


def test_preset_project_is_seeded_with_a_hard_linked_dataset(client, data_root):
    projects = client.get("/api/projects").json()
    assert [p["id"] for p in projects] == [PRESET_ID]
    dataset = data_root / PRESET_ID / "dataset.h5ad"
    assert dataset.read_bytes() == b"fake h5ad"
    assert os.stat(dataset).st_ino == os.stat(data_root / "raw" / "covid_pbmc_wilk2020.h5ad").st_ino
    assert projects[0]["dataset_path"] == str(dataset)
    assert projects[0]["status"] == "created"


def test_seeding_is_idempotent_across_restarts(app, data_root, orchestrator, settings):
    with TestClient(app):
        pass
    with TestClient(create_app(settings, orchestrator=orchestrator)) as again:
        assert [p["id"] for p in again.get("/api/projects").json()] == [PRESET_ID]


def test_no_preset_dataset_means_no_seed_and_503_on_create(tmp_path, orchestrator):
    settings = Settings(data_root=tmp_path / "empty")
    with TestClient(create_app(settings, orchestrator=orchestrator)) as c:
        assert c.get("/api/projects").json() == []
        r = c.post("/api/projects", json={"name": "New"})
        assert r.status_code == 503
        assert [p.name for p in (tmp_path / "empty").iterdir()] == []  # nothing left behind


def test_create_project(client, data_root):
    r = client.post("/api/projects", json={"name": "  My analysis  "})
    assert r.status_code == 201
    project = r.json()
    assert project["name"] == "My analysis" and valid_id(project["id"]) and len(project["id"]) == 32
    folder = data_root / project["id"]
    assert json.loads((folder / "project.json").read_text())["name"] == "My analysis"
    assert (folder / "dataset.h5ad").read_bytes() == b"fake h5ad"
    assert client.get(f"/api/projects/{project['id']}").json() == project


def test_list_is_newest_first(client):
    first = client.post("/api/projects", json={"name": "First"}).json()
    second = client.post("/api/projects", json={"name": "Second"}).json()
    ids = [p["id"] for p in client.get("/api/projects").json()]
    assert ids.index(second["id"]) < ids.index(first["id"])


def test_projects_survive_a_restart(app, settings, orchestrator):
    with TestClient(app) as c:
        created = c.post("/api/projects", json={"name": "Keep me"}).json()
    with TestClient(create_app(settings, orchestrator=orchestrator)) as c:
        assert created["id"] in [p["id"] for p in c.get("/api/projects").json()]
        assert c.get(f"/api/projects/{created['id']}").json()["name"] == "Keep me"


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "   "}, {"name": "x" * 101}, {"name": 5}])
def test_invalid_names_are_rejected(client, body):
    assert client.post("/api/projects", json=body).status_code == 422


@pytest.mark.parametrize("project_id", ["missing", "UPPER", "a" * 65, "..", "a.b", "a-b"])
def test_unknown_or_invalid_ids_are_404(client, project_id):
    assert client.get(f"/api/projects/{project_id}").status_code == 404


def test_hard_link_failure_falls_back_to_a_copy(client, data_root, monkeypatch):
    def no_link(*_):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", no_link)
    project = client.post("/api/projects", json={"name": "Copied"}).json()
    dataset = data_root / project["id"] / "dataset.h5ad"
    assert dataset.read_bytes() == b"fake h5ad"
    assert os.stat(dataset).st_nlink == 1


def test_failed_create_leaves_no_folder(client, data_root, monkeypatch):
    def broken(*_):
        raise OSError("disk full")

    monkeypatch.setattr(os, "link", broken)
    monkeypatch.setattr("shutil.copy2", broken)
    before = set(p.name for p in data_root.iterdir())
    with pytest.raises(OSError):
        client.post("/api/projects", json={"name": "Broken"})
    assert set(p.name for p in data_root.iterdir()) == before


def test_registry_skips_bad_folders(data_root):
    (data_root / "_cache").mkdir()  # no project.json: not a project
    (data_root / "corrupt").mkdir()
    (data_root / "corrupt" / "project.json").write_text("{not json")
    (data_root / "mismatch").mkdir()
    (data_root / "mismatch" / "project.json").write_text(
        json.dumps({"id": "other", "name": "x", "dataset_path": "d", "status": "created", "created_at": "2026-10-17T00:00:00Z"})
    )
    registry = ProjectRegistry(data_root, data_root / "raw" / "covid_pbmc_wilk2020.h5ad")
    registry.load()
    assert registry.list() == []


def test_project_dir_rejects_invalid_ids(data_root):
    registry = ProjectRegistry(data_root, data_root / "raw" / "x")
    with pytest.raises(ValueError):
        registry.project_dir("../etc")


@pytest.mark.parametrize(
    ("events", "status"),
    [
        ([], "created"),
        ([("run_status", {"status": "running"})], "intake"),
        ([("run_status", {"status": "running"}), ("stage_done", {"stage": "intake", "summary": ""})], "intake"),
        ([("run_status", {"status": "running"}), ("stage_done", {"stage": "planning", "summary": ""})], "running"),
        ([("run_status", {"status": "running"}), ("stage_done", {"stage": "report", "summary": ""})], "done"),
        ([("run_status", {"status": "running"}), ("stage_done", {"stage": "failed", "summary": ""})], "failed"),
        ([("run_status", {"status": "running"}), ("stage_done", {"stage": "stopped", "summary": ""})], "stopped"),
    ],
)
def test_project_status_follows_the_run(client, app, events, status):
    for type_, payload in events:
        app.state.store.append(type_, PRESET_ID, payload)
    assert client.get(f"/api/projects/{PRESET_ID}").json()["status"] == status
    assert client.get("/api/projects").json()[0]["status"] == status
