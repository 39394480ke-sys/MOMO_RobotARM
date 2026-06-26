#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="${ARM_ENV_NAME:-momo_rebot}"
PYTHON_VERSION="${ARM_PYTHON_VERSION:-3.11}"
INSTALL_OPTIONAL=0
MINIFORGE_INSTALLER="${MINIFORGE_INSTALLER:-$HOME/Miniforge3-Linux-aarch64.sh}"

for arg in "$@"; do
  case "$arg" in
    --optional)
      INSTALL_OPTIONAL=1
      ;;
    -h|--help)
      echo "Usage: scripts/bootstrap_arm.sh [--optional]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This bootstrap is intended for Ubuntu/Linux ARM boards." >&2
fi

ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64)
    ;;
  *)
    echo "Warning: expected ARM64/aarch64, got $ARCH." >&2
    ;;
esac

echo "Installing Ubuntu system packages..."
sudo apt-get update
sudo apt-get install -y \
  build-essential \
  bubblewrap \
  ca-certificates \
  curl \
  git \
  libgl1 \
  libglib2.0-0 \
  libsm6 \
  libxext6 \
  libxrender1 \
  pkg-config \
  unzip \
  wget \
  v4l-utils

if ! command -v conda >/dev/null 2>&1 && ! command -v mamba >/dev/null 2>&1; then
  echo "Installing Miniforge for ARM64..."
  if [[ ! -f "$MINIFORGE_INSTALLER" ]]; then
    curl -fsSL "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-aarch64.sh" -o "$MINIFORGE_INSTALLER"
  fi
  bash "$MINIFORGE_INSTALLER" -b -p "$HOME/miniforge3"
  # shellcheck disable=SC1091
  source "$HOME/miniforge3/etc/profile.d/conda.sh"
  # shellcheck disable=SC1091
  source "$HOME/miniforge3/etc/profile.d/mamba.sh"
  grep -qxF 'export MAMBA_ROOT_PREFIX="$HOME/miniforge3"' "$HOME/.bashrc" || echo 'export MAMBA_ROOT_PREFIX="$HOME/miniforge3"' >> "$HOME/.bashrc"
  grep -qxF 'source "$HOME/miniforge3/etc/profile.d/conda.sh"' "$HOME/.bashrc" || echo 'source "$HOME/miniforge3/etc/profile.d/conda.sh"' >> "$HOME/.bashrc"
  grep -qxF 'source "$HOME/miniforge3/etc/profile.d/mamba.sh"' "$HOME/.bashrc" || echo 'source "$HOME/miniforge3/etc/profile.d/mamba.sh"' >> "$HOME/.bashrc"
else
  if command -v conda >/dev/null 2>&1; then
    CONDA_BASE="$(conda info --base)"
  else
    CONDA_BASE="$(mamba info --base)"
  fi
  # shellcheck disable=SC1091
  source "$CONDA_BASE/etc/profile.d/conda.sh"
  if [[ -f "$CONDA_BASE/etc/profile.d/mamba.sh" ]]; then
    # shellcheck disable=SC1091
    source "$CONDA_BASE/etc/profile.d/mamba.sh"
  fi
fi

export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/miniforge3}"

if ! command -v mamba >/dev/null 2>&1; then
  conda install -n base -c conda-forge mamba -y
fi

if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "Creating conda environment: $ENV_NAME"
  mamba env create -n "$ENV_NAME" -f environment-arm.yml
else
  echo "Updating conda environment: $ENV_NAME"
  mamba env update -n "$ENV_NAME" -f environment-arm.yml --prune
fi

ENV_PREFIX="$(conda env list | awk -v env="$ENV_NAME" '$1 == env {print $NF}')"
mkdir -p "$ENV_PREFIX/etc/conda/activate.d" "$ENV_PREFIX/etc/conda/deactivate.d"
cat > "$ENV_PREFIX/etc/conda/activate.d/momo_rebot_env.sh" <<'SH'
export MOMO_OLD_PYTHONPATH="${PYTHONPATH:-}"
unset PYTHONPATH
export MOMO_OLD_LD_PRELOAD="${LD_PRELOAD:-}"
export LD_PRELOAD="$CONDA_PREFIX/lib/libgomp.so.1${LD_PRELOAD:+:$LD_PRELOAD}"
SH
cat > "$ENV_PREFIX/etc/conda/deactivate.d/momo_rebot_env.sh" <<'SH'
if [ -n "${MOMO_OLD_PYTHONPATH:-}" ]; then export PYTHONPATH="$MOMO_OLD_PYTHONPATH"; else unset PYTHONPATH; fi
if [ -n "${MOMO_OLD_LD_PRELOAD:-}" ]; then export LD_PRELOAD="$MOMO_OLD_LD_PRELOAD"; else unset LD_PRELOAD; fi
unset MOMO_OLD_PYTHONPATH MOMO_OLD_LD_PRELOAD
SH

mamba run -n "$ENV_NAME" python -m pip install -r requirements-arm.txt -c constraints-arm.txt

if [[ "$INSTALL_OPTIONAL" == "1" ]]; then
  mamba run -n "$ENV_NAME" python -m pip install -r requirements-arm-optional.txt
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example. Edit ARM_ROBOT_PORT before real hardware use."
fi

echo "Python check:"
mamba run -n "$ENV_NAME" python - <<'PY'
import sys
print(sys.executable)
print(sys.version)
for name in ["fastapi", "uvicorn", "pydantic", "yaml", "numpy", "requests", "serial", "pybullet", "cv2"]:
    __import__(name)
print("base imports ok")
PY

echo "Bootstrap complete. Next:"
echo "  mamba run -n $ENV_NAME python 系统集成/依赖检查.py"
echo "  mamba run -n $ENV_NAME python URDF运动学仿真/URDF检查_urdf_inspector.py"
echo "Note: real Feetech control still needs a separate LeRobot/Torch or lightweight SDK decision."
