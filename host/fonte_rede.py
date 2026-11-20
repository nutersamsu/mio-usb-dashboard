"""Diagnostico da internet a partir do pve: gateway, destinos externos, DNS, latencia e perda.

Estados (campo nst), em ordem de prioridade:
  gw    gateway (OPNsense, pela LAN) sem resposta              -> critico (nlv 2)
  net   gateway ok, nenhum destino externo responde (WAN/provedor) -> critico
  dns   internet ok, mas o servidor DNS nao resolve             -> alerta (nlv 1)
  perda perda de pacotes acima do limite                        -> alerta
  lat   latencia media acima do limite                          -> alerta
  ok                                                            -> nlv 0
Falha so de DNS nunca e tratada como queda da internet.
Separar "WAN desconectada" de "provedor fora" exige a API do OPNsense (nao usada aqui).
"""
import random
import re
import socket
import struct
import subprocess
import threading
from collections import deque

RE_PACOTES = re.compile(r"(\d+) packets transmitted, (\d+) (?:packets )?received")
RE_RTT = re.compile(r"= [\d.]+/([\d.]+)/")


def ler_ping(saida, n):
    """Saida do 'ping -q' -> (enviados, recebidos, rtt_medio_ms ou None)."""
    m = RE_PACOTES.search(saida or "")
    if not m:
        return n, 0, None
    env, rec = int(m.group(1)), int(m.group(2))
    rtt = RE_RTT.search(saida)
    return env, rec, (float(rtt.group(1)) if rtt and rec else None)


def ping_estat(alvo, n=3):
    try:
        r = subprocess.run(["ping", "-n", "-q", "-c", str(n), "-i", "0.2", "-W", "1", alvo],
                           capture_output=True, text=True, timeout=n + 4)
        return ler_ping(r.stdout, n)
    except (OSError, subprocess.SubprocessError):
        return n, 0, None


def consulta_dns(servidor, nome, timeout=2.0, porta=53):
    """Consulta A direta ao servidor (UDP). True se responder NOERROR com pelo menos 1 resposta."""
    tid = random.randint(0, 0xFFFF)
    pergunta = b"".join(bytes([len(p)]) + p.encode("ascii") for p in nome.strip(".").split("."))
    pacote = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0) + pergunta + b"\0" + struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(timeout)
        s.sendto(pacote, (servidor, porta))
        dados = s.recv(1500)
    except OSError:
        return False
    finally:
        s.close()
    if len(dados) < 12:
        return False
    rid, flags, _, ancount = struct.unpack(">HHHH", dados[:8])
    return rid == tid and bool(flags & 0x8000) and (flags & 0x000F) == 0 and ancount > 0


def dns_do_sistema(resolv_conf, reserva):
    """Primeiro 'nameserver' que nao seja local (127.x / ::1); senao a reserva (gateway)."""
    for linha in (resolv_conf or "").splitlines():
        p = linha.split()
        if len(p) >= 2 and p[0] == "nameserver" and not p[1].startswith("127.") and p[1] != "::1":
            return p[1]
    return reserva


def classificar(gw_ok, net_ok, dns_ok, lat, perda, lim):
    if not gw_ok:
        return "gw", 2
    if not net_ok:
        return "net", 2
    if not dns_ok:
        return "dns", 1
    if perda is not None and perda > lim.get("perda", 5):
        return "perda", 1
    if lat is not None and lat > lim.get("latencia", 150):
        return "lat", 1
    return "ok", 0


class DiagnosticoRede:
    def __init__(self, alvos, dns_servidor, dns_nomes, janela=20, rodadas_lat=6, falhas_dns=3,
                 ping=ping_estat, dns=consulta_dns):
        self.alvos, self.dns_servidor, self.dns_nomes = list(alvos), dns_servidor, list(dns_nomes)
        self.ping, self.dns = ping, dns
        self.rodadas = deque(maxlen=janela)        # (enviados, recebidos, [rtt...]) por rodada
        self.rodadas_lat, self.falhas_dns = rodadas_lat, falhas_dns
        self._dns_falhas = 0

    def testar(self):
        """Uma rodada: pinga todos os destinos e consulta o DNS em paralelo. True se algum respondeu."""
        res = [None] * len(self.alvos)
        dns_res = [False]

        def um(i, alvo):
            res[i] = self.ping(alvo)

        def dns():
            dns_res[0] = any(self.dns(self.dns_servidor, n) for n in self.dns_nomes)

        fios = [threading.Thread(target=um, args=(i, a)) for i, a in enumerate(self.alvos)]
        if self.dns_servidor and self.dns_nomes:
            fios.append(threading.Thread(target=dns))
        for f in fios:
            f.start()
        for f in fios:
            f.join()
        env = sum(r[0] for r in res)
        rec = sum(r[1] for r in res)
        self.rodadas.append((env, rec, [r[2] for r in res if r[2] is not None]))
        self._dns_falhas = 0 if dns_res[0] else self._dns_falhas + 1
        return rec > 0

    def dns_ok(self):
        return self._dns_falhas < self.falhas_dns

    def perda(self):
        """% de perda nas rodadas em que a internet respondia (queda total nao e 'perda')."""
        vivas = [r for r in self.rodadas if r[1] > 0]
        env = sum(r[0] for r in vivas)
        if not env:
            return None
        return round(100.0 * (env - sum(r[1] for r in vivas)) / env)

    def latencia(self):
        rtts = [x for r in list(self.rodadas)[-self.rodadas_lat:] for x in r[2]]
        return round(sum(rtts) / len(rtts), 1) if rtts else None

    def campos(self, gw_ok, net_ok, limites):
        lat, perda = self.latencia(), self.perda()
        nst, nlv = classificar(gw_ok, net_ok, self.dns_ok(), lat, perda, limites)
        return {"gw": "1" if gw_ok else "0",
                "lat": "-" if lat is None else "%.0f" % lat,
                "per": "-" if perda is None else str(perda),
                "dns": "1" if self.dns_ok() else "0",
                "nst": nst, "nlv": str(nlv)}


def dns_auto(gateway):
    try:
        with open("/etc/resolv.conf") as f:
            texto = f.read()
    except OSError:
        texto = ""
    return dns_do_sistema(texto, gateway)
