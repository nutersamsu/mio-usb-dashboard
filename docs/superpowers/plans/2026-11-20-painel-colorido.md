# Painel colorido do Mio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mio mostra 5 telas coloridas (Internet do OPNsense via Zabbix, Servidor, Máquinas, Serviços, Alerta), 10 s cada, toque avança.

**Architecture:** `server.py` (pve) junta dados do Zabbix, do `pvesh` e de testes TCP e manda uma linha `D|...` a cada 2 s em /dev/mio. `mio_dash.c` (WinCE) só interpreta e desenha.

**Tech Stack:** Python 3.13 só biblioteca padrão (unittest), C + CeGCC 9.3 (LXC 104), API JSON-RPC do Zabbix 7.

**Spec:** `docs/superpowers/specs/2026-11-20-painel-colorido-design.md`

## Global Constraints
- Python sem dependências externas; MioDash só importa COREDLL (toolhelp/notify carregados em tempo de execução).
- Valores do protocolo nunca contêm `|`; vírgula decimal (pt-BR); linha ≤ 2048 bytes.
- Fuso de "hoje"/"mês": Europe/Rome.
- Projeto sem git: o passo "Commit" vira "copiar para o pve / cartão" quando indicado.
- Cores do mockup: bg #0a0f1e, card #141b33, line #26304f, txt #eef2ff, mut #8b95b8, down #22d3ee, up #f472b6, ok #34d399, am #fbbf24, al #f87171, alf #7f1d1d, vm #a78bfa.

## Review Focus
- Zabbix fora do ar / token inválido → tela Internet mostra "sem dados do OPNsense", resto segue (teste em Task 2).
- Virada do dia/mês e horário de verão → consumo zera no limite certo em Europe/Rome (teste em Task 2).
- Lacuna no histórico (Zabbix parado 1 h) → não inventa consumo: integra só intervalos ≤ 3× o intervalo do item (teste em Task 2).
- Nome de VM ou serviço com `;`, `|` ou acento → saneado antes de ir na linha (teste em Task 3).
- `pvesh` falha → tela Máquinas mostra "sem dados", sem derrubar o envio (teste em Task 3).

---

### Task 1: Zabbix pronto para o painel

**Files:** nenhum arquivo do projeto; registra o resultado em `README.md` (seção Zabbix).

- [ ] **Step 1:** Com o token Admin existente (no .10), criar usergroup `mio-painel` com permissão de **leitura** no hostgroup do host `opnsense`, usuário `mio-painel` (papel User role) nesse grupo, e `token.create` para ele sem expiração. Gravar o token no pve em `/root/.config/mio-painel-zabbix.token` (600). Não guardar no .10.
- [ ] **Step 2:** `item.update` dos itens 50871 e 50879: `delay` = `10s`.
- [ ] **Step 3: Verificar** do pve com o token novo: `item.get` dos 2 itens retorna `lastvalue`; `item.update` com esse token falha (sem permissão de escrita). Após ~30 s, `history.get` traz pontos com intervalo de ~10 s.

### Task 2: `host/fonte_zabbix.py`

**Files:** Create `host/fonte_zabbix.py`, `host/test_fonte_zabbix.py`

**Interfaces:**
- Produces: `class Zabbix(url: str, token: str, timeout: float = 5)` com `chamar(metodo: str, params: dict) -> list|dict` (levanta `ErroZabbix`);
  `inicio_dia_mes(agora: datetime) -> tuple[int, int]` (epoch do início do dia e do mês, Europe/Rome);
  `bytes_de_trends(trends: list[dict]) -> float` (Σ value_avg×3600/8);
  `bytes_de_historico(pontos: list[tuple[int, float]], max_gap: int) -> float` (trapézio, ignora gaps > max_gap);
  `grafico(pontos_d, pontos_u, n=20) -> tuple[list[int], list[int], float]` (valores 0–99 e máximo em Mbit/s);
  `class Internet(zbx, item_in: str, item_out: str)` com `atualizar(agora) -> dict` com chaves `wd, wu, wg, wm, hd, hu, md, mu, mes, dia, ndias, wok`.

- [ ] **Step 1: Testes** (`python3 -m unittest test_fonte_zabbix`):
  - `inicio_dia_mes(datetime(2026,11,20,0,30,tzinfo=UTC))` → dia = 2026-11-20 00:00 Rome (= 23:00 UTC de 19/11), mês = 2026-11-01 00:00 Rome.
  - `inicio_dia_mes` em 29/03/2026 (horário de verão) dá 00:00 local correto.
  - `bytes_de_trends([{"value_avg":"8000000"}])` == 3_600_000_000.
  - `bytes_de_historico([(0,8e6),(10,8e6)], 30)` == 10_000_000; com pontos `(0,8e6),(3600,8e6)` e max_gap 30 → 0.
  - `grafico` com máximo 50 Mbit/s → último valor 99 quando é o máximo; lista vazia → `([], [], 0.0)`.
  - `Internet.atualizar` com `zbx` falso que levanta `ErroZabbix` → `{"wok": "0"}`.
- [ ] **Step 2:** Rodar, ver falhar.
- [ ] **Step 3:** Implementar. `chamar` usa `urllib.request` com header `Authorization: Bearer`. `atualizar`: velocidade a cada chamada (`item.get`, `history.get` últimos 600 s, history=0); consumo recalculado no máx. a cada 300 s (cache): `trend.get` de horas fechadas desde o início do mês + `history.get` da hora corrente; hoje = mesma conta a partir do início do dia. GB com 1 casa e vírgula; acima de 1000 GB vira "1,2 TB".
- [ ] **Step 4:** Testes passam. Teste real do pve: `python3 -c` imprimindo `Internet(...).atualizar(now)` com valores plausíveis (Mbit/s, GB).

### Task 3: `host/fonte_pve.py` (máquinas e serviços)

**Files:** Create `host/fonte_pve.py`, `host/test_fonte_pve.py`

**Interfaces:**
- Produces: `limpar(s: str) -> str` (remove `|;,:` e quebras, corta 24 chars);
  `maquinas(json_texto: str) -> list[str]` → `"nome;VM 100;1;18%;9,1 GB"`, ordenado por vmid, máx. 6;
  `ler_maquinas() -> dict` (`{"vm1":..., "nvm": "3/4"}`; erro → `{"nvm": "-"}`);
  `testar_servicos(lista: list[dict], timeout=1.5) -> dict` (`sv1="Jellyfin;1;3"`, …, em paralelo com threads).
- [ ] **Step 1: Testes:** `limpar("a|b;c")=="abc"`; JSON de exemplo do `pvesh` com 1 VM running e 1 stopped → strings esperadas (stopped: `"xpenology-teste;VM 103;0;;desligada"`); JSON inválido → `ler_maquinas` não levanta; serviço em porta fechada local → `;0;`.
- [ ] **Step 2:** Rodar, ver falhar. **Step 3:** Implementar (`subprocess.run(["pvesh","get","/cluster/resources","--type","vm","--output-format","json"], timeout=5)`). **Step 4:** Passam; teste real no pve lista server/jellyfin/proxorchestrator/xpenology.

### Task 4: `server.py` + `config.json` com os campos novos

**Files:** Modify `host/server.py` (coletor e `linha_serial`), `host/config.json`

**Interfaces:**
- Consumes: Task 2 `Internet`, Task 3 `ler_maquinas`, `testar_servicos`.
- Produces: linha com os campos atuais + `wd wu wg wm hd hu md mu mes dia ndias wok`, `vm1..vm6 nvm`, `sv1..sv9`, e `alr` incluindo serviços OFF e "OPNsense sem dados" se `wok=0` por > 2 min.
- [ ] **Step 1:** config: `"zabbix": {"url": "http://192.168.1.10:8086/api_jsonrpc.php", "token_arquivo": "/root/.config/mio-painel-zabbix.token", "item_in": "50871", "item_out": "50879"}` e `"servicos"` com os 9 da spec (`tcp:IP:porta`), tirando SSH/PVE/SRV antigos.
- [ ] **Step 2: Teste** `test_linha.py`: com dados de exemplo, `linha_serial` ≤ 2048 bytes, começa com `D|`, nenhum valor tem `|`, termina com `\r\n`.
- [ ] **Step 3:** Implementar; serviços testados a cada 10 s, máquinas a cada 5 s, internet a cada 10 s.
- [ ] **Step 4:** `python3 server.py --once` no pve mostra a linha completa com números reais.

### Task 5: `device/mio_dash.c` com as 5 telas

**Files:** Modify `device/mio_dash.c`

**Interfaces:**
- Consumes: campos da Task 4. Mantém: leitor serial, fechar MutDevice, instância única, diagnóstico rx/tx/erro na tela SEM DADOS, timeout de escrita.
- [ ] **Step 1:** Limites: `MAX_CAMPOS 48`, `Campo.v[200]`, `linha[2048]`, `ROTACAO_MS 10000`, timer de 250 ms só para a linha de progresso.
- [ ] **Step 2:** Desenho igual ao mockup `docs/telas-mio.html` (mesmas coordenadas em 320x240): cabeçalho (título, hora `h`, 4 bolinhas, "×", progresso), Internet (cards, triângulos, gráfico com área em cor sólida escurecida — down #0b4a57, up #5a2a45), Servidor (barras arredondadas `RoundRect`), Máquinas (4–6 linhas), Serviços (grade 3×3), Alerta (vermelho; itens de `alr` separados por `;`). Alerta: cabeçalho vermelho e tela 5 entra na rotação.
- [ ] **Step 3:** Compilar no LXC 104 sem avisos (`make`), conferir que só importa COREDLL.
- [ ] **Step 4:** Copiar o exe para `sdcard/MioAutoRun/Apps/` e testar no aparelho com `server.py` rodando: as 5 telas, toque avança, × fecha.

### Task 6: Serviço no pve e limpeza

**Files:** Modify `host/mio-dashboard.service` (já existe), `README.md`
- [ ] **Step 1:** Copiar `host/` para `/opt/mio-usb-dashboard/host`, instalar e habilitar `mio-dashboard.service`; `journalctl -u mio-dashboard` sem erro; Mio mostra dados reais.
- [ ] **Step 2:** Reiniciar o serviço e reconectar o cabo: volta sozinho.
- [ ] **Step 3:** README atualizado (protocolo novo, Zabbix, MutDevice, cartão). Apagar o LXC 104 **só com OK do usuário**. Atualizar memória e inventário do homelab.
