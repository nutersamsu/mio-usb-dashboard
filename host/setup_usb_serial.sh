#!/bin/sh
# Prepara o Linux (Proxmox/Debian) para falar com o Mio C250 pela serial USB.
# O Mio aparece como "Mio DigiWalker USB Sync" (VID 3340 PID 043A, classe FF),
# que e a porta COM9 do lado do Mio. No Linux, o driver 'ipaq' cria /dev/ttyUSBx.
#
# Uso:  sudo ./setup_usb_serial.sh            (carrega driver e mostra a porta)
#       sudo ./setup_usb_serial.sh --udev     (tambem cria /dev/mio fixo e permanente)
set -e
VID=3340
PID=043a

[ "$(id -u)" -eq 0 ] || { echo "Rode como root (sudo)."; exit 1; }

modprobe usbserial
modprobe ipaq

# Se esta versao do driver nao conhece o PID do C250, ensina na hora:
if [ -w /sys/bus/usb-serial/drivers/ipaq/new_id ]; then
    echo "$VID $PID" > /sys/bus/usb-serial/drivers/ipaq/new_id 2>/dev/null || true
fi

if [ "$1" = "--udev" ]; then
    cat > /etc/udev/rules.d/99-mio-c250.rules <<EOF
# Mio DigiWalker C250 (serial USB) -> /dev/mio
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="$VID", ATTR{idProduct}=="$PID", RUN+="/bin/sh -c 'modprobe ipaq; echo $VID $PID > /sys/bus/usb-serial/drivers/ipaq/new_id || true'"
SUBSYSTEM=="tty", ATTRS{idVendor}=="$VID", ATTRS{idProduct}=="$PID", SYMLINK+="mio", MODE="0660", GROUP="dialout", ENV{ID_MM_DEVICE_IGNORE}="1"
EOF
    echo "ipaq" > /etc/modules-load.d/mio-ipaq.conf
    udevadm control --reload-rules
    udevadm trigger
    echo "Regra udev criada: /dev/mio (reconecte o cabo do Mio)."
fi

sleep 2
echo "--- Mio no barramento USB:"
lsusb -d $VID: || echo "Mio NAO encontrado: confira cabo e se o Mio esta ligado."
echo "--- Portas serie criadas pelo ipaq:"
dmesg | grep -i -E "ipaq|ttyUSB" | tail -n 5
ls -l /dev/ttyUSB* /dev/mio 2>/dev/null || echo "(nenhuma /dev/ttyUSB* ainda)"
echo
echo "Teste rapido (com o MioDash.exe aberto no Mio):"
echo "  echo 'D|h=teste|cpu=42|ram=50|dsk=10|tmp=40|up=1d|alr=' > /dev/mio"
