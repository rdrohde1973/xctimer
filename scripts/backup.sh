#!/usr/bin/env bash
# Nightly backup for XCTimer (handoff §6.5). Runs on Hetzner; the existing
# hetzner-backup-pull job lands ~/backups/ on the NAS automatically.
set -euo pipefail
APP_DIR="${APP_DIR:-$HOME/xctimer}"
DB_FILE="$APP_DIR/xctimer.db"
BACKUP_DEST="${BACKUP_DEST:-$HOME/backups/xctimer}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"
STAMP=$(date +%Y-%m-%d_%H%M%S)
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
PY="${PYTHON_BIN:-$APP_DIR/.venv/bin/python}"; [[ -x "$PY" ]] || PY=$(command -v python3)

# 1. WAL-safe hot snapshot (safe while the app is running; DO NOT plain-cp a live DB)
"$PY" - "$DB_FILE" "$WORK/xctimer.db" <<'PYEOF'
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as s, sqlite3.connect(sys.argv[2]) as d:
    s.backup(d)
PYEOF

# 2. Stage DB + config + NON-regenerable uploads + infra for cold-start restore
P="$WORK/payload"; mkdir -p "$P"; mv "$WORK/xctimer.db" "$P/"
for f in env secret.key; do [[ -f "$APP_DIR/$f" ]] && cp -p "$APP_DIR/$f" "$P/"; done
for sub in static/logos static/branding static/photos uploads; do   # adjust to final upload layout
  [[ -d "$APP_DIR/$sub" ]] && mkdir -p "$P/$sub" && cp -rp "$APP_DIR/$sub/." "$P/$sub/"
done
mkdir -p "$P/systemd" "$P/cloudflared"
cp -p "$HOME/.config/systemd/user/xctimer.service" "$P/systemd/" 2>/dev/null || true
find "$HOME/.cloudflared" -maxdepth 1 -type f -exec cp -p {} "$P/cloudflared/" \; 2>/dev/null || true
[[ -f "$APP_DIR/requirements.txt" ]] && cp -p "$APP_DIR/requirements.txt" "$P/" \
  || "$APP_DIR/.venv/bin/pip" freeze > "$P/requirements.txt" 2>/dev/null || true

# 3. Archive -> dest, rotate to RETAIN_DAYS
mkdir -p "$BACKUP_DEST"
tar -czf "$BACKUP_DEST/xctimer-${STAMP}.tar.gz" -C "$P" .
find "$BACKUP_DEST" -maxdepth 1 -name 'xctimer-*.tar.gz' -type f -mtime +"$RETAIN_DAYS" -delete
echo "[$(date -Iseconds)] xctimer backup complete -> $BACKUP_DEST"
