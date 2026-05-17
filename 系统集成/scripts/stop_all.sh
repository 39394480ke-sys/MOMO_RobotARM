#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
mamba run -n "${ARM_ENV_NAME:-arm_rebot}" python 一键停止.py

