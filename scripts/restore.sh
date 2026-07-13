#!/usr/bin/env bash
# Restore XCTimer from a backup archive produced by scripts/backup.sh (handoff §6.5).
# Usage: scripts/restore.sh /path/to/xctimer-YYYY-MM-DD_HHMMSS.tar.gz
# Test this once right after the first prod deploy — an untested backup isn't a backup.
set -euo pipefail
ARCHIVE="${1:?usage: restore.sh <archive.tar.gz>}"
APP_DIR="${APP_DIR:-$HOME/xctimer}"
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT

echo "Extracting $ARCHIVE ..."
tar -xzf "$ARCHIVE" -C "$WORK"

mkdir -p "$APP_DIR"
# 1. Database + secrets
cp -p "$WORK/xctimer.db" "$APP_DIR/xctimer.db"
for f in env secret.key requirements.txt; do
  [[ -f "$WORK/$f" ]] && cp -p "$WORK/$f" "$APP_DIR/$f"
done
# 2. Uploads (adjust to final layout)
for sub in static/logos static/branding static/photos uploads; do
  [[ -d "$WORK/$sub" ]] && mkdir -p "$APP_DIR/$sub" && cp -rp "$WORK/$sub/." "$APP_DIR/$sub/"
done
# 3. Python env
python3 -m venv "$APP_DIR/.venv" 2>/dev/null || true
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
# 4. systemd unit + cloudflared creds
[[ -f "$WORK/systemd/xctimer.service" ]] && \
  cp -p "$WORK/systemd/xctimer.service" "$HOME/.config/systemd/user/" && \
  systemctl --user daemon-reload
if [[ -d "$WORK/cloudflared" ]]; then
  mkdir -p "$HOME/.cloudflared"
  cp -p "$WORK/cloudflared/." "$HOME/.cloudflared/" 2>/dev/null || true
fi

echo "Restore staged. Start with: systemctl --user restart xctimer.service"
