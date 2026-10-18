"""Download and preprocess the benchmark datasets on the Brev box.

    uv run python -m bench.prepare_datasets [dataset ...]

For each dataset in bench/datasets.json: download the CELLxGENE .h5ad to
$DATA_ROOT/raw/<id>.h5ad (resumable), then run sandbox/preprocess.py in the
sandbox image into $DATA_ROOT/_reference/<id>/. Also builds the negative
control `wilk_shuffled` (condition labels permuted across donors). Folders
under _reference/ are not app projects. Skips work already done.
"""

import json
import subprocess
import sys
from pathlib import Path

from sandbox import kernel_manager as km

DATA_ROOT = Path("/home/ubuntu/workspace/data")
REPO = Path(__file__).resolve().parent.parent
DATASETS = json.loads((Path(__file__).parent / "datasets.json").read_text())


def download(key: str, url: str) -> Path:
    dest = DATA_ROOT / "raw" / f"{key}.h5ad"
    if key == "wilk" and (DATA_ROOT / "raw" / "covid_pbmc_wilk2020.h5ad").exists():
        dest = DATA_ROOT / "raw" / "covid_pbmc_wilk2020.h5ad"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    part = dest.with_suffix(".h5ad.part")
    subprocess.run(["curl", "-fsSL", "--retry", "3", "-C", "-", "-o", str(part), url], check=True)
    part.rename(dest)
    return dest


def docker_python(*args: str) -> None:
    subprocess.run(["docker", "run", "--rm", "-v", f"{DATA_ROOT}:/data", "-v", f"{REPO}:/repo:ro",
                    km.IMAGE, "python", *args], check=True)


def preprocess(key: str, raw: Path) -> Path:
    out = DATA_ROOT / "_reference" / key
    if (out / "dataset_summary.json").exists() and (out / "umap_points.json").exists():
        return out
    out.mkdir(parents=True, exist_ok=True)
    docker_python("/repo/sandbox/preprocess.py", f"/data/{raw.relative_to(DATA_ROOT)}",
                  f"/data/{out.relative_to(DATA_ROOT)}")
    return out


def shuffled_control(source: Path, key: str = "wilk_shuffled") -> Path:
    out = DATA_ROOT / "_reference" / key
    if (out / "dataset_summary.json").exists():
        return out
    out.mkdir(parents=True, exist_ok=True)
    docker_python("/repo/bench/shuffle_labels.py", f"/data/{source.relative_to(DATA_ROOT)}",
                  f"/data/{out.relative_to(DATA_ROOT)}")
    return out


def main(keys: list[str]) -> None:
    for key in keys or list(DATASETS):
        ds = DATASETS[key]
        print(f"== {key}: {ds['name']}", flush=True)
        raw = download(key, ds["url"])
        out = preprocess(key, raw)
        print(f"   ready: {out}", flush=True)
        if key == "wilk":
            print(f"   negative control: {shuffled_control(out)}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
