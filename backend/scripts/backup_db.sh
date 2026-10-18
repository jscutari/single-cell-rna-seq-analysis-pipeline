#!/usr/bin/env bash
# Dump the SCRAP database (docker compose service "db") to a gzipped SQL file.
# Keeps the newest $BACKUP_KEEP dumps (default 10) in $BACKUP_DIR
# (default ~/workspace/backups). Copy one off the box before the demo:
#   scp <box>:~/workspace/backups/scrap-<time>.sql.gz .
# Restore into a running database (replaces its tables):
#   gunzip -c scrap-<time>.sql.gz | docker compose exec -T db sh -c 'psql -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
set -euo pipefail
cd "$(dirname "$0")/../.."

OUT_DIR="${BACKUP_DIR:-$HOME/workspace/backups}"
KEEP="${BACKUP_KEEP:-10}"
mkdir -p "$OUT_DIR"

file="$OUT_DIR/scrap-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
# Write to .part and rename on success, so a failed dump never looks complete.
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' | gzip > "$file.part"
mv "$file.part" "$file"

# Keep the newest $KEEP dumps.
ls -1t "$OUT_DIR"/scrap-*.sql.gz | tail -n +"$((KEEP + 1))" | while read -r old; do rm -f -- "$old"; done
echo "$file"
