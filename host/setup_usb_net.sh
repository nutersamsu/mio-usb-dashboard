#!/bin/sh
# Configura a rede USB RNDIS (usb0 / enx*) com IP estatico 192.168.55.1/24.
#
# ATENCAO: no Mio C250 Plus testado em 20/11/2026 a imagem do WinCE NAO tem o driver
# RNDIS ("O driver USB 'RNDIS' nao existe nesta imagem"). Este script so serve para
# outro aparelho/ROM que tenha RNDIS. Para o C250, use setup_usb_serial.sh.
#
# Uso:  sudo ./setup_usb_net.sh                (iproute2, temporario)
#       sudo ./setup_usb_net.sh --nat          (tambem compartilha a internet com o GPS)
#       sudo ./setup_usb_net.sh --persistente  (grava em /etc/systemd/network)
set -e
IP=192.168.55.1/24
REDE=192.168.55.0/24

[ "$(id -u)" -eq 0 ] || { echo "Rode como root (sudo)."; exit 1; }
modprobe rndis_host 2>/dev/null || true
sleep 1

IFACE=$(ls /sys/class/net | grep -E '^(usb[0-9]+|enx[0-9a-f]+)$' | head -n1)
if [ -z "$IFACE" ]; then
    echo "Nenhuma interface usb0/enx* encontrada. O aparelho esta em modo RNDIS?"
    echo "Dica: 'dmesg | tail' e 'lsusb'. Mio C250: nao tem RNDIS, use setup_usb_serial.sh."
    exit 1
fi
echo "Interface RNDIS: $IFACE"

# Evita que o NetworkManager mexa na interface
command -v nmcli >/dev/null 2>&1 && nmcli device set "$IFACE" managed no 2>/dev/null || true

ip addr flush dev "$IFACE"
ip addr add "$IP" dev "$IFACE"
ip link set "$IFACE" up
ip -br addr show "$IFACE"

for arg in "$@"; do
    case "$arg" in
    --nat)
        SAIDA=$(ip route show default | awk '/default/ {print $5; exit}')
        sysctl -w net.ipv4.ip_forward=1 >/dev/null
        iptables -t nat -C POSTROUTING -s "$REDE" -o "$SAIDA" -j MASQUERADE 2>/dev/null ||
            iptables -t nat -A POSTROUTING -s "$REDE" -o "$SAIDA" -j MASQUERADE
        iptables -C FORWARD -i "$IFACE" -o "$SAIDA" -j ACCEPT 2>/dev/null ||
            iptables -A FORWARD -i "$IFACE" -o "$SAIDA" -j ACCEPT
        iptables -C FORWARD -i "$SAIDA" -o "$IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null ||
            iptables -A FORWARD -i "$SAIDA" -o "$IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT
        echo "NAT ligado: $REDE -> $SAIDA"
        ;;
    --persistente)
        cat > /etc/systemd/network/50-mio-rndis.network <<EOF
[Match]
Name=usb* enx*
Driver=rndis_host

[Network]
Address=$IP
ConfigureWithoutCarrier=yes
EOF
        echo "Gravado /etc/systemd/network/50-mio-rndis.network (precisa de systemd-networkd ativo)."
        ;;
    esac
done
echo "Teste: ping 192.168.55.2  (IP do GPS)"
