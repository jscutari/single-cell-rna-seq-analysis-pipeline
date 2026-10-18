#!/usr/bin/env bash
# Keep an SSH tunnel to the box's backend open: localhost:8080 -> box:8080.
# Reconnects automatically when the connection drops. Run on your laptop:
#   bash infra/tunnel.sh [ssh-host]        (default: consistent-brown-moth; Ctrl-C to stop)
HOST="${1:-consistent-brown-moth}"
while true; do
  ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
      -o ConnectTimeout=15 -L 8080:localhost:8080 "$HOST"
  echo "$(date +%H:%M:%S) tunnel dropped; reconnecting in 3s" >&2
  sleep 3
done
