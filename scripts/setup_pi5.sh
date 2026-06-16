#!/usr/bin/env bash
# Prepara o Raspberry Pi 5 para rodar o mestre PROFIBUS via USB-RS485.
set -euo pipefail

DEV="${1:-/dev/ttyUSB0}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "[1/3] Adicionando $USER ao grupo dialout..."
sudo usermod -aG dialout "$USER"

echo "[2/3] Fixando latency_timer=1 para $DEV (se presente agora)..."
BASEDEV="$(basename "$DEV")"
LAT="/sys/bus/usb-serial/devices/${BASEDEV}/latency_timer"
if [ -e "$LAT" ]; then
    echo 1 | sudo tee "$LAT" >/dev/null
    echo "    latency_timer=$(cat "$LAT")"
else
    echo "    $DEV ausente agora; a regra udev aplica ao conectar."
fi

echo "[3/3] Instalando regra udev..."
sudo cp "$HERE/99-rs485.rules" /etc/udev/rules.d/99-rs485.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=tty --subsystem-match=usb-serial

echo "OK. Refaca o login (logout/login) para o grupo dialout ter efeito."
