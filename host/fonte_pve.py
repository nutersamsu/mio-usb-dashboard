"""Maquinas do Proxmox (API com token so leitura, ou pvesh) e servicos testados por TCP, no formato da linha do Mio."""
import json
import socket
import ssl
import subprocess
import threading
import time
from urllib.request import Request, urlopen

MAX_MAQUINAS = 6


def limpar(s):
    """Tira os separadores do protocolo (| ; , :) e quebras; no maximo 24 caracteres."""
    for c in "|;,:\r\n":
        s = s.replace(c, "")
    return s[:24]


def _gb(b):
    return ("%.1f GB" % (b / 2 ** 30)).replace(".", ",")


def maquinas(json_texto):
    lista = sorted(json.loads(json_texto), key=lambda m: int(m.get("vmid", 0)))
    saida = []
    for m in lista[:MAX_MAQUINAS]:
        tipo = "CT" if m.get("type") == "lxc" else "VM"
        rot = "%s %s" % (tipo, m.get("vmid"))
        nome = limpar(str(m.get("name") or rot))
        if m.get("status") == "running":
            saida.append("%s;%s;1;%d%%;%s" % (nome, rot, round(float(m.get("cpu", 0)) * 100),
                                              _gb(float(m.get("mem", 0)))))
        else:
            saida.append("%s;%s;0;;desligada" % (nome, rot))
    return saida


def _pvesh():
    r = subprocess.run(["pvesh", "get", "/cluster/resources", "--type", "vm",
                        "--output-format", "json"], capture_output=True, text=True, timeout=5)
    return r.stdout


def _abrir(req, timeout, ctx=None):
    with urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read()


def leitor_api(url, token_arquivo, ca=None, timeout=5, abrir=None):
    """Funcao que le /cluster/resources pela API do PVE com um token (papel PVEAuditor).

    Dispensa root: o servico roda com usuario proprio. O token e lido a cada chamada
    (trocar o arquivo nao exige reiniciar) e nunca vai para log ou mensagem de erro."""
    if abrir is None:
        ctx = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()

        def abrir(req, timeout):
            return _abrir(req, timeout, ctx)

    def ler():
        with open(token_arquivo) as f:
            token = f.read().strip()
        req = Request(url.rstrip("/") + "/api2/json/cluster/resources?type=vm",
                      headers={"Authorization": "PVEAPIToken=" + token})
        return json.dumps(json.loads(abrir(req, timeout))["data"])
    return ler


def ler_maquinas(ler=_pvesh):
    try:
        lista = maquinas(ler())
    except (OSError, ValueError, subprocess.SubprocessError, TypeError, KeyError):
        return {"nvm": "-"}
    d = {"vm%d" % (i + 1): v for i, v in enumerate(lista)}
    d["nvm"] = "%d/%d" % (sum(1 for v in lista if v.split(";")[2] == "1"), len(lista))
    return d


def _testar(check, timeout):
    """'tcp:host:porta' -> milissegundos, ou None se fechado."""
    _, host, porta = check.split(":")
    t = time.monotonic()
    try:
        with socket.create_connection((host, int(porta)), timeout=timeout):
            return max(1, round((time.monotonic() - t) * 1000))
    except OSError:
        return None


def testar_servicos(lista, timeout=1.5):
    res = [None] * len(lista)

    def um(i, s):
        res[i] = _testar(s["check"], timeout)

    fios = [threading.Thread(target=um, args=(i, s)) for i, s in enumerate(lista)]
    for f in fios:
        f.start()
    for f in fios:
        f.join()
    d = {}
    for i, (s, ms) in enumerate(zip(lista, res)):
        d["sv%d" % (i + 1)] = "%s;%s;%s" % (limpar(s["nome"]), "0" if ms is None else "1",
                                            "" if ms is None else ms)
    d["nsv"] = "%d/%d" % (sum(1 for ms in res if ms is not None), len(lista))
    return d
