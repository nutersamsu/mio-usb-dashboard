# Alarme sonoro quando a internet cai — design curto

Data: 20/11/2026. Aprovado pelo usuário na conversa ("sim, silêncio das 23h às 7h, pode fazer").

**Intenção:** o Mio apita quando a internet da casa cai, para o usuário perceber sem olhar a tela.

**Abordagens:** (1) escolhida: o pve testa a internet com ping e manda o estado ao Mio, que gera o
bip na memória (sem arquivo de som); (2) usar só o item do Zabbix (velocidade zero não prova queda);
(3) WAV no cartão (mais um arquivo para copiar, sem ganho).

**Decidido:**
- Queda = ping em 1.1.1.1 **e** 8.8.8.8 falhando **3 vezes seguidas**, teste a cada 10 s (~30 s).
  Um ping bom já volta para "no ar".
- Campos novos: `net` (1/0), `som` (1 = pode tocar; 0 = som desligado ou horário de silêncio).
  Alerta "Internet caiu há N min" entra na tela de alerta.
- Silêncio das **23h às 7h** (fuso do pve, Europe/Rome): tela mostra o alerta, sem som.
- Mio: 3 bips agudos a cada 10 s enquanto `net=0` e `som=1`; **toque silencia** até a internet
  voltar (e passa a tela); na volta, bip duplo grave de "tudo certo"; volume no máximo ao tocar.
- Config no `config.json`: `"internet_teste": {"alvos": ["1.1.1.1","8.8.8.8"], "falhas": 3,
  "som": true, "silencio": "23-7"}`.
- A linha passa a ser codificada em cp1252 (página de código do Mio) para acentos aparecerem.
- `PlaySoundW`/`waveOutSetVolume` carregados em tempo de execução (exe abre mesmo sem áudio).

**Não objetivos:** alarme para outros alertas; sons configuráveis pelo usuário.
