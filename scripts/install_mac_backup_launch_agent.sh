#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${MOMO_PROJECT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON_BIN="${MOMO_PYTHON_BIN:-$(command -v python3)}"
TEMPLATE="$PROJECT_ROOT/scripts/com.momo.robotarm.backup.plist.example"
PLIST="$HOME/Library/LaunchAgents/com.momo.robotarm.backup.plist"
LOG_DIR="$HOME/Library/Logs/MOMORobotArmBackup"
RUNTIME_DIR="$HOME/Library/Application Support/MOMORobotArmBackup"
SCRIPT_PATH="$RUNTIME_DIR/pull_board_backups_to_mac.py"

mkdir -p "$(dirname "$PLIST")" "$LOG_DIR" "$RUNTIME_DIR"
cp "$PROJECT_ROOT/scripts/pull_board_backups_to_mac.py" "$SCRIPT_PATH"
cp "$PROJECT_ROOT/scripts/backup_board_local_data.py" "$RUNTIME_DIR/backup_board_local_data.py"
python3 - "$TEMPLATE" "$PLIST" "$HOME" "$PYTHON_BIN" "$SCRIPT_PATH" <<'PY'
from pathlib import Path
import sys

template, output, home, python, script = sys.argv[1:]
text = Path(template).read_text(encoding="utf-8")
text = text.replace("__HOME__", home).replace("__PYTHON_BIN__", python).replace("__SCRIPT_PATH__", script)
Path(output).write_text(text, encoding="utf-8")
PY

plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/com.momo.robotarm.backup"
echo "Mac backup LaunchAgent installed."
