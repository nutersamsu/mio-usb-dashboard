"""Registro dos ultimos eventos (subida e descida de alertas), para a tela Sistema do Mio.

Um evento so nasce quando um alerta aparece ou some, nunca enquanto ele continua ativo.
Pisca-pisca: o mesmo alerta subindo de novo em menos de 5 min nao gera outro par de eventos.
Campo 'ev' da linha: "hh:mm,nivel,texto;..." (mais novo primeiro, 4 eventos).
"""
import json
import os
import re
import sys
import time

NIVEIS = ("INFO", "ALERTA", "CRÍTICO")
MAX_GUARDADOS = 20
NO_CAMPO = 4
TEXTO_MAX = 28
REPETICAO_S = 300
VOLTOU = {"internet": "Internet voltou", "gw": "Gateway voltou", "dns": "DNS voltou",
          "cs": "CrowdSec voltou", "old:pve": "Proxmox voltou", "old:crowdsec": "CrowdSec voltou"}


def limpar(texto):
    texto = re.sub(r" há \d+ min$", "", texto)              # "Internet caiu há 3 min"
    for c in ",;|\r\n":
        texto = texto.replace(c, " ")
    return " ".join(texto.split())[:TEXTO_MAX]


def _hora(t):
    return time.strftime("%H:%M", time.localtime(t))


class Eventos:
    def __init__(self, arquivo=None, hora=_hora, log=None):
        self.arquivo, self.hora = arquivo, hora
        self.log = log if log is not None else (lambda s: sys.stderr.write(s + "\n"))
        self.lista = self._carregar()               # [(hh:mm, nivel, texto)], mais novo primeiro
        self._ativos = {}                           # chave -> (nivel, texto, registrado?)
        self._subiu_em = {}                         # chave -> ultima subida registrada

    def _carregar(self):
        if not self.arquivo:
            return []
        try:
            with open(self.arquivo) as f:
                return [tuple(x) for x in json.load(f)][:MAX_GUARDADOS]
        except (OSError, ValueError, TypeError):
            return []

    def _salvar(self):
        if not self.arquivo:
            return
        try:
            tmp = self.arquivo + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.lista, f, ensure_ascii=False)
            os.replace(tmp, self.arquivo)
        except OSError:
            pass

    def _novo(self, t, nivel, texto):
        texto = limpar(texto)
        self.lista.insert(0, (self.hora(t), nivel, texto))
        del self.lista[MAX_GUARDADOS:]
        self.log("evento: %s %s" % (NIVEIS[nivel], texto))
        self._salvar()

    def info(self, texto, t):
        self._novo(t, 0, texto)

    def atualizar(self, alertas, t):
        """alertas = [(chave, nivel, bip, texto)] do momento."""
        agora = {a[0]: a for a in alertas}
        for chave, nivel, _, texto in alertas:
            if chave in self._ativos:
                continue
            registrar = t - self._subiu_em.get(chave, -1e12) >= REPETICAO_S
            if registrar:
                self._subiu_em[chave] = t
                self._novo(t, nivel, texto)
            self._ativos[chave] = (nivel, texto, registrar)
        for chave in [c for c in self._ativos if c not in agora]:
            _, texto, registrado = self._ativos.pop(chave)
            if registrado:
                self._novo(t, 0, VOLTOU.get(chave, "Normal: " + limpar(texto)))

    def campo(self):
        return ";".join("%s,%d,%s" % e for e in self.lista[:NO_CAMPO])
