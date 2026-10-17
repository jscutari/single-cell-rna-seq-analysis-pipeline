#!/usr/bin/env bash
# vLLM launch command for Nemotron 3.5 Lightning.
#
# Flags follow the model card's "1x H100" recipes (vllm/vllm-openai:v0.27.1):
#   bash infra/serve_vllm.sh               # interactive: DSpark speculative decoding (default)
#   MODE=throughput bash infra/serve_vllm.sh   # no speculative decoding, max batch (ablation)
#   NO_PREFIX_CACHE=1 bash infra/serve_vllm.sh # prefix caching off (ablation)
#
# Serves an OpenAI-compatible API on localhost:8000 as model "lightning".
# Logs: docker logs -f vllm
set -euo pipefail

MODE="${MODE:-interactive}"
NO_PREFIX_CACHE="${NO_PREFIX_CACHE:-0}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-131072}"
HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"

IMAGE=vllm/vllm-openai:v0.27.1
MODEL=nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4
DRAFT_MODEL=nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4-DSpark

# Shared by both recipes
args=(
  serve --model "$MODEL"
  --served-model-name lightning
  --host 0.0.0.0 --port 8000
  # The model supports 1M tokens; our agents need far less, and a shorter
  # limit leaves more GPU memory for KV cache, i.e. more agents at once.
  --max-model-len "$MAX_MODEL_LEN"
  # Leave ~12 GB free for the embedding + reranker models (step 11a).
  --gpu-memory-utilization 0.85
  --async-scheduling
  --mamba-backend flashinfer
  --mamba-cache-mode align
  --mamba-ssm-cache-dtype float16
  --enable-mamba-cache-stochastic-rounding
  --mamba-cache-philox-rounds 5
  # Splits the model's thinking into `reasoning_content`, separate from the answer.
  --reasoning-parser nemotron_v3
  --tool-call-parser qwen3_coder
  --enable-auto-tool-choice
)
env_args=()

if [ "$NO_PREFIX_CACHE" = 1 ]; then
  args+=(--no-enable-prefix-caching)
else
  # Every agent prompt starts with the same brief + dataset summary; vLLM reuses
  # that computed prefix instead of recomputing it for each request.
  args+=(--enable-prefix-caching)
fi

case "$MODE" in
  interactive)
    # A small draft model guesses 3 tokens ahead; the big model checks them in one pass.
    args+=(
      --max-num-seqs 128
      --speculative_config.model "$DRAFT_MODEL"
      --speculative_config.num_speculative_tokens 3
    )
    ;;
  throughput)
    env_args+=(-e VLLM_HUMMING_MOE_GEMM_TYPE=indexed)
    args+=(
      --max-num-seqs 256
      --max-num-batched-tokens 16384
      --moe-backend humming
      --linear-backend humming
      --mamba-ssu-algorithm horizontal
    )
    ;;
  *) echo "Unknown MODE=$MODE (use interactive or throughput)" >&2; exit 1 ;;
esac

docker rm -f vllm >/dev/null 2>&1 || true

# Port bound to localhost only: the API has no auth, so don't expose it to the internet.
docker run -d --name vllm \
  --gpus all --ipc=host \
  -p 127.0.0.1:8000:8000 \
  -v "$HF_HOME:/root/.cache/huggingface" \
  ${env_args[@]+"${env_args[@]}"} \
  --restart unless-stopped \
  --entrypoint vllm \
  "$IMAGE" "${args[@]}"

echo "Starting vLLM (MODE=$MODE, prefix cache $([ "$NO_PREFIX_CACHE" = 1 ] && echo off || echo on))."
echo "Waiting for http://localhost:8000/health (first start compiles kernels, can take several minutes)..."
for _ in $(seq 1 180); do
  if curl -sf localhost:8000/health >/dev/null; then
    echo "vLLM is up."
    curl -s localhost:8000/v1/models
    echo
    exit 0
  fi
  if [ "$(docker inspect -f '{{.State.Running}}' vllm 2>/dev/null)" != true ]; then
    echo "vLLM container exited. Last logs:" >&2
    docker logs --tail 50 vllm >&2
    exit 1
  fi
  sleep 10
done
echo "Still not healthy after 30 min. Check: docker logs -f vllm" >&2
exit 1
