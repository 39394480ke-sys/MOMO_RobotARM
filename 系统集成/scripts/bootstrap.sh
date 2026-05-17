#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_NAME="${ARM_ENV_NAME:-arm_rebot}"
PYTHON=(mamba run -n "$ENV_NAME" python)

mkdir -p .venv runtime/pids runtime/logs runtime/state
touch runtime/logs/system.log runtime/logs/web.log runtime/logs/vision.log runtime/logs/agent.log runtime/logs/gui.log

BASE_DEPS=(
  fastapi
  uvicorn
  pydantic
  pyyaml
  numpy
  requests
  opencv-contrib-python
)

ADVANCED_DEPS=(
  PyQt5
  pybullet
  sounddevice
  mediapipe
)

REAL_DEPS=(
  lerobot
  feetech-servo-sdk
  pyserial
)

INSTALL_ADVANCED=0
INSTALL_REAL=0
for arg in "$@"; do
  case "$arg" in
    --advanced) INSTALL_ADVANCED=1 ;;
    --real) INSTALL_REAL=1 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

echo "使用环境：$ENV_NAME"
"${PYTHON[@]}" -V
"${PYTHON[@]}" -m pip install --upgrade pip
"${PYTHON[@]}" -m pip install "${BASE_DEPS[@]}"

if [[ "$INSTALL_ADVANCED" == "1" ]]; then
  "${PYTHON[@]}" -m pip install "${ADVANCED_DEPS[@]}"
fi

if [[ "$INSTALL_REAL" == "1" ]]; then
  "${PYTHON[@]}" -m pip install "${REAL_DEPS[@]}"
fi

echo "bootstrap 完成。"

