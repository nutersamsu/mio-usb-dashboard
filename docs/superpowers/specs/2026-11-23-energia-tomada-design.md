# Tela ENERGIA: consumo da tomada em euros — desenho curto (23/11/2026)

## Por quê
O usuário quer ver no Mio quanto a tomada inteligente gasta, em euros, com o preço da conta da Enel dele.

## Escolha (do usuário): opção A — leitura direta na rede local
O host do Mio (pve) lê a tomada pela rede local com a chave local Tuya. Sem nuvem e sem Home Assistant; segue
funcionando sem internet. Descartadas: via Home Assistant (depende da VM do teste ficar para sempre), nuvem Tuya
(internet + limite de consultas), firmware novo (no protocolo 3.5 exige abrir e soldar).

## Aparelho
LSC Power Plug EU com medidor (Tuya, protocolo 3.5, product id `keykmm3rjyqy5r8p`), na rede da casa por DHCP.
IP, device id e chave local ficam só no `config.json`/`/etc/mio-dashboard` do pve — **nunca no git (repo público)**.

## Como fica
- `host/fonte_tomada.py`: classe `Tomada(ip, device_id, chave_arquivo, versao="3.5", estado_arquivo, preco)`,
  leitura a cada ciclo (10 s) via `tinytuya` (MIT) instalado num venv do serviço (decisão minha: o protocolo 3.5
  usa AES-GCM; reimplementar seria arriscado). Sem `tinytuya` ou sem chave → campo de erro, o resto do painel segue.
- Campos para o Mio (curtos, como os outros): `tw` W agora, `tv` V, `ta` A, `to` 1/0 ligada, `te` estado
  (1 ok / 0 sem resposta / e erro), `tkd` kWh hoje, `tkm` kWh mês, `ted` € hoje, `tem` € mês, `teh` € por hora agora.
  A linha passa de 51 para ~61 campos (limite 64): se apertar, agrupar como `cn`/`cs`.
- Contagem do dia/mês: integrar a potência no tempo (W × Δt, com Δt máximo de 60 s para buracos), guardada em
  `/var/lib/mio-dashboard/tomada.json`; zera à meia-noite e no dia 1 (fuso Europe/Rome).
  DPs reais lidos em 23/11 (leitura local ok com a chave): 1 switch_1 (bool), 18 cur_current (mA), 19 cur_power
  (W, escala 1 → ÷10), 20 cur_voltage (V, escala 1 → ÷10), 26 fault (bitmap), 17 add_ele (kWh, escala 3) NÃO vem
  na leitura normal (só em relatórios avulsos) → decidido: integrar a potência, não usar o add_ele.
  Chave/IP/id em `/root/.config/tuya-tomada.json` no servidor .10 (600); no pve vai para `/etc/mio-dashboard`.
- Preço: `config.json` → `"tomada": {"preco_kwh": 0.25, ...}` (fatura Enel ago–set/2026: custo variável com IVA).
- Tela ENERGIA no MioDash (tema Neon, 320×240), logo após as telas atuais:
  ```
  ENERGIA                     LIGADA
        238 W        0,06 €/h
  ▁▂▂▃▅▇▆▃▂▂  (última hora, no host)
  Hoje 1,42 kWh · 0,35 €
  Mês  19,2 kWh · 4,80 €     230 V 1,03 A
  ```
  Sem dados: "TOMADA SEM RESPOSTA". O histórico da última hora vai num campo compacto (ex.: 12 valores).
- Alerta opcional (config, desligado por padrão): âmbar se a tomada sumir mais de 5 min; âmbar acima de N W.
- Recompilar o MioDash no LXC 104 e desligar depois; usuário copia o exe para o cartão.

## Fora do escopo
Ligar/desligar a tomada pelo Mio (o painel é só leitura); outras tomadas.

## Depende do usuário
Chave local (conta grátis iot.tuya.com ligada ao app); acesso ao pve para instalar (hoje sem SSH/token).
