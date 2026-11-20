# Segurança

O Mio C250 fala com o servidor **só pela serial USB**. Não há rede entre os dois (a ROM não tem TCP/IP), então nada precisa ser exposto na rede para o painel funcionar.

## Controles

| Área | Controle |
|---|---|
| HTTP | Desligado na instalação de referência (`"http": false`). Se ligado, escuta em `127.0.0.1` por padrão, só aceita `GET` (outros métodos → 501) e não tem rotas administrativas. Não exponha à internet. |
| Usuário | O serviço roda como `mio-painel` (usuário de sistema, sem shell, sem home), só com o grupo `dialout` para abrir `/dev/mio`. |
| Proxmox | Token de API `mio@pve!painel` com papel **PVEAuditor** (só `*.Audit`, nenhuma escrita). TLS verificado com a CA do cluster copiada para `/etc/mio-dashboard/pve-root-ca.pem`. O usuário `mio@pve` não tem senha (não entra na interface web). |
| Zabbix | Usuário `mio-painel` só leitura, token de API. |
| Segredos | Fora do repositório e do código, em `/etc/mio-dashboard/` (pasta 700, arquivos 600, dono `mio-painel`). Os tokens não vão para logs nem mensagens de erro. |
| systemd | `NoNewPrivileges`, sem capabilities, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, `DevicePolicy=closed` + só `char-ttyUSB`, famílias de rede limitadas (`systemd-analyze security`: 3.0 OK). |
| Reinício | `Restart=on-failure` com limite de 10 tentativas em 10 min. Config inválida sai com código 78 e não é reiniciada. |

## Limitações conhecidas

- A serial não tem autenticação: quem tiver acesso físico ao cabo USB pode ler as métricas ou mandar linhas falsas para o Mio.
- O Mio só exibe dados. Ele não envia comandos ao servidor, e o host descarta tudo o que chega dele.
- O teste de internet usa ping ICMP sem privilégio (`net.ipv4.ping_group_range`). Se esse sysctl estiver fechado, o teste acusa queda falsa.
- Trocar o certificado da CA do Proxmox exige copiar de novo o `pve-root-ca.pem`.

## Revogar acesso

```bash
pveum user token remove mio@pve painel     # ou: pveum user delete mio@pve
```
No Zabbix, desative o usuário `mio-painel` ou apague o token dele.
