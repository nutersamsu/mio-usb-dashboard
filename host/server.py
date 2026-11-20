#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mio USB Dashboard - coletor de metricas + servidor HTTP (porta 8080) + envio serial.

So biblioteca padrao. Usa psutil se estiver instalado (opcional), senao /proc e /sys.

Modos de entrega ao GPS Mio C250:
  1) HTTP (RNDIS/rede): paginas HTML 4.01 de 320x240 em http://<ip>:8080/?view=sys|net|alert
  2) Serial USB (/dev/ttyUSB0 via driver 'ipaq'): uma linha de texto a cada intervalo,
     lida pelo cliente nativo device/mio_dash.c no Mio.  <- caminho real do C250 (sem RNDIS)

Uso:
  python3 server.py                       # usa config.json ao lado
  python3 server.py --config /etc/mio-dashboard.json
  python3 server.py --once                # imprime uma coleta e sai (teste)
"""
import argparse
import html
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fonte_internet import TesteInternet, em_silencio  # noqa: E402
from fonte_pve import ler_maquinas, testar_servicos  # noqa: E402
from fonte_zabbix import Internet, Zabbix  # noqa: E402
from urllib.parse import urlparse, parse_qs

try:
    import psutil  # opcional
except Exception:  # pragma: no cover
    psutil = None

AQUI = os.path.dirname(os.path.abspath(__file__))

CONFIG_PADRAO = {
    "listen": "0.0.0.0",
    "port": 8080,
    "intervalo": 2,                 # segundos entre coletas
    "rotacao": 5,                   # segundos por vista no navegador
    "interface": "auto",            # "auto" = interface da rota padrao (ex.: vmbr0 no Proxmox)
    "ping_alvo": "auto",            # "auto" = gateway padrao; ou "1.1.1.1"
    "disco": "/",
    "servicos": [                   # systemd:<unidade> ou tcp:<host>:<porta>
        {"nome": "SSH", "check": "tcp:127.0.0.1:22"},
        {"nome": "PVE", "check": "systemd:pveproxy"},
        {"nome": "PG", "check": "tcp:127.0.0.1:5432"}
    ],
    "proxmox": True,                # conta VMs/CTs rodando (qm/pct), se existirem
    "limites": {"cpu": 85, "ram": 90, "disco": 90, "temp": 85, "ping_falhas": 3},
    "serial": {
        "ativo": False,
        "porta": "/dev/ttyUSB0",    # ou /dev/mio (regra udev do setup_usb_serial.sh)
        "baud": 115200
    }
}


# ----------------------------------------------------------------- utilidades
def ler(caminho, padrao=""):
    try:
        with open(caminho) as f:
            return f.read()
    except Exception:
        return padrao


def carregar_config(caminho):
    cfg = json.loads(json.dumps(CONFIG_PADRAO))
    if caminho and os.path.exists(caminho):
        with open(caminho) as f:
            usuario = json.load(f)
        for k, v in usuario.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def rota_padrao():
    """(interface, gateway) da rota padrao, lendo /proc/net/route."""
    for linha in ler("/proc/net/route").splitlines()[1:]:
        p = linha.split()
        if len(p) >= 3 and p[1] == "00000000":
            gw = socket.inet_ntoa(bytes.fromhex(p[2])[::-1])
            return p[0], gw
    return None, None


def fmt_uptime(seg):
    seg = int(seg)
    d, seg = divmod(seg, 86400)
    h, seg = divmod(seg, 3600)
    m = seg // 60
    return "%dd %02dh%02dm" % (d, h, m) if d else "%02dh%02dm" % (h, m)


# ----------------------------------------------------------------- coletor
class Coletor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.dados = {}
        self.trava = threading.Lock()
        self._cpu_ant = None
        self._net_ant = None
        self._ping_falhas = 0
        self._internet_falha_desde = 0.0
        self._extra, self._extra_em = {}, {}
        self.internet = None
        it = cfg.get("internet_teste", {})
        self.teste_net = TesteInternet(it.get("alvos", ["1.1.1.1", "8.8.8.8"]), int(it.get("falhas", 3)))
        z = cfg.get("zabbix")
        if z:
            token = ler(z["token_arquivo"]).strip()
            if token:
                self.internet = Internet(Zabbix(z["url"], token), z["item_in"], z["item_out"],
                                         z["total_in"], z["total_out"])

    # --- sistema
    def cpu(self):
        if psutil:
            return psutil.cpu_percent(interval=None)
        p = ler("/proc/stat").splitlines()[0].split()[1:]
        v = [int(x) for x in p]
        ocioso, total = v[3] + (v[4] if len(v) > 4 else 0), sum(v)
        ant, self._cpu_ant = self._cpu_ant, (ocioso, total)
        if not ant or total == ant[1]:
            return 0.0
        return round(100.0 * (1 - (ocioso - ant[0]) / float(total - ant[1])), 1)

    def memoria(self):
        info = {}
        for l in ler("/proc/meminfo").splitlines():
            k, _, v = l.partition(":")
            info[k] = int(v.split()[0]) if v.split() else 0
        total = info.get("MemTotal", 0) / 1024.0
        livre = info.get("MemAvailable", info.get("MemFree", 0)) / 1024.0
        usada = total - livre
        return round(usada), round(total), round(100.0 * usada / total, 1) if total else 0

    def disco(self):
        st = os.statvfs(self.cfg["disco"])
        total = st.f_blocks * st.f_frsize
        livre = st.f_bavail * st.f_frsize
        usado = total - st.f_bfree * st.f_frsize
        pct = round(100.0 * usado / (usado + livre), 1) if (usado + livre) else 0
        return round(livre / 1e9, 1), round(total / 1e9, 1), pct

    def temperatura(self):
        if psutil and hasattr(psutil, "sensors_temperatures"):
            try:
                t = psutil.sensors_temperatures()
                for chave in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz"):
                    if t.get(chave):
                        return round(max(x.current for x in t[chave]), 1)
            except Exception:
                pass
        # /sys/class/hwmon (coretemp/k10temp) e depois thermal_zone
        melhor = None
        base = "/sys/class/hwmon"
        if os.path.isdir(base):
            for h in sorted(os.listdir(base)):
                nome = ler(os.path.join(base, h, "name")).strip()
                if nome in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz"):
                    for f in os.listdir(os.path.join(base, h)):
                        if f.startswith("temp") and f.endswith("_input"):
                            v = ler(os.path.join(base, h, f)).strip()
                            if v.isdigit():
                                melhor = max(melhor or 0, int(v) / 1000.0)
                    if melhor:
                        return round(melhor, 1)
        base = "/sys/class/thermal"
        if os.path.isdir(base):
            for z in sorted(os.listdir(base)):
                v = ler(os.path.join(base, z, "temp")).strip()
                if v.lstrip("-").isdigit():
                    melhor = max(melhor or 0, int(v) / 1000.0)
        return round(melhor, 1) if melhor else None

    def uptime(self):
        return float(ler("/proc/uptime", "0").split()[0])

    # --- rede
    def trafego(self, iface):
        linhas = ler("/proc/net/dev").splitlines()[2:]
        rx = tx = None
        for l in linhas:
            nome, _, resto = l.partition(":")
            if nome.strip() == iface:
                c = resto.split()
                rx, tx = int(c[0]), int(c[8])
        if rx is None:
            return None, None
        agora = time.time()
        ant, self._net_ant = self._net_ant, (agora, rx, tx)
        if not ant or agora <= ant[0]:
            return 0.0, 0.0
        dt = agora - ant[0]
        return round((rx - ant[1]) / dt / 1024.0, 1), round((tx - ant[2]) / dt / 1024.0, 1)

    def ping(self, alvo):
        try:
            r = subprocess.run(["ping", "-c", "1", "-W", "1", alvo],
                               capture_output=True, text=True, timeout=3)
            m = re.search(r"time[=<]([\d.]+)", r.stdout)
            if r.returncode == 0 and m:
                self._ping_falhas = 0
                return round(float(m.group(1)), 1)
        except Exception:
            pass
        self._ping_falhas += 1
        return None

    def servico(self, check):
        tipo, _, alvo = check.partition(":")
        try:
            if tipo == "systemd":
                r = subprocess.run(["systemctl", "is-active", "--quiet", alvo], timeout=3)
                return r.returncode == 0
            if tipo == "tcp":
                host, _, porta = alvo.rpartition(":")
                with socket.create_connection((host or "127.0.0.1", int(porta)), timeout=0.7):
                    return True
        except Exception:
            return False
        return False

    def proxmox(self):
        """(vms_rodando, vms_total, cts_rodando, cts_total) ou None se nao for Proxmox."""
        res = []
        for cmd in (["qm", "list"], ["pct", "list"]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
                linhas = [l for l in r.stdout.splitlines()[1:] if l.strip()]
                rodando = sum(1 for l in linhas if " running " in " %s " % l)
                res += [rodando, len(linhas)]
            except Exception:
                return None
        return tuple(res)

    # --- ciclo
    def coletar(self):
        cfg = self.cfg
        iface, gw = rota_padrao()
        if cfg["interface"] != "auto":
            iface = cfg["interface"]
        alvo = gw if cfg["ping_alvo"] == "auto" else cfg["ping_alvo"]
        ram_u, ram_t, ram_p = self.memoria()
        d_livre, d_total, d_pct = self.disco()
        rx, tx = self.trafego(iface) if iface else (None, None)
        lat = self.ping(alvo) if alvo else None
        extra = dict(self.extras(time.monotonic()), rot=tempo_tela(cfg))
        servs = [(s["nome"], extra.get("sv%d" % (i + 1), ";0").split(";")[1] == "1")
                 for i, s in enumerate(cfg["servicos"])]
        pve = self.proxmox() if cfg.get("proxmox") else None
        d = {
            "host": socket.gethostname(),
            "hora": time.strftime("%H:%M:%S"),
            "cpu": self.cpu(), "ram_u": ram_u, "ram_t": ram_t, "ram": ram_p,
            "disco_livre": d_livre, "disco_total": d_total, "disco": d_pct,
            "temp": self.temperatura(), "uptime": fmt_uptime(self.uptime()),
            "iface": iface or "-", "rx": rx, "tx": tx,
            "ping_alvo": alvo or "-", "ping": lat,
            "servicos": servs, "pve": pve, "extra": extra, "_em": time.monotonic(),
        }
        d["alertas"] = self.alertas(d)
        with self.trava:
            self.dados = d
        return d

    def extras(self, agora):
        """Internet (Zabbix), maquinas (pvesh) e servicos TCP, cada um no seu ritmo."""
        tarefas = [("internet", 10, lambda: self.internet.atualizar(
                        datetime.now(timezone.utc)) if self.internet else {"wok": "0"},
                    {"wok": "0"}),
                   ("maquinas", 5, lambda: ler_maquinas(), {"nvm": "-"}),
                   ("servicos", 10, lambda: testar_servicos(self.cfg["servicos"]), {"nsv": "-"}),
                   ("net", 10, lambda: self._testar_net(agora), {"net": "1", "som": "0"})]
        for nome, periodo, f, se_falhar in tarefas:
            if agora - self._extra_em.get(nome, -1e9) >= periodo:
                try:
                    self._extra[nome] = f()
                except Exception as e:           # uma fonte quebrada nao para as outras
                    sys.stderr.write("%s: %r\n" % (nome, e))
                    self._extra[nome] = dict(se_falhar)
                self._extra_em[nome] = agora
        junto = {}
        for v in self._extra.values():
            junto.update(v)
        return junto

    def _testar_net(self, agora):
        self.teste_net.testar(agora)
        d = self.teste_net.estado(agora)
        d["netmin"] = str(self.teste_net.minutos_fora(agora))
        d["som"] = som_ativo(self.cfg, time.localtime().tm_hour)
        return d

    def alertas(self, d, agora=None):
        agora = time.monotonic() if agora is None else agora
        L, a = self.cfg["limites"], []
        ex = d.get("extra", {})
        if ex.get("net") == "0":
            a.append("Internet caiu há %s min" % ex.get("netmin", "0"))
        if ex.get("wok", "1") == "0":
            if not self._internet_falha_desde:
                self._internet_falha_desde = agora
            if agora - self._internet_falha_desde > 120:
                a.append("OPNsense sem dados")
        else:
            self._internet_falha_desde = 0.0
        if d["cpu"] is not None and d["cpu"] > L["cpu"]:
            a.append("CPU %.0f%%" % d["cpu"])
        if d["ram"] > L["ram"]:
            a.append("RAM %.0f%%" % d["ram"])
        if d["disco"] > L["disco"]:
            a.append("DISCO %.0f%%" % d["disco"])
        if d["temp"] is not None and d["temp"] > L["temp"]:
            a.append("TEMP %.0fC" % d["temp"])
        if self._ping_falhas >= L["ping_falhas"]:
            a.append("SEM PING " + d["ping_alvo"])
        for nome, ok in d["servicos"]:
            if not ok:
                a.append(nome + " fora do ar")
        return a

    def loop(self):
        self.cpu()  # inicializa delta
        while True:
            try:
                self.coletar()
            except Exception as e:  # nunca derruba o servico
                sys.stderr.write("coleta: %r\n" % e)
            time.sleep(self.cfg["intervalo"])

    def atual(self):
        with self.trava:
            return dict(self.dados)


# ----------------------------------------------------------------- serial
DADOS_MAX_IDADE = 15        # s; coleta parada -> para de enviar e o Mio mostra SEM DADOS
# campos que o Mio nao le: ficam fora da linha (o Mio guarda no maximo 48 campos)
NAO_ENVIAR = {"md", "mu", "netmin"}


def som_ativo(cfg, hora):
    """'1' se o Mio pode apitar agora: som ligado e fora do horario de silencio."""
    it = cfg.get("internet_teste", {})
    if not it.get("som", True) or em_silencio(hora, it.get("silencio", "")):
        return "0"
    return "1"


def dados_frescos(d, agora):
    return "_em" in d and agora - d["_em"] <= DADOS_MAX_IDADE


def tempo_tela(cfg):
    """Segundos de cada tela no Mio (campo 'rot'), entre 5 e 600; padrao 10."""
    try:
        s = int(cfg.get("tempo_tela", 10))
    except (TypeError, ValueError):
        s = 10
    return str(min(600, max(5, s)))


def linha_serial(d):
    """Protocolo para o cliente do Mio: 'D|chave=valor|...\\r\\n' (ASCII, sem acento)."""
    def n(v, f="%.0f"):
        return "-" if v is None else f % v
    campos = [
        "D", "h=" + d["hora"], "host=" + d["host"][:16],
        "cpu=" + n(d["cpu"]), "ram=" + n(d["ram"]),
        "ramu=%d" % d["ram_u"], "ramt=%d" % d["ram_t"],
        "dsk=" + n(d["disco"]), "dskl=" + n(d["disco_livre"], "%.1f"),
        "tmp=" + n(d["temp"]), "up=" + d["uptime"],
        "png=" + n(d["ping"], "%.1f"),
        "alr=" + ";".join(d["alertas"]),
    ]
    for k, v in sorted(d.get("extra", {}).items()):
        if k not in NAO_ENVIAR:
            campos.append("%s=%s" % (k, v))
    texto = "|".join(c.replace("|", "/") for c in campos)
    return (texto.encode("cp1252", "replace") + b"\r\n")      # pagina de codigo do Mio


def loop_serial(coletor, cfg):
    import termios
    porta, baud = cfg["serial"]["porta"], cfg["serial"]["baud"]
    vel = getattr(termios, "B%d" % baud, termios.B115200)
    while True:
        fd = None
        try:
            fd = os.open(porta, os.O_RDWR | os.O_NOCTTY)
            at = termios.tcgetattr(fd)
            at[0] = 0; at[1] = 0                      # iflag, oflag: cru
            at[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            at[3] = 0                                 # lflag: sem eco/canonico
            at[4] = at[5] = vel
            termios.tcsetattr(fd, termios.TCSANOW, at)
            sys.stderr.write("serial: enviando para %s\n" % porta)
            while True:
                d = coletor.atual()
                if d and dados_frescos(d, time.monotonic()):
                    os.write(fd, linha_serial(d))
                # descarta o "MIO OLA" que o Mio manda: sem isso o buffer enche
                # e cada envio do Mio espera 1 s de timeout
                termios.tcflush(fd, termios.TCIFLUSH)
                time.sleep(cfg["intervalo"])
        except Exception as e:
            sys.stderr.write("serial %s: %r (nova tentativa em 5 s)\n" % (porta, e))
            time.sleep(5)
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    pass


# ----------------------------------------------------------------- HTML 320x240
# HTML 4.01 + tabelas + <font>: o Internet Explorer do WinCE 5 nao entende CSS moderno.
CORES = {"fundo": "#000000", "txt": "#FFFFFF", "mut": "#AAAAAA",
         "ok": "#00FF00", "al": "#FF3333", "am": "#FFCC00"}


def cor_pct(v, lim):
    if v is None:
        return CORES["mut"]
    return CORES["al"] if v > lim else (CORES["am"] if v > lim * 0.8 else CORES["ok"])


def pagina(titulo, corpo, prox, rot, fundo=None):
    fundo = fundo or CORES["fundo"]
    return ("<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.01 Transitional//EN\">\n"
            "<html><head><meta http-equiv=\"Content-Type\" content=\"text/html; charset=iso-8859-1\">"
            "<meta http-equiv=\"refresh\" content=\"%d;url=/?view=%s\">"
            "<title>%s</title></head>"
            "<body bgcolor=\"%s\" text=\"%s\" leftmargin=\"2\" topmargin=\"2\" marginwidth=\"2\" marginheight=\"2\">"
            "<table width=\"314\" cellpadding=\"1\" cellspacing=\"0\" border=\"0\">%s</table>"
            "</body></html>") % (rot, prox, titulo, fundo, CORES["txt"], corpo)


def linha(rotulo, valor, cor=None, tam=5):
    return ("<tr><td><font face=\"Tahoma\" size=\"3\" color=\"%s\">%s</font></td>"
            "<td align=\"right\"><font face=\"Tahoma\" size=\"%d\" color=\"%s\"><b>%s</b></font></td></tr>"
            % (CORES["mut"], html.escape(rotulo), tam, cor or CORES["txt"], html.escape(valor)))


def cabecalho(texto, d):
    return ("<tr><td><font face=\"Tahoma\" size=\"2\" color=\"%s\"><b>%s</b></font></td>"
            "<td align=\"right\"><font face=\"Tahoma\" size=\"2\" color=\"%s\">%s</font></td></tr>"
            % (CORES["am"], html.escape(texto), CORES["mut"], html.escape(d.get("hora", ""))))


def render(view, d, cfg):
    rot, L = cfg["rotacao"], cfg["limites"]
    if not d:
        return pagina("Mio", linha("Aguardando", "coleta..."), "sys", 2)
    alerta = bool(d["alertas"])
    if alerta:                       # alerta critico fixa a tela de alerta
        view = "alert"
    if view == "net":
        c = cabecalho("REDE " + d["iface"], d)
        rx = "-" if d["rx"] is None else "%.0f KB/s" % d["rx"]
        tx = "-" if d["tx"] is None else "%.0f KB/s" % d["tx"]
        c += linha("RX", rx, tam=4) + linha("TX", tx, tam=4)
        p = "FALHA" if d["ping"] is None else "%.0f ms" % d["ping"]
        c += linha("Ping", p, CORES["al"] if d["ping"] is None else CORES["ok"], tam=4)
        for nome, ok in d["servicos"]:
            c += linha(nome, "OK" if ok else "OFF", CORES["ok"] if ok else CORES["al"], tam=4)
        if d["pve"]:
            c += linha("VM/CT", "%d/%d  %d/%d" % d["pve"], tam=3)
        return pagina("Rede", c, "alert", rot)
    if view == "alert":
        if alerta:
            c = cabecalho("ALERTA", d)
            for a in d["alertas"][:6]:
                c += ("<tr><td colspan=\"2\"><font face=\"Tahoma\" size=\"5\" color=\"#FFFFFF\"><b>%s</b></font></td></tr>"
                      % html.escape(a))
            return pagina("ALERTA", c, "alert", rot, fundo="#B00000")
        c = cabecalho("ALERTAS", d) + linha("Status", "TUDO OK", CORES["ok"], tam=6)
        return pagina("Alertas", c, "sys", rot)
    # sys
    c = cabecalho(d["host"][:18], d)
    c += linha("CPU", "%.0f%%" % d["cpu"], cor_pct(d["cpu"], L["cpu"]), tam=6)
    c += linha("RAM", "%.0f%%" % d["ram"], cor_pct(d["ram"], L["ram"]), tam=5)
    c += linha("", "%d/%d MB" % (d["ram_u"], d["ram_t"]), CORES["mut"], tam=2)
    c += linha("Disco", "%.0f%%" % d["disco"], cor_pct(d["disco"], L["disco"]), tam=5)
    t = "-" if d["temp"] is None else "%.0f C" % d["temp"]
    c += linha("Temp", t, cor_pct(d["temp"], L["temp"]), tam=5)
    c += linha("Uptime", d["uptime"], tam=3)
    return pagina("Sistema", c, "net", rot)


class Handler(BaseHTTPRequestHandler):
    coletor = None
    cfg = None

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api":
            corpo = json.dumps(self.coletor.atual()).encode()
            tipo = "application/json"
        elif u.path in ("/", "/index.html"):
            view = parse_qs(u.query).get("view", ["sys"])[0]
            corpo = render(view, self.coletor.atual(), self.cfg).encode("iso-8859-1", "replace")
            tipo = "text/html; charset=iso-8859-1"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(AQUI, "config.json"))
    ap.add_argument("--once", action="store_true", help="coleta uma vez, imprime e sai")
    a = ap.parse_args()
    cfg = carregar_config(a.config)
    col = Coletor(cfg)
    if a.once:
        col.cpu(); time.sleep(1); col.coletar(); time.sleep(1)
        d = col.coletar()
        print(json.dumps(d, indent=2, ensure_ascii=False))
        print(linha_serial(d).decode().rstrip())
        return
    threading.Thread(target=col.loop, daemon=True).start()
    if cfg["serial"]["ativo"]:
        threading.Thread(target=loop_serial, args=(col, cfg), daemon=True).start()
    Handler.coletor, Handler.cfg = col, cfg
    srv = ThreadingHTTPServer((cfg["listen"], cfg["port"]), Handler)
    sys.stderr.write("Mio dashboard em http://%s:%d/?view=sys\n" % (cfg["listen"], cfg["port"]))
    srv.serve_forever()


if __name__ == "__main__":
    main()
