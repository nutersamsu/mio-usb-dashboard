"""Tomada inteligente Tuya (ex.: LSC Power Plug com medidor) lida direto na rede local, so leitura.

Precisa da chave local (arquivo JSON com id, ip, versao, chave; fora do git) e da biblioteca tinytuya (MIT).
Sem uma ou outra, o campo fica em erro e o resto do painel segue.

Campo composto para o Mio: tm = te;tw;tv;ta;to;tkd;tkm;ted;tem;teh;hist
  te   1 ok | 0 sem resposta | e erro (chave/biblioteca) | - nao configurado
  tw   potencia agora (W)        tv tensao (V)        ta corrente (A)        to 1 ligada / 0 desligada
  tkd  kWh hoje   tkm kWh no mes   ted EUR hoje   tem EUR no mes   teh EUR por hora agora
  hist 12 medias de 5 min da ultima hora (W), '-' sem dado, separadas por ','
A tomada nao entrega um contador confiavel na leitura normal (DP 17 so em relatorios avulsos): o consumo e a
potencia integrada no tempo (W x dt), com dt maximo de 60 s. Dia e mes no fuso Europe/Rome; totais em arquivo.
"""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

DT_MAX = 60          # s; buraco maior nao conta energia
BALDE = 300          # s; historico em medias de 5 min
N_HIST = 12


def leitor_tinytuya(chave_arquivo, timeout=5):
    """Leitor real: devolve o dict 'dps' da tomada ou levanta excecao."""
    with open(chave_arquivo) as f:
        c = json.load(f)
    import tinytuya                     # so no venv do servico; ImportError vira erro de configuracao
    d = tinytuya.OutletDevice(c["id"], c["ip"], c["chave"], version=float(c.get("versao", 3.5)))
    d.set_socketTimeout(timeout)
    d.set_socketRetryLimit(1)

    def ler():
        r = d.status()
        if not isinstance(r, dict) or "dps" not in r:
            raise OSError("sem resposta: %s" % (r.get("Error") if isinstance(r, dict) else r))
        return r["dps"]
    return ler


class Tomada:
    def __init__(self, cfg, ler=None, fuso="Europe/Rome"):
        self.estado_arquivo = cfg.get("estado")
        self.preco = float(cfg.get("preco_kwh", 0.25))
        self.fuso = ZoneInfo(fuso)
        self.ultimo_erro = ""
        self._ler, self._config_erro = ler, None
        if ler is None:
            try:
                self._ler = leitor_tinytuya(cfg["chave_arquivo"], cfg.get("timeout", 5))
            except (OSError, ValueError, KeyError, ImportError) as e:
                self._config_erro = "%s: %s" % (type(e).__name__, e)
        self.kwh_dia = self.kwh_mes = 0.0
        self._dia = self._mes = None
        self._t = self._w = None
        self._baldes = {}
        self._carregar()

    # --- estado (sobrevive a reinicio)
    def _carregar(self):
        if not self.estado_arquivo:
            return
        try:
            with open(self.estado_arquivo) as f:
                e = json.load(f)
            self._dia, self._mes = str(e["dia"]), str(e["mes"])
            self.kwh_dia, self.kwh_mes = float(e["kd"]), float(e["km"])
        except (OSError, ValueError, KeyError, TypeError):
            self._dia = self._mes = None
            self.kwh_dia = self.kwh_mes = 0.0

    def _salvar(self):
        if not self.estado_arquivo:
            return
        try:
            tmp = self.estado_arquivo + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"dia": self._dia, "mes": self._mes, "kd": self.kwh_dia, "km": self.kwh_mes}, f)
            os.replace(tmp, self.estado_arquivo)
        except OSError as e:
            self.ultimo_erro = "estado: %s" % e.strerror

    # --- calendario
    def _local(self, t):
        return datetime.fromtimestamp(t, self.fuso)

    def _virar(self, t):
        d = self._local(t)
        dia, mes = d.strftime("%Y-%m-%d"), d.strftime("%Y-%m")
        if mes != self._mes:
            self.kwh_mes, self._mes = 0.0, mes
        if dia != self._dia:
            self.kwh_dia, self._dia = 0.0, dia

    def _somar(self, t0, t1, w):
        """Energia de w watts entre t0 e t1, dividida na meia-noite se ela cair no meio."""
        meia_noite = datetime.combine(self._local(t1).date(), datetime.min.time(), self.fuso).timestamp()
        if t0 < meia_noite < t1:
            self._virar(t0)
            antes = w * (meia_noite - t0) / 3.6e6
            self.kwh_dia += antes
            self.kwh_mes += antes
            t0 = meia_noite
        self._virar(t1)
        kwh = w * (t1 - t0) / 3.6e6
        self.kwh_dia += kwh
        self.kwh_mes += kwh
        b = self._baldes.setdefault(int(t1 // BALDE), [0.0, 0.0])
        b[0] += w * (t1 - t0)
        b[1] += t1 - t0

    def _historico(self, t):
        atual = int(t // BALDE)
        for k in [k for k in self._baldes if k <= atual - N_HIST]:
            del self._baldes[k]
        saida = []
        for k in range(atual - N_HIST + 1, atual + 1):
            b = self._baldes.get(k)
            saida.append("%.0f" % (b[0] / b[1]) if b and b[1] > 0 else "-")
        return ",".join(saida)

    # --- leitura
    def atualizar(self, t):
        self._virar(t)
        te, tw, tv, ta, to, teh = "e", "-", "-", "-", "-", "-"
        if self._config_erro:
            self.ultimo_erro = self._config_erro
            self._t = self._w = None
        else:
            try:
                dps = self._ler()
                ligada = bool(dps.get("1", True))
                w = float(dps.get("19", 0)) / 10 if ligada else 0.0
                if self._t is not None and self._w is not None and 0 < t - self._t <= DT_MAX:
                    self._somar(self._t, t, self._w)
                    self._salvar()
                elif self._dia is not None:
                    self._salvar()
                self._t, self._w = t, w
                te, to = "1", "1" if ligada else "0"
                tw, teh = "%.0f" % w, "%.3f" % (w / 1000 * self.preco)
                tv = "%.0f" % (float(dps.get("20", 0)) / 10) if "20" in dps else "-"
                ta = "%.2f" % (float(dps.get("18", 0)) / 1000) if "18" in dps else "-"
                self.ultimo_erro = ""
            except Exception as e:      # rede, tomada fora, resposta estranha: nao para o painel
                te, self.ultimo_erro = "0", "%s: %s" % (type(e).__name__, e)
                self._t = self._w = None
        partes = [te, tw, tv, ta, to, "%.3f" % self.kwh_dia, "%.2f" % self.kwh_mes,
                  "%.2f" % (self.kwh_dia * self.preco), "%.2f" % (self.kwh_mes * self.preco), teh,
                  self._historico(t)]
        return {"tm": ";".join(partes)}
