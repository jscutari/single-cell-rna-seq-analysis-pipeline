#!/usr/bin/env bash
# Rebuild the Brev box from scratch. Safe to run again: every step skips work already done.
#
# On a fresh box:
#   git clone https://github.com/jscutari/single-cell-rna-seq-analysis-pipeline.git ~/scrap
#   bash ~/scrap/infra/setup_brev.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE=/home/ubuntu/workspace
DATA_DIR="$WORKSPACE/data"
LOG_DIR="$WORKSPACE/logs"
HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"

VLLM_IMAGE=vllm/vllm-openai:v0.27.1
MODEL=nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4
DRAFT_MODEL=nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4-DFlash

# Wilk et al. 2020 (GEO GSE150728), annotated .h5ad from CZ CELLxGENE
COVID_URL=https://datasets.cellxgene.cziscience.com/8d7fad46-2f37-4aa0-ac9d-babbc36efb6f.h5ad
COVID_FILE="$DATA_DIR/raw/covid_pbmc_wilk2020.h5ad"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

step "GPU driver"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader

step "Docker"
if ! docker info >/dev/null 2>&1; then
  if ! command -v docker >/dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
  fi
  sudo usermod -aG docker "$USER"
  echo "Added $USER to the docker group. Log out, SSH back in, and rerun this script."
  exit 1
fi

step "NVIDIA container toolkit (GPU inside Docker)"
if ! docker run --rm --gpus all ubuntu:22.04 nvidia-smi -L >/dev/null 2>&1; then
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | sudo gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
  sudo apt-get update -q && sudo apt-get install -yq nvidia-container-toolkit
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
fi
docker run --rm --gpus all ubuntu:22.04 nvidia-smi -L

step "uv + Python env"
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
(cd "$REPO_DIR" && uv sync)

step "Workspace folders"
mkdir -p "$DATA_DIR/raw" "$LOG_DIR" "$HF_HOME"

step "vLLM image (~10 GB, first pull takes a few minutes)"
docker pull -q "$VLLM_IMAGE"

step "Background downloads (logs in $LOG_DIR)"
# Model weights go to the HF cache, which serve_vllm.sh mounts into the container.
# hf download skips files already in the cache, so rerunning is cheap.
UVX="$(command -v uvx)"
nohup env HF_HOME="$HF_HOME" "$UVX" --from huggingface_hub hf download "$MODEL" \
  >"$LOG_DIR/download_model.log" 2>&1 &
nohup env HF_HOME="$HF_HOME" "$UVX" --from huggingface_hub hf download "$DRAFT_MODEL" \
  >"$LOG_DIR/download_draft.log" 2>&1 &
# Download to .part and rename on success, so a half-finished file never looks complete.
if [ ! -s "$COVID_FILE" ]; then
  nohup sh -c "curl -fL --retry 3 -C - -o '$COVID_FILE.part' '$COVID_URL' && mv '$COVID_FILE.part' '$COVID_FILE'" \
    >"$LOG_DIR/download_covid.log" 2>&1 &
fi

step "Done"
echo "Downloads keep running in the background. Watch them with:"
echo "  tail -f $LOG_DIR/download_*.log"
echo "  du -sh $HF_HOME $COVID_FILE"
