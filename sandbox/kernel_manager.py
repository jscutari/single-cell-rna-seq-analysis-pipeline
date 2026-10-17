"""Start/stop kernels, run cells, save .ipynb.

Each hypothesis gets its own Jupyter kernel inside a scrap-sandbox container
with no network and capped memory/CPU. Because --network none also blocks
localhost TCP, the kernel's ZMQ sockets use IPC transport: unix socket files
in a directory mounted into the container at /conn.

Layout on the host, per hypothesis:
  <project_dir>/processed.h5ad                      mounted read-only at /data
  <project_dir>/hypotheses/<hid>/                   mounted read-write at /work
  <project_dir>/hypotheses/<hid>/<hid>.ipynb        every cell, with outputs
  <project_dir>/hypotheses/<hid>/figures/*.png      every plot
  $KERNEL_DIR/<hid>/                                sockets + connection file

Smoke test (on the box):  uv run python -m sandbox.kernel_manager
"""

import asyncio
import base64
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import nbformat
from jupyter_client.asynchronous import AsyncKernelClient

from shared.events import Event, EventType, emit, set_sink
from shared.schemas import CellStatus, CodeCell, now

IMAGE = os.environ.get("SANDBOX_IMAGE", "scrap-sandbox")
KERNEL_DIR = Path(os.environ.get("KERNEL_DIR", "/home/ubuntu/workspace/kernels"))
MEMORY = os.environ.get("SANDBOX_MEMORY", "24g")
CPUS = os.environ.get("SANDBOX_CPUS", "4")
DEFAULT_TIMEOUT = 600  # seconds per cell
MAX_OUTPUT_CHARS = 12_000  # what agents see per stream; the notebook keeps everything

# Runs once when a kernel starts, so every hypothesis begins from the same state.
PREAMBLE = """
%matplotlib inline
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, scanpy as sc, matplotlib.pyplot as plt
pd.set_option("display.width", 200); pd.set_option("display.max_columns", 30)
plt.rcParams["figure.dpi"] = 100
GENESETS_DIR = "/opt/genesets"
adata = sc.read_h5ad("/data/processed.h5ad")
print(adata)
"""

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class _Kernel:
    hypothesis_id: str
    project_id: str
    container: str
    client: AsyncKernelClient
    work_dir: Path
    notebook: nbformat.NotebookNode = field(default_factory=nbformat.v4.new_notebook)
    next_index: int = 0


_kernels: dict[str, _Kernel] = {}


async def _docker(*args: str, check: bool = True) -> str:
    proc = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if check and proc.returncode != 0:
        raise RuntimeError(f"docker {args[0]} failed: {err.decode().strip()}")
    return out.decode().strip()


def _connection_info(ip: str, key: str) -> dict:
    # With IPC transport, "ip" is a socket path prefix and each "port" is just a
    # suffix: the shell channel lives at <ip>-1, iopub at <ip>-2, and so on.
    return {
        "transport": "ipc", "ip": ip, "key": key, "signature_scheme": "hmac-sha256",
        "shell_port": 1, "iopub_port": 2, "stdin_port": 3, "control_port": 4, "hb_port": 5,
        "kernel_name": "python3",
    }


async def start_kernel(hypothesis_id: str, project_id: str, project_dir: str | Path) -> None:
    """Start a sandboxed kernel for this hypothesis and run the preamble (loads `adata`)."""
    if hypothesis_id in _kernels:
        return
    project_dir = Path(project_dir)
    work_dir = project_dir / "hypotheses" / hypothesis_id
    (work_dir / "figures").mkdir(parents=True, exist_ok=True)
    conn_dir = KERNEL_DIR / hypothesis_id
    conn_dir.mkdir(parents=True, exist_ok=True)
    for stale in conn_dir.glob("kernel-*"):
        stale.unlink()

    key = uuid.uuid4().hex
    (conn_dir / "kernel.json").write_text(json.dumps(_connection_info("/conn/kernel", key)))

    container = f"scrap-kernel-{hypothesis_id[:12]}"
    await _docker("rm", "-f", container, check=False)
    await _docker(
        "run", "-d", "--name", container,
        "--network", "none",
        "--memory", MEMORY, "--cpus", CPUS, "--pids-limit", "512",
        "--init",  # tini as PID 1: forwards SIGINT to the kernel, reaps zombies
        "-v", f"{project_dir.resolve()}:/data:ro",
        "-v", f"{work_dir.resolve()}:/work",
        "-v", f"{conn_dir.resolve()}:/conn",
        IMAGE, "python", "-m", "ipykernel_launcher", "-f", "/conn/kernel.json",
    )

    client = AsyncKernelClient()
    client.load_connection_info(_connection_info(str(conn_dir / "kernel"), key))
    client.start_channels()
    await client.wait_for_ready(timeout=120)

    kernel = _Kernel(hypothesis_id, project_id, container, client, work_dir)
    _kernels[hypothesis_id] = kernel
    result = await _execute(kernel, PREAMBLE, timeout=300)
    if result["error"]:
        raise RuntimeError(f"Kernel preamble failed:\n{result['stderr']}")


async def _execute(kernel: _Kernel, source: str, timeout: float) -> dict:
    """Run code; collect stdout, stderr, PNGs and notebook outputs. Raises TimeoutError."""
    stdout, stderr, pngs, outputs = [], [], [], []
    error = False

    def on_msg(msg: dict) -> None:
        nonlocal error
        kind, content = msg["msg_type"], msg["content"]
        if kind in ("stream", "display_data", "execute_result", "error"):
            outputs.append(nbformat.v4.output_from_msg(msg))
        if kind == "stream":
            (stdout if content["name"] == "stdout" else stderr).append(content["text"])
        elif kind in ("display_data", "execute_result"):
            data = content["data"]
            if "image/png" in data:
                pngs.append(data["image/png"])
            elif "text/plain" in data:
                stdout.append(data["text/plain"] + "\n")
        elif kind == "error":
            error = True
            stderr.append(_ANSI.sub("", "\n".join(content["traceback"])))

    reply = await kernel.client.execute_interactive(
        source, output_hook=on_msg, timeout=timeout, store_history=True
    )
    return {
        "stdout": "".join(stdout), "stderr": "".join(stderr), "pngs": pngs, "outputs": outputs,
        "error": error or reply["content"]["status"] != "ok",
        "execution_count": reply["content"].get("execution_count"),
    }


def _clip(text: str) -> str:
    """Keep the start and end of long output; small models drown in huge tables."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    half = MAX_OUTPUT_CHARS // 2
    return f"{text[:half]}\n... [{len(text) - MAX_OUTPUT_CHARS} chars clipped] ...\n{text[-half:]}"


async def run_cell(hypothesis_id: str, source: str, timeout: float = DEFAULT_TIMEOUT) -> CodeCell:
    """Run one cell. Emits cell_started/cell_finished and appends the cell to the notebook."""
    kernel = _kernels[hypothesis_id]
    cell = CodeCell(hypothesis_id=hypothesis_id, index=kernel.next_index, source=source,
                    status=CellStatus.running, started_at=now())
    kernel.next_index += 1
    emit(Event(type=EventType.cell_started, project_id=kernel.project_id, payload=cell))

    nb_cell = nbformat.v4.new_code_cell(source)
    try:
        result = await _execute(kernel, source, timeout)
        cell.status = CellStatus.error if result["error"] else CellStatus.ok
        cell.stdout, cell.stderr = _clip(result["stdout"]), _clip(result["stderr"])
        nb_cell.outputs, nb_cell.execution_count = result["outputs"], result["execution_count"]
        for i, png in enumerate(result["pngs"]):
            path = kernel.work_dir / "figures" / f"cell{cell.index:03d}_{i}.png"
            path.write_bytes(base64.b64decode(png))
            cell.figure_paths.append(str(path))
    except TimeoutError:
        cell.status = CellStatus.timeout
        cell.stderr = f"Cell exceeded the {timeout:.0f}s time limit and was interrupted."
        await _recover(kernel)

    cell.ended_at = now()
    kernel.notebook.cells.append(nb_cell)
    nbformat.write(kernel.notebook, kernel.work_dir / f"{hypothesis_id}.ipynb")
    emit(Event(type=EventType.cell_finished, project_id=kernel.project_id, payload=cell))
    return cell


async def _recover(kernel: _Kernel) -> None:
    """After a timeout: interrupt; if the kernel still won't answer, restart it from the preamble."""
    await _docker("kill", "--signal", "SIGINT", kernel.container, check=False)
    try:
        await kernel.client.execute_interactive("pass", timeout=20)
        return
    except TimeoutError:
        pass
    hid, pid, project_dir = kernel.hypothesis_id, kernel.project_id, kernel.work_dir.parent.parent
    notebook, next_index = kernel.notebook, kernel.next_index
    await stop_kernel(hid)
    await start_kernel(hid, pid, project_dir)
    # Keep the notebook history; variables from earlier cells are gone.
    _kernels[hid].notebook, _kernels[hid].next_index = notebook, next_index


async def stop_kernel(hypothesis_id: str) -> None:
    kernel = _kernels.pop(hypothesis_id, None)
    if kernel is None:
        return
    kernel.client.stop_channels()
    await _docker("rm", "-f", kernel.container, check=False)


async def stop_all() -> None:
    await asyncio.gather(*(stop_kernel(h) for h in list(_kernels)))


async def _smoke_test() -> None:
    set_sink(lambda e: print(f"  event: {e.type} cell={e.payload.get('index')} {e.payload.get('status')}"))
    project_dir = Path("/home/ubuntu/workspace/data/covid_pbmc")
    hid = "smoketest"
    await start_kernel(hid, "smoke", project_dir)
    try:
        for src in [
            "adata.obs.groupby(['disease', 'donor_id'], observed=True).size().unstack(0).fillna(0).astype(int)",
            "sc.pl.umap(adata, color='cell.type.coarse', show=False); plt.show()\nprint('plotted')",
            "1 / 0",
        ]:
            cell = await run_cell(hid, src)
            print(f"[{cell.status}] figs={len(cell.figure_paths)}\n{cell.stdout[:400]}{cell.stderr[-300:]}\n")
        cell = await run_cell(hid, "import urllib.request\nurllib.request.urlopen('https://example.com', timeout=5)")
        print(f"[network blocked: {cell.status == CellStatus.error}] {cell.stderr.strip().splitlines()[-1]}\n")
        cell = await run_cell(hid, "while True: pass", timeout=5)
        print(f"[timeout handled: {cell.status == CellStatus.timeout}]")
        cell = await run_cell(hid, "print('still alive, adata has', adata.n_obs, 'cells')")
        print(f"[{cell.status}] {cell.stdout}")
        print("notebook:", project_dir / "hypotheses" / hid / f"{hid}.ipynb")
    finally:
        await stop_all()


if __name__ == "__main__":
    asyncio.run(_smoke_test())
