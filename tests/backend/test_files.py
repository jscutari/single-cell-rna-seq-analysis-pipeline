"""Files and findings from project_state.json, and safe file serving."""

import json
import os

import pytest

from backend.projects import PRESET_ID
from backend.routes.files import resolve_inside

BASE = f"/api/projects/{PRESET_ID}"


@pytest.fixture
def project_dir(client, data_root):
    folder = data_root / PRESET_ID
    fig = folder / "hypotheses" / "h1" / "figures"
    fig.mkdir(parents=True)
    (fig / "cell001_0.png").write_bytes(b"\x89PNG fake")
    (fig / "with space.png").write_bytes(b"png2")
    (folder / "hypotheses" / "h1" / "h1.ipynb").write_text('{"cells": []}')
    (folder / "report.md").write_text("# Report")
    state = {
        "stage": "report",
        "files": [
            {"id": "a", "project_id": PRESET_ID, "name": "report.md", "kind": "text", "size_bytes": 8,
             "path": "report.md", "added_at": "2026-10-17T00:00:00Z", "summary": "Final report"},
            {"id": "b", "project_id": PRESET_ID, "name": "cell001_0.png", "kind": "image", "size_bytes": 9,
             "path": "hypotheses/h1/figures/cell001_0.png", "added_at": "2026-10-17T00:00:00Z", "summary": None},
        ],
        "findings": [
            {"finding": {"id": "f1", "claim": "ISG up"}, "hypothesis_title": "ISG", "figure": "hypotheses/h1/figures/cell001_0.png",
             "notebook": "hypotheses/h1/h1.ipynb", "chart": {"type": "bar", "xLabel": "score", "bars": []}},
            {"finding": {"id": "f2", "claim": "No table"}, "hypothesis_title": "HLA", "figure": None, "notebook": None, "chart": None},
        ],
    }
    (folder / "project_state.json").write_text(json.dumps(state))
    return folder


def test_files_list_has_urls(client, project_dir):
    files = client.get(f"{BASE}/files").json()
    assert [f["url"] for f in files] == [f"{BASE}/files/report.md", f"{BASE}/files/hypotheses/h1/figures/cell001_0.png"]
    assert files[0]["summary"] == "Final report"


def test_findings_are_finding_cards(client, project_dir):
    cards = client.get(f"{BASE}/findings").json()
    assert [c["finding"]["id"] for c in cards] == ["f1", "f2"]
    assert cards[0]["chart"]["type"] == "bar" and cards[0]["mock"] is False
    assert cards[0]["figure_url"] == f"{BASE}/files/hypotheses/h1/figures/cell001_0.png"
    assert cards[0]["notebook_url"] == f"{BASE}/files/hypotheses/h1/h1.ipynb"
    assert cards[1]["chart"] is None and cards[1]["figure_url"] is None


def test_no_results_yet_means_empty_lists(client):
    assert client.get(f"{BASE}/files").json() == []
    assert client.get(f"{BASE}/findings").json() == []


@pytest.mark.parametrize("path", ["files", "findings", "files/report.md"])
def test_unknown_project_is_404(client, path):
    assert client.get(f"/api/projects/nope/{path}").status_code == 404


def test_serves_files_with_content_types(client, project_dir):
    r = client.get(f"{BASE}/files/hypotheses/h1/figures/cell001_0.png")
    assert r.status_code == 200 and r.content == b"\x89PNG fake" and r.headers["content-type"] == "image/png"
    assert client.get(f"{BASE}/files/report.md").headers["content-type"].startswith("text/markdown")
    assert client.get(f"{BASE}/files/hypotheses/h1/h1.ipynb").headers["content-type"] == "application/json"
    assert client.get(f"{BASE}/files/hypotheses/h1/figures/with%20space.png").content == b"png2"


def test_serves_the_dataset_hard_link(client, project_dir):
    assert client.get(f"{BASE}/files/dataset.h5ad").content == b"fake h5ad"


@pytest.mark.parametrize(
    "path",
    ["missing.png", "hypotheses", "hypotheses/h1", "../raw/covid_pbmc_wilk2020.h5ad", "..%2Fraw%2Fcovid_pbmc_wilk2020.h5ad",
     "hypotheses/../../raw/covid_pbmc_wilk2020.h5ad", "%2Fetc%2Fpasswd", "%2e%2e/%2e%2e/etc/passwd"],
)
def test_rejects_missing_directories_and_traversal(client, project_dir, path):
    assert client.get(f"{BASE}/files/{path}").status_code == 404


def test_rejects_symlinks_pointing_outside(client, project_dir, data_root, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    os.symlink(secret, project_dir / "link.txt")
    assert client.get(f"{BASE}/files/link.txt").status_code == 404


def test_allows_symlinks_that_stay_inside(client, project_dir):
    os.symlink(project_dir / "report.md", project_dir / "alias.md")
    assert client.get(f"{BASE}/files/alias.md").text == "# Report"


@pytest.mark.parametrize("relative", ["", "/etc/passwd", "\\windows", "a\x00b", "../x"])
def test_resolve_inside_rejects(tmp_path, relative):
    assert resolve_inside(tmp_path, relative) is None


def test_resolve_inside_accepts_nested_files(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.txt").write_text("x")
    assert resolve_inside(tmp_path, "a/b.txt") == (tmp_path / "a" / "b.txt").resolve()
