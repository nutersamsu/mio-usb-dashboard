"""Internet da casa (WAN do OPNsense) lida do Zabbix: velocidade, grafico e consumo.

So biblioteca padrao. Usa um token do Zabbix SO DE LEITURA (usuario mio-painel).
"""
import calendar
import http.client
import json
import time
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("Europe/Rome")
MESES = ["JANEIRO", "FEVEREIRO", "MARCO", "ABRIL", "MAIO", "JUNHO", "JULHO",
         "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]


VELOCIDADE_VELHA = 60       # s sem amostra nova -> "sem dados do OPNsense"
CONSUMO_VAZIO = {"hd": "-", "hu": "-", "ht": "-", "md": "-", "mu": "-", "mt": "-",
                 "mes": "-", "dia": "0", "ndias": "0"}


class ErroZabbix(Exception):
    pass


class Zabbix:
    def __init__(self, url, token, timeout=5):
        self.url, self.token, self.timeout = url, token, timeout

    def chamar(self, metodo, params):
        corpo = json.dumps({"jsonrpc": "2.0", "method": metodo, "params": params, "id": 1}).encode()
        req = urllib.request.Request(self.url, data=corpo, headers={
            "Content-Type": "application/json-rpc", "Authorization": "Bearer " + self.token})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                resp = json.load(r)
        except (OSError, ValueError, http.client.HTTPException) as e:
            raise ErroZabbix(str(e)) from e
        if "error" in resp:
            raise ErroZabbix(str(resp["error"].get("data") or resp["error"]))
        return resp["result"]


def inicio_dia_mes(agora):
    """Epoch do inicio do dia e do mes em Europe/Rome."""
    local = agora.astimezone(FUSO)
    dia = local.replace(hour=0, minute=0, second=0, microsecond=0)
    mes = dia.replace(day=1)
    # replace() mantem o offset do instante original; recalcula para o horario de verao
    dia = datetime(dia.year, dia.month, dia.day, tzinfo=FUSO)
    mes = datetime(mes.year, mes.month, 1, tzinfo=FUSO)
    return int(dia.timestamp()), int(mes.timestamp())


def bytes_de_trends(trends, intervalo=60):
    """Trend = media (bps) da hora. So conta o tempo realmente coberto pelas
    amostras (num x intervalo), para uma hora com lacuna nao virar hora cheia."""
    total = 0.0
    for t in trends:
        coberto = min(int(t.get("num", 3600 // intervalo)) * intervalo, 3600)
        total += float(t["value_avg"]) * coberto / 8
    return total


def bytes_de_historico(pontos, max_gap):
    """Integra bps no tempo (trapezio). Intervalos maiores que max_gap nao contam."""
    total = 0.0
    for (t0, v0), (t1, v1) in zip(pontos, pontos[1:]):
        dt = t1 - t0
        if 0 < dt <= max_gap:
            total += (v0 + v1) / 2 * dt / 8
    return total


def formatar_gb(b):
    gb = b / 1e9
    if gb >= 1000:
        return ("%.1f TB" % (gb / 1000)).replace(".", ",")
    return ("%.1f GB" % gb).replace(".", ",")


def formatar_mbit(bps):
    m = bps / 1e6
    return ("%.0f" % m) if m >= 100 else ("%.1f" % m).replace(".", ",")


def _reduzir(valores, n):
    if len(valores) <= n:
        return valores
    passo = len(valores) / n
    return [sum(valores[int(i * passo):int((i + 1) * passo)]) /
            max(1, int((i + 1) * passo) - int(i * passo)) for i in range(n)]


def grafico(pontos_d, pontos_u, n=20):
    """Ultimos pontos (bps) -> listas 0..99 e o maximo da janela em Mbit/s."""
    if not pontos_d and not pontos_u:
        return [], [], 0.0
    d = _reduzir([v / 1e6 for _, v in pontos_d], n)
    u = _reduzir([v / 1e6 for _, v in pontos_u], n)
    mx = max(d + u) or 1.0
    return ([int(v / mx * 99) for v in d], [int(v / mx * 99) for v in u], round(mx, 1))


class Internet:
    def __init__(self, zbx, vivo_in, vivo_out, total_in, total_out,
                 intervalo_total=60, cache_consumo=300):
        self.zbx = zbx
        self.vivo = (vivo_in, vivo_out)
        self.total = (total_in, total_out)
        self.intervalo_total = intervalo_total
        self.max_gap = intervalo_total * 3
        self.cache_consumo = cache_consumo
        self._consumo = None
        self._consumo_em = 0.0

    def _historico(self, item, desde, ate):
        r = self.zbx.chamar("history.get", {"itemids": [item], "history": 3, "time_from": desde,
                                            "time_till": ate, "sortfield": "clock",
                                            "sortorder": "ASC", "output": ["clock", "value"]})
        return [(int(p["clock"]), float(p["value"])) for p in r]

    def _bytes(self, item, desde, agora_ts):
        hora = agora_ts - agora_ts % 3600
        tr = self.zbx.chamar("trend.get", {"itemids": [item], "time_from": desde,
                                          "time_till": hora - 1, "output": ["clock", "value_avg", "num"]})
        tr = [t for t in tr if int(t["clock"]) >= desde]
        return bytes_de_trends(tr, self.intervalo_total) + bytes_de_historico(
            self._historico(item, max(hora, desde), agora_ts), self.max_gap)

    def _calcular_consumo(self, agora):
        ts = int(agora.timestamp())
        dia, mes = inicio_dia_mes(agora)
        bi, bo = (self._bytes(i, mes, ts) for i in self.total)
        hi, ho = (self._bytes(i, dia, ts) for i in self.total)
        local = agora.astimezone(FUSO)
        return {"hd": formatar_gb(hi), "hu": formatar_gb(ho), "ht": formatar_gb(hi + ho),
                "md": formatar_gb(bi), "mu": formatar_gb(bo), "mt": formatar_gb(bi + bo),
                "mes": MESES[local.month - 1], "dia": str(local.day),
                "ndias": str(calendar.monthrange(local.year, local.month)[1])}

    def _consumo_atual(self, agora):
        """Consumo com cache; uma falha aqui nao derruba a velocidade."""
        if self._consumo is None or time.monotonic() - self._consumo_em > self.cache_consumo:
            try:
                self._consumo = self._calcular_consumo(agora)
                self._consumo_em = time.monotonic()
            except (ErroZabbix, KeyError, ValueError, TypeError):
                # tenta de novo em 60 s; mantem o ultimo valor bom, se houver
                self._consumo_em = time.monotonic() - self.cache_consumo + 60
                if self._consumo is None:
                    return dict(CONSUMO_VAZIO)
        return self._consumo

    def atualizar(self, agora):
        try:
            ts = int(agora.timestamp())
            itens = self.zbx.chamar("item.get", {"itemids": list(self.vivo),
                                                 "output": ["itemid", "lastvalue", "lastclock"]})
            if not itens or any(ts - int(i["lastclock"]) > VELOCIDADE_VELHA for i in itens):
                return {"wok": "0"}                      # OPNsense parou de mandar dados
            ultimo = {i["itemid"]: float(i["lastvalue"]) for i in itens}
            gd, gu, mx = grafico(self._historico(self.vivo[0], ts - 600, ts),
                                 self._historico(self.vivo[1], ts - 600, ts))
            d = {"wok": "1", "wd": formatar_mbit(ultimo.get(self.vivo[0], 0)),
                 "wu": formatar_mbit(ultimo.get(self.vivo[1], 0)),
                 "wg": ",".join("%d/%d" % p for p in zip(gd, gu)),
                 "wm": ("%.0f" % mx) if mx >= 10 else ("%.1f" % mx).replace(".", ",")}
            d.update(self._consumo_atual(agora))
            return d
        except (ErroZabbix, KeyError, ValueError, TypeError):
            return {"wok": "0"}
