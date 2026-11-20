#!/bin/sh
# Simula queda da internet para o painel do Mio e volta depois de N s (padrao 90).
# Uso no pve (unidade solta, sobrevive ao restart do servico):
#   systemd-run --unit mio-simula --collect /opt/mio-usb-dashboard/host/simular_queda.sh 45
C=/opt/mio-usb-dashboard/host/config.json
cp $C /root/mio-config-antes-teste.json
python3 -c "import json; c=json.load(open(\"$C\")); c[\"internet_teste\"][\"alvos\"]=[\"192.0.2.1\"]; json.dump(c,open(\"$C\",\"w\"),indent=2,ensure_ascii=False)"
systemctl restart mio-dashboard; echo "$(date +%T) queda simulada"
sleep ${1:-90}
cp /root/mio-config-antes-teste.json $C && rm /root/mio-config-antes-teste.json
systemctl restart mio-dashboard; echo "$(date +%T) internet de volta"
