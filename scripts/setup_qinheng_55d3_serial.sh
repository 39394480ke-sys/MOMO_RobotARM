#!/usr/bin/env bash
set -euo pipefail

# Install the WCH CH343 Linux driver for QinHeng 1a86:55d3 adapters and create
# a stable robot-arm serial alias: /dev/momo-servo.

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This script is intended for Linux boards." >&2
  exit 1
fi

KVER="$(uname -r)"
KERNELDIR="${KERNELDIR:-/lib/modules/$KVER/build}"
if [[ ! -d "$KERNELDIR" && -d /usr/src/header ]]; then
  KERNELDIR=/usr/src/header
fi

WORKDIR="${CH343_WORKDIR:-$HOME/ch343ser_linux}"
DRIVER_URL="${CH343_DRIVER_URL:-https://github.com/WCHSoftGroup/ch343ser_linux.git}"

sudo usermod -aG dialout "${USER}"
sudo apt-get update
sudo apt-get install -y build-essential git flex bison

if [[ ! -d "$WORKDIR/.git" ]]; then
  rm -rf "$WORKDIR"
  git clone --depth 1 "$DRIVER_URL" "$WORKDIR"
fi

if [[ ! -x "$KERNELDIR/scripts/basic/fixdep" || ! -x "$KERNELDIR/scripts/mod/modpost" ]]; then
  sudo make -C "$KERNELDIR" scripts modules_prepare || true
fi

make -C "$WORKDIR/driver" clean KERNELDIR="$KERNELDIR" || true
make -C "$WORKDIR/driver" KERNELDIR="$KERNELDIR"

sudo install -D -m 0644 "$WORKDIR/driver/ch343.ko" "/lib/modules/$KVER/extra/ch343.ko"
sudo depmod -a "$KVER" || true
echo ch343 | sudo tee /etc/modules-load.d/ch343.conf >/dev/null

sudo systemctl disable --now qinheng-55d3-serial-bind.service 2>/dev/null || true
if [[ -f /etc/udev/rules.d/99-qinheng-55d3-option-serial.rules ]]; then
  sudo mv /etc/udev/rules.d/99-qinheng-55d3-option-serial.rules /etc/udev/rules.d/99-qinheng-55d3-option-serial.rules.disabled
fi

sudo modprobe ch343 || sudo insmod "/lib/modules/$KVER/extra/ch343.ko"

sudo tee /etc/udev/rules.d/98-momo-servo-ch343.rules >/dev/null <<'RULE'
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="55d3", SYMLINK+="momo-servo", MODE="0660", GROUP="dialout"
RULE

sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=tty || true

echo "CH343 setup complete."
echo "If the adapter is already plugged in and still bound to option, unplug/replug it or run:"
echo "  sudo sh -c 'echo 4-1:1.0 > /sys/bus/usb/drivers/option/unbind'  # interface name may differ"
echo
lsusb | grep -i '1a86:55d3' || true
lsusb -t | grep -E 'usb_ch343|option' || true
ls -l /dev/momo-servo /dev/ttyCH343USB* 2>/dev/null || true
echo "Log out and back in for the dialout group change to apply."
