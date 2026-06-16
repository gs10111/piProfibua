#!/usr/bin/env bash
# Prepara um Raspberry Pi 3 para falar PROFIBUS via modulo RS485-TTL na UART de GPIO.
#
# No Pi3, a UART dos GPIO 14/15 e por padrao a mini-UART (ttyS0), cujo baud e
# instavel (atrelado ao clock do core) - ruim para o timing PROFIBUS. Este script
# libera a PL011 (estavel) nos GPIO desabilitando o Bluetooth, de modo que
# /dev/serial0 -> ttyAMA0 (PL011).
set -euo pipefail

# Localiza config.txt/cmdline.txt (Bookworm: /boot/firmware; antigos: /boot).
BOOT=/boot/firmware
[ -f "$BOOT/config.txt" ] || BOOT=/boot
CONFIG="$BOOT/config.txt"
CMDLINE="$BOOT/cmdline.txt"
echo "Usando boot dir: $BOOT"

echo "[1/5] Adicionando $USER ao grupo dialout..."
sudo usermod -aG dialout "$USER"

echo "[2/5] Habilitando a UART (enable_uart=1)..."
grep -q '^enable_uart=1' "$CONFIG" || echo 'enable_uart=1' | sudo tee -a "$CONFIG" >/dev/null

echo "[3/5] Desabilitando Bluetooth para liberar a PL011 nos GPIO 14/15..."
grep -q '^dtoverlay=disable-bt' "$CONFIG" || echo 'dtoverlay=disable-bt' | sudo tee -a "$CONFIG" >/dev/null
sudo systemctl disable hciuart 2>/dev/null || true

echo "[4/5] Removendo o console serial (evita conflito de getty na porta)..."
if [ -f "$CMDLINE" ]; then
    sudo sed -i 's/console=serial0,[0-9]\+ //g; s/console=ttyAMA0,[0-9]\+ //g' "$CMDLINE"
fi
sudo systemctl disable serial-getty@ttyAMA0.service 2>/dev/null || true
sudo systemctl disable serial-getty@serial0.service 2>/dev/null || true

echo "[5/5] OK. REINICIE o Pi (sudo reboot) para aplicar."
echo "Apos o boot: a porta sera /dev/serial0 (-> ttyAMA0). Confira com: ls -l /dev/serial0"
echo "Faca tambem logout/login uma vez para o grupo dialout valer."
