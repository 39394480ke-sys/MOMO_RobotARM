#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
mamba run -n "${MOMO_ENV_NAME:-momo_rebot}" python 一键启动.py --mode dry_run

