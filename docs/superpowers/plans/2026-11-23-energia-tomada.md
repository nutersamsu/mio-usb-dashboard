# Tela ENERGIA — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ler a tomada LSC (Tuya 3.5) na rede local e mostrar no Mio a potência e o consumo do dia/mês em euros.

**Architecture:** `host/fonte_tomada.py` (leitor injetável, integra W×Δt, estado em arquivo) → tarefa de 10 s no
`Coletor.extras` → campo composto `tm` na linha → `tela_energia` no MioDash.

**Tech Stack:** Python 3 stdlib + `tinytuya` (só no venv do serviço), unittest; C (CeGCC) no LXC 104.

**Spec:** `docs/superpowers/specs/2026-11-23-energia-tomada-design.md`

## Global Constraints
- Repo PÚBLICO: nada de IP real, device id ou chave no git (config de exemplo com valores fictícios).
- Sem tinytuya instalado, o servidor sobe e o resto do painel segue (`tm` com estado `e`).
- Campo composto `tm` = `te;tw;tv;ta;to;tkd;tkm;ted;tem;teh;hist` (`hist` = 12 médias de 5 min separadas por `,`).
  `te`: `1` ok, `0` sem resposta, `e` erro de configuração/biblioteca, `-` não configurado.
- Preço vem de `config.json` → `tomada.preco_kwh` (padrão 0.25). Dia/mês no fuso Europe/Rome.
- Δt máximo de 60 s na integração (buraco maior não conta energia).
- ASCII na linha (cp1252), números com ponto.

## Review Focus
- Tomada desligada da tomada/rede por horas → sem energia inventada no buraco; `te=0`.
- Virada da meia-noite e do mês entre duas leituras → zera certo, sem perder a parte antes da virada.
- Arquivo de estado corrompido ou de outro dia → recomeça sem quebrar.
- Reinício do serviço no meio do dia → continua o total do dia.
- Potência com relé desligado (`to=0`) → 0 W, sem contar.

---

### Task 1: `fonte_tomada.py`
**Files:** Create `host/fonte_tomada.py`, `host/test_fonte_tomada.py`
**Interfaces — Produces:** `class Tomada(cfg: dict, ler=None, agora=time.time)` com `atualizar(t: float) -> dict`
devolvendo `{"tm": "<composto>"}`; `ler()` devolve o dict `dps` (`{"1": bool, "18": mA, "19": W*10, "20": V*10}`) ou
levanta exceção. `cfg`: `chave_arquivo` (JSON com id, ip, versao, chave), `estado`, `preco_kwh`.
- [ ] Testes: valores convertidos (W÷10, V÷10, A=mA/1000); integração de 2 leituras (1000 W por 36 s = 0,01 kWh);
  buraco > 60 s não soma; virada de dia/mês zera e soma a parte certa; estado salvo e recarregado; estado ruim
  ignorado; leitor com exceção → `te=0` e totais mantidos; sem chave/tinytuya → `te=e`; hist com 12 posições.
- [ ] Implementar; `python3 -m unittest test_fonte_tomada` passa. Commit.

### Task 2: integrar no servidor
**Files:** Modify `host/server.py` (Coletor, extras 10 s, COMPOSTOS `tm`, LEITURA_BOA, `velhas` → código `tomada`,
alertas opcionais), `host/config.json` (bloco `tomada` desligado com valores fictícios), Test `host/test_tomada_servidor.py`.
- [ ] Testes: sem bloco `tomada` → nada muda na linha; com fonte falsa → `tm=` na linha com 11 partes; linha ≤ 64
  campos e ≤ 2048 bytes; alerta âmbar "Tomada sem resposta" só se `alerta_sem_resposta` ligado e > 5 min.
- [ ] Toda a suíte (`python3 -m unittest`) passa. Commit.

### Task 3: tela no Mio
**Files:** Modify `device/mio_dash.c` (`tela_energia`, `N_TELAS` 8, ANIME vira 8), docs/telas (prévia).
- [ ] Escrever a tela; compilar no LXC 104 (pve, precisa de acesso) e desligar; copiar exe para `sdcard` e
  `mio-cartao`. Usuário testa no aparelho.

### Task 4: instalar no pve e documentar
- [ ] venv com tinytuya em `/opt/mio-usb-dashboard/venv`, unit com o python do venv, chave em
  `/etc/mio-dashboard/tomada.json` (600, dono mio-painel), config no pve, reiniciar e conferir a linha.
- [ ] README/SECURITY (sem dados reais); commit; push só com o OK do usuário.
