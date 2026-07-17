#!/usr/bin/env bash
set -euo pipefail

BEGIN_MARKER="# BEGIN MOMO ROBOTARM BACKUP"
END_MARKER="# END MOMO ROBOTARM BACKUP"
PROJECT_ROOT="${MOMO_PROJECT_ROOT:-/home/fibo/MOMO_RobotARM}"
PYTHON_BIN="${MOMO_PYTHON_BIN:-/home/fibo/miniforge3/bin/python}"
BACKUP_ROOT="${MOMO_BACKUP_ROOT:-/home/fibo/MOMO_RobotARM-local-backups}"
tmp_current="$(mktemp)"
tmp_new="$(mktemp)"
trap 'rm -f "$tmp_current" "$tmp_new"' EXIT

crontab -l >"$tmp_current" 2>/dev/null || true
awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
  $0 == begin { inside = 1; next }
  $0 == end { inside = 0; next }
  !inside { print }
' "$tmp_current" >"$tmp_new"

{
  printf '%s\n' "$BEGIN_MARKER"
  printf '15 3 * * * %q %q >> %q 2>&1\n' \
    "$PYTHON_BIN" "$PROJECT_ROOT/scripts/backup_board_local_data.py" "$BACKUP_ROOT/backup.log"
  printf '%s\n' "$END_MARKER"
} >>"$tmp_new"

mkdir -p "$BACKUP_ROOT"
crontab "$tmp_new"
"$PYTHON_BIN" "$PROJECT_ROOT/scripts/backup_board_local_data.py" \
  --project-root "$PROJECT_ROOT" --backup-root "$BACKUP_ROOT"
echo "Board backup cron installed."
