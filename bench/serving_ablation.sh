#!/usr/bin/env bash
# Serving ablation: rerun the serving benchmark with vLLM in throughput mode
# (no speculative decoding), then always restore the normal interactive setup.
#   bash bench/serving_ablation.sh [n_list]       e.g. 1,4,8
# Logs in ~/workspace/logs/serving_*.log; marks completion in serving_ablation.done.
set -uo pipefail
cd "$(dirname "$0")/.."
N="${1:-1,4,8}"
LOGS="$HOME/workspace/logs"
rm -f "$LOGS/serving_ablation.done"

restore() {
  bash infra/serve_vllm.sh > "$LOGS/serve_restore.log" 2>&1
  echo "restored interactive vLLM (exit $?)" >> "$LOGS/serving_ablation.done"
}
trap restore EXIT

if MODE=throughput bash infra/serve_vllm.sh > "$LOGS/serve_throughput.log" 2>&1; then
  "$HOME/.local/bin/uv" run python -u -m bench.serving --label throughput --n "$N" > "$LOGS/serving_throughput.log" 2>&1
  echo "throughput run exit $?" > "$LOGS/serving_ablation.done"
else
  echo "throughput vLLM failed to start" > "$LOGS/serving_ablation.done"
fi
