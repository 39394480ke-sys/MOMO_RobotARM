#!/usr/bin/env bash
set -euo pipefail

# The Edge AIoT board kernel has usbserial option/cp210x/pl2303 built in, but
# CONFIG_USB_SERIAL_CH341 is disabled. This binds QinHeng 1a86:55d3 adapters to
# the built-in option USB serial driver so /dev/ttyUSB* appears.

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This script is intended for Linux boards." >&2
  exit 1
fi

sudo usermod -aG dialout "${USER}"

sudo tee /usr/local/sbin/bind-qinheng-55d3-serial.sh >/dev/null <<'SH'
#!/usr/bin/env bash
set -euo pipefail
NEW_ID=/sys/bus/usb-serial/drivers/option1/new_id
if [[ -w "$NEW_ID" ]]; then
  echo '1a86 55d3' > "$NEW_ID" 2>/dev/null || true
fi
SH
sudo chmod +x /usr/local/sbin/bind-qinheng-55d3-serial.sh

sudo tee /etc/udev/rules.d/99-qinheng-55d3-option-serial.rules >/dev/null <<'RULE'
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="1a86", ATTR{idProduct}=="55d3", RUN+="/usr/local/sbin/bind-qinheng-55d3-serial.sh"
RULE

sudo tee /etc/systemd/system/qinheng-55d3-serial-bind.service >/dev/null <<'UNIT'
[Unit]
Description=Bind QinHeng 1a86:55d3 USB serial adapter to option driver
After=systemd-udev-settle.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/bind-qinheng-55d3-serial.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable qinheng-55d3-serial-bind.service
sudo udevadm control --reload-rules
sudo /usr/local/sbin/bind-qinheng-55d3-serial.sh

echo "QinHeng 1a86:55d3 bind installed."
echo "Log out and back in for the dialout group change to apply."
ls -l /dev/serial/by-id 2>/dev/null || true
ls -l /dev/ttyUSB* 2>/dev/null || true
