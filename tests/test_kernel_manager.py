"""sandbox/kernel_manager.py. Unit tests run anywhere; integration tests need the Brev box
(Docker, the scrap-sandbox image and the preprocessed COVID data)."""

import json
import shutil
import subprocess
from pathlib import Path

import nbformat
import pytest

from sandbox import kernel_manager as km
from shared.schemas import CellStatus

DATA = Path("/home/ubuntu/workspace/data/covid_pbmc")


def test_connection_info_uses_ipc_sockets():
    info = km._connection_info("/conn/kernel", "k")
    assert info["transport"] == "ipc" and info["ip"] == "/conn/kernel" and info["key"] == "k"
    assert sorted(info[f"{c}_port"] for c in ("shell", "iopub", "stdin", "control", "hb")) == [1, 2, 3, 4, 5]


def test_clip_keeps_start_and_end():
    short = "x" * 100
    assert km._clip(short) == short
    long = "A" * km.MAX_OUTPUT_CHARS + "B" * km.MAX_OUTPUT_CHARS
    clipped = km._clip(long)
    assert clipped.startswith("A") and clipped.endswith("B") and "chars clipped" in clipped
    assert len(clipped) < km.MAX_OUTPUT_CHARS + 100


def test_preamble_loads_data_and_helpers_and_keeps_a_protected_copy():
    assert 'sc.read_h5ad("/data/processed.h5ad")' in km.PREAMBLE
    assert "from scrap_tools import *" in km.PREAMBLE and "_ADATA = adata" in km.PREAMBLE


def _box_ready() -> bool:
    if not shutil.which("docker") or not (DATA / "processed.h5ad").exists():
        return False
    return subprocess.run(["docker", "image", "inspect", km.IMAGE], capture_output=True).returncode == 0


box = pytest.mark.skipif(not _box_ready(), reason="needs Docker, the scrap-sandbox image and COVID data")


@pytest.fixture
async def kernel(tmp_path, events):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "processed.h5ad").hardlink_to(DATA / "processed.h5ad")
    hid = f"test{tmp_path.name[-8:]}"
    await km.start_kernel(hid, "p", project)
    yield hid, project
    await km.stop_kernel(hid)


@pytest.mark.integration
@box
async def test_cells_outputs_figures_and_notebook(kernel, events):
    hid, project = kernel
    ok = await km.run_cell(hid, "print(adata.n_obs)")
    assert ok.status == CellStatus.ok and ok.stdout.strip() == "44649" and ok.index == 0

    fig = await km.run_cell(hid, "plt.plot([1, 2]); plt.show()")
    assert fig.status == CellStatus.ok and len(fig.figure_paths) == 1 and Path(fig.figure_paths[0]).exists()

    err = await km.run_cell(hid, "1 / 0")
    assert err.status == CellStatus.error and "ZeroDivisionError" in err.stderr and "\x1b[" not in err.stderr

    helpers = await km.run_cell(hid, "print(callable(pseudobulk), len(load_geneset('MSigDB_Hallmark_2020', "
                                     "'Interferon Alpha Response')) > 50)")
    assert helpers.stdout.strip() == "True True"

    nb = nbformat.read(project / "hypotheses" / hid / f"{hid}.ipynb", as_version=4)
    assert [c.source for c in nb.cells][:3] == ["print(adata.n_obs)", "plt.plot([1, 2]); plt.show()", "1 / 0"]
    assert any(o.output_type == "display_data" for o in nb.cells[1].outputs)
    types = [(e.type, e.payload["index"]) for e in events if e.type.startswith("cell_")]
    assert types[:2] == [("cell_started", 0), ("cell_finished", 0)]


@pytest.mark.integration
@box
async def test_sandbox_has_no_network(kernel):
    hid, _ = kernel
    cell = await km.run_cell(hid, "import urllib.request\nurllib.request.urlopen('https://example.com', timeout=5)")
    assert cell.status == CellStatus.error and "URLError" in cell.stderr


@pytest.mark.integration
@box
async def test_data_is_read_only(kernel):
    hid, _ = kernel
    cell = await km.run_cell(hid, "open('/data/new_file', 'w')")
    assert cell.status == CellStatus.error and ("Read-only" in cell.stderr or "Permission" in cell.stderr)


@pytest.mark.integration
@box
async def test_timeout_interrupts_and_kernel_survives(kernel):
    hid, _ = kernel
    await km.run_cell(hid, "keep = 41")
    cell = await km.run_cell(hid, "while True: pass", timeout=3)
    assert cell.status == CellStatus.timeout and "time limit" in cell.stderr
    after = await km.run_cell(hid, "print(keep + 1)")
    assert after.status == CellStatus.ok and after.stdout.strip() == "42"


@pytest.mark.integration
@box
async def test_stop_kernel_removes_the_container(tmp_path, events):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "processed.h5ad").hardlink_to(DATA / "processed.h5ad")
    await km.start_kernel("stoptest", "p", project)
    await km.stop_kernel("stoptest")
    names = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
    assert "scrap-kernel-stoptest" not in names
