#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
mamba run -n "${ARM_ENV_NAME:-arm_rebot}" python - <<'PY'
from integration.config_loader import load_config
from integration.process_manager import ProcessManager
config = load_config()
config["services"]["web_api"]["enabled"] = True
print(ProcessManager(config).start_service("web_api"))
PY

