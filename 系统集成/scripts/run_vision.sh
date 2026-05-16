#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
mamba run -n "${MOMO_ENV_NAME:-momo_rebot}" python - <<'PY'
from integration.config_loader import load_config
from integration.process_manager import ProcessManager
config = load_config()
config["services"]["vision"]["enabled"] = True
print(ProcessManager(config).start_service("vision"))
PY

