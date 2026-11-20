"""CrowdSec pela LAPI, so leitura, com chave de bouncer (bouncer so pode ler decisoes).

Campos para o Mio:
  cs   1 = LAPI no ar | 0 = LAPI fora (servico parado) | e = no ar mas a leitura falhou (chave, rede...)
  csb  IPs bloqueados (ban) por decisoes locais ativas (deteccoes daqui + cscli)
  csn  decisoes locais novas nas ultimas 24 h (ids vistos ficam salvos em arquivo)
  csl  decisoes da lista comunitaria (CAPI + listas); lida no maximo a cada 30 min (~2 MB)
O bouncer nao le alertas da LAPI; por isso 'novos em 24 h' conta decisoes, nao alertas.
"""
import json
import os
from urllib.request import Request, urlopen

DIA = 86400


def _abrir(req, timeout):
    with urlopen(req, timeout=timeout) as r:
        return r.read()


class CrowdSec:
    def __init__(self, url, chave_arquivo, estado_arquivo=None, comunidade=True,
                 periodo_lista=1800, timeout=8, abrir=_abrir):
        self.url, self.chave_arquivo = url.rstrip("/"), chave_arquivo
        self.estado_arquivo, self.comunidade = estado_arquivo, comunidade
        self.periodo_lista, self.timeout, self.abrir = periodo_lista, timeout, abrir
        self._lista, self._lista_em = "-", None
        self.ultimo_erro = ""
        self._vistos = self._carregar()

    # --- estado dos ids vistos (sobrevive a reinicio)
    def _carregar(self):
        if not self.estado_arquivo:
            return {}
        try:
            with open(self.estado_arquivo) as f:
                return {str(k): float(v) for k, v in json.load(f).items()}
        except (OSError, ValueError, AttributeError, TypeError):
            return {}

    def _salvar(self):
        if not self.estado_arquivo:
            return
        try:
            tmp = self.estado_arquivo + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._vistos, f)
            os.replace(tmp, self.estado_arquivo)
        except OSError as e:
            self.ultimo_erro = "estado: %s" % e.strerror

    # --- LAPI
    def _get(self, caminho, chave=None):
        cab = {"X-Api-Key": chave} if chave else {}
        dados = self.abrir(Request(self.url + caminho, headers=cab, method="GET"), self.timeout)
        return json.loads(dados or b"null")

    def _decisoes(self, chave, origens):
        return self._get("/v1/decisions?origins=" + origens, chave) or []

    def atualizar(self, agora):
        """agora = epoch (time.time())."""
        try:
            saude = self._get("/health")
            if not isinstance(saude, dict) or saude.get("status") != "up":
                raise OSError("health")
        except Exception as e:                       # noqa: BLE001 - qualquer falha = LAPI fora
            self.ultimo_erro = "lapi fora: %s" % type(e).__name__
            return {"cs": "0"}
        try:
            with open(self.chave_arquivo) as f:
                chave = f.read().strip()
            locais = self._decisoes(chave, "crowdsec,cscli")
            if self.comunidade and (self._lista_em is None or agora - self._lista_em >= self.periodo_lista):
                self._lista = str(len(self._decisoes(chave, "CAPI,lists")))
                self._lista_em = agora
        except Exception as e:                       # noqa: BLE001
            # so o tipo e o codigo: a chave nunca vai para log
            self.ultimo_erro = "leitura: %s %s" % (type(e).__name__, getattr(e, "code", ""))
            return {"cs": "e"}
        bans = {d.get("value") for d in locais if d.get("type") == "ban"}
        mudou = False
        for d in locais:
            i = str(d.get("id"))
            if i not in self._vistos:
                self._vistos[i] = agora
                mudou = True
        velhos = [i for i, t in self._vistos.items() if agora - t > DIA]
        for i in velhos:
            del self._vistos[i]
        if mudou or velhos:
            self._salvar()
        self.ultimo_erro = ""
        return {"cs": "1", "csb": str(len(bans)), "csn": str(len(self._vistos)),
                "csl": self._lista if self.comunidade else "-"}
