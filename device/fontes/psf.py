"""Leitor de fontes PSF2 (console do Linux), usado para gerar fontes_pixel.h.

Fonte: Terminus (Dimitar Zhekov), licenca SIL OFL 1.1, pacote console-setup do Debian.
"""
import gzip
import struct


def ler(caminho):
    dados = gzip.open(caminho).read() if caminho.endswith(".gz") else open(caminho, "rb").read()
    if dados[:2] == b"\x36\x04":  # PSF1: 8 px de largura, tabela unicode em uint16
        modo, alt = dados[2], dados[3]
        n = 512 if modo & 1 else 256
        glifos = [list(dados[4 + i * alt: 4 + (i + 1) * alt]) for i in range(n)]
        mapa = {}
        if modo & 2:
            p = 4 + n * alt
            for i in range(n):
                seq = False
                while True:
                    (u,) = struct.unpack("<H", dados[p:p + 2])
                    p += 2
                    if u == 0xFFFF:
                        break
                    if u == 0xFFFE:
                        seq = True
                    elif not seq:
                        mapa.setdefault(u, i)
        else:
            mapa = {i: i for i in range(n)}
        return {"larg": 8, "alt": alt, "glifos": glifos, "mapa": mapa}
    magic, ver, hsz, flags, n, bpg, alt, larg = struct.unpack("<8I", dados[:32])
    if magic != 0x864AB572:
        raise ValueError("nao e PSF: " + caminho)
    lb = (larg + 7) // 8
    glifos = []
    for i in range(n):
        g = dados[hsz + i * bpg: hsz + (i + 1) * bpg]
        linhas = [int.from_bytes(g[r * lb:(r + 1) * lb], "big") >> (lb * 8 - larg) for r in range(alt)]
        glifos.append(linhas)
    mapa = {}
    if flags & 1:  # tabela unicode (UTF-8, 0xFF separa glifos, 0xFE inicia sequencias)
        p = hsz + n * bpg
        for i in range(n):
            fim = dados.index(b"\xff", p)
            trecho = dados[p:fim].split(b"\xfe")[0]
            for ch in trecho.decode("utf-8"):
                mapa.setdefault(ord(ch), i)
            p = fim + 1
    else:
        mapa = {i: i for i in range(n)}
    return {"larg": larg, "alt": alt, "glifos": glifos, "mapa": mapa}


def glifo(f, cp):
    i = f["mapa"].get(cp)
    return None if i is None else f["glifos"][i]


def metricas(f):
    """linha de base = ultima linha com pixel no 'H' + 1; altura de maiuscula."""
    h = glifo(f, ord("H"))
    usadas = [r for r, v in enumerate(h) if v]
    return {"base": usadas[-1] + 1, "cap": usadas[-1] - usadas[0] + 1}
