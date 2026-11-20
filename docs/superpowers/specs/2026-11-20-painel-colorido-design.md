# Painel colorido do Mio + internet do OPNsense — design

Data: 20/11/2026. Aprovado pelo usuário a partir do mockup `docs/telas-mio.html`
(https://claude.ai/artifact/WCdhYces4BX6Gv7m4TYSup).

## Intenção
O GPS Mio C250 (WinCE 5, 320x240) ligado na USB do Proxmox vira um painel bonito e colorido,
que além do servidor mostra a **internet da casa vinda do OPNsense**: velocidade agora e
consumo de **hoje** e do **mês**.

## Objetivos
- 5 telas iguais ao mockup: Internet, Servidor, Máquinas, Serviços, Alerta.
- Cada tela fica **10 s**; **tocar** passa para a próxima e reinicia os 10 s; "×" no canto
  superior direito fecha.
- Linha de progresso de 10 s embaixo do título; bolinhas indicando a tela.
- Alerta: título vermelho em todas as telas e a tela Alerta entra na rotação (não trava).
- Cores: fundo azul-escuro, download ciano, upload rosa, verde/amarelo/vermelho por estado.

## Não objetivos
- Sem consumo por aparelho da rede. Sem instalar plugin no OPNsense (vnstat).
- Sem mexer no comportamento do MutDevice / porta COM9 já resolvido.

## Restrições
- Mio: só GDI do WinCE (FillRect, RoundRect, Ellipse, Polygon, Polyline, Tahoma). Sem
  transparência: a área do gráfico usa uma cor sólida escurecida.
- Enlace: uma linha ASCII `D|k=v|...` a cada 2 s em /dev/mio (115200). Valores sem `|`.
- Host: `server.py` só com biblioteca padrão do Python, rodando no pve como serviço systemd
  (exceção à regra do Portainer: precisa da USB e de `pvesh`).
- Zabbix em http://192.168.1.10:8086, host `opnsense` (10680), itens WAN
  `net.if.in[igc0]` (50871) e `net.if.out[igc0]` (50879), em bps.

## Abordagens consideradas
1. **Zabbix (escolhida pelo usuário):** sem mexer no firewall; histórico de 31 dias e trends
   já existem. Custo: velocidade com o intervalo do item → os 2 itens WAN passam de 1 min
   para 10 s.
2. API do OPNsense com usuário só leitura: tempo real, mas exige criar usuário no firewall
   e somar o consumo por conta própria.
3. Plugin vnstat no OPNsense: totais prontos, mas instala pacote no firewall.

## Como (decidido)
- **Velocidade:** `item.get` lastvalue dos 2 itens a cada 10 s; histórico dos últimos 10 min
  (`history.get`) para o gráfico, 20 pontos, normalizados 0–99 pelo máximo da janela.
- **Consumo:** soma de bps×tempo/8. Horas fechadas via `trend.get` (value_avg × 3600),
  hora corrente via `history.get`. Recalcula a cada 5 min. Hoje e mês no fuso Europe/Rome.
- **Token do Zabbix:** usuário próprio só leitura (`mio-painel`), com token sem acesso de
  escrita; guardado no pve em /root/.config/mio-painel-zabbix.token (600).
- **Máquinas:** `pvesh get /cluster/resources --type vm` (nome, vmid, tipo, status, cpu, mem).
- **Serviços (TCP do pve):** Jellyfin .12:8096, Portainer .10:9443, NPM .10:81,
  qBittorrent .10:8081, Seerr .10:5056, Navidrome .10:4533, Zabbix .10:8086,
  DNS .1:53, CrowdSec .10:8088. Tempo de resposta em ms.
- **Protocolo:** campos novos na mesma linha (`wd`, `wu` Mbit/s; `wg` 20 pares down/up 0–99;
  `wm` máximo do gráfico; `hd`/`hu` hoje GB; `md`/`mu` mês GB; `mes`, `dia`, `ndias`;
  `vmN=nome;tipo id;on;cpu;mem`; `svN=nome;on;ms`). No Mio: valor até 200 caracteres,
  linha até 2048, até 48 campos.
- **Mio:** `mio_dash.c` redesenhado com double buffer (já existe), mesmas cores do mockup.
  Se não houver dados da internet (Zabbix fora), a tela mostra "sem dados do OPNsense".

## Deixado para quem constrói
Ajuste fino de posições/tamanhos de fonte no aparelho real; textos curtos de estado.
