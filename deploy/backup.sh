#!/bin/bash
# Copies the database (and the code hash key, if it is a file) to a dated folder
# and removes backups older than KEEP_DAYS. Safe to run while the service is
# running: it uses SQLite's own backup, not a file copy.
#
#   sudo -u eliddi /opt/eliddi-backend/deploy/backup.sh
#
# Settings can be overridden from the environment.
set -euo pipefail

DB="${ELIDDI_DATABASE:-/var/lib/eliddi/eliddi.sqlite3}"
DEST="${BACKUP_DIR:-/var/backups/eliddi}"
KEEP_DAYS="${KEEP_DAYS:-30}"
PYTHON="${PYTHON:-/opt/eliddi-backend/venv/bin/python}"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$DEST/$stamp"
mkdir -p "$target"
chmod 700 "$DEST" "$target"

"$PYTHON" - "$DB" "$target/eliddi.sqlite3" <<'PY'
import sqlite3, sys
source = sqlite3.connect(sys.argv[1])
copy = sqlite3.connect(sys.argv[2])
source.backup(copy)
copy.close()
source.close()
PY

chmod 600 "$target/eliddi.sqlite3"

key="$(dirname "$DB")/code_hash_key"
if [ -f "$key" ]; then
    cp "$key" "$target/code_hash_key"
    chmod 600 "$target/code_hash_key"
fi

find "$DEST" -mindepth 1 -maxdepth 1 -type d -mtime "+$KEEP_DAYS" -exec rm -rf {} +
echo "Backed up to $target"
