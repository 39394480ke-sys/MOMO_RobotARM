#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${MOMO_PROJECT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON_BIN="${MOMO_PYTHON_BIN:-$(command -v python3)}"
TEMPLATE="$PROJECT_ROOT/scripts/com.momo.robotarm.backup.plist.example"
PLIST="$HOME/Library/LaunchAgents/com.momo.robotarm.backup.plist"
LOG_DIR="$HOME/Library/Logs/MOMORobotArmBackup"

mkdir -p "$(dirname "$PLIST")" "$LOG_DIR"
python3 - "$TEMPLATE" "$PLIST" "$HOME" "$PROJECT_ROOT" "$PYTHON_BIN" <<'PY'
from pathlib import Path
import sys

template, output, home, project, python = sys.argv[1:]
text = Path(template).read_text(encoding="utf-8")
text = text.replace("__HOME__", home).replace("__PROJECT_ROOT__", project).replace("__PYTHON_BIN__", python)
Path(output).write_text(text, encoding="utf-8")
PY

plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/com.momo.robotarm.backup"
echo "Mac backup LaunchAgent installed."
