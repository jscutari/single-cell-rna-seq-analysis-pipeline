#!/usr/bin/env bash
# Start (or restart) the backend on the Brev box, in the background.
#   bash infra/run_backend.sh          # start, or restart if running
#   bash infra/run_backend.sh stop
# Logs: ~/workspace/logs/backend.log. Needs Postgres up (docker compose up -d db) and .env.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$HOME/workspace/backend.pid"
LOG="$HOME/workspace/logs/backend.log"
mkdir -p "$(dirname "$LOG")"

stop() {
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill "$(cat "$PID_FILE")"
    for _ in $(seq 1 20); do kill -0 "$(cat "$PID_FILE")" 2>/dev/null || break; sleep 0.5; done
    echo "stopped backend (pid $(cat "$PID_FILE"))"
  fi
  rm -f "$PID_FILE"
}

if [ "${1:-}" = "stop" ]; then
  stop
  exit 0
fi

stop
cd "$REPO_DIR"
# One worker, no --reload: the orchestrator keeps runs in this process's memory.
nohup "$HOME/.local/bin/uv" run uvicorn backend.main:app --host 127.0.0.1 --port 8080 >> "$LOG" 2>&1 < /dev/null &
echo $! > "$PID_FILE"
for _ in $(seq 1 60); do
  if curl -sf -m 2 localhost:8080/api/health; then
    echo
    echo "backend up (pid $(cat "$PID_FILE")), log: $LOG"
    exit 0
  fi
  sleep 1
done
echo "backend did not become healthy; see $LOG" >&2
exit 1
