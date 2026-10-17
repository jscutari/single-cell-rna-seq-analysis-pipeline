#!/usr/bin/env bash
# Run tests/sandbox inside the scrap-sandbox image (scanpy, pydeseq2, ...).
# The repo is mounted read-only; pytest is installed into the throwaway container.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
docker run --rm -v "$REPO:/repo:ro" -w /repo -e PYTHONDONTWRITEBYTECODE=1 scrap-sandbox sh -c \
  'pip install --user -q --disable-pip-version-check pytest && \
   python -m pytest -q -p no:cacheprovider -c /dev/null --noconftest --rootdir /repo tests/sandbox "$@"' -- "$@"
