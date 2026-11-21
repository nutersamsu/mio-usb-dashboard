"""Previa das telas com a fonte de pixel (sem precisar do aparelho).

Pega os SVGs gerados por docs/telas/gerador/gerar.js, tira os <text>, rasteriza o fundo
em 320x240 com o ImageMagick e escreve o texto com as mesmas tabelas do fontes_pixel.h.
Uso: python3 previa.py <pasta psf> <pasta svg> <pasta saida>
Sai <tela>.png (320x240) e <tela>-3x.png (ampliada sem suavizar, para ver os pixels).
"""
import html
import os
import re
import subprocess
import sys

import gerar_fontes as gf

pasta_psf, pasta_svg, saida = sys.argv[1:4]
os.makedirs(saida, exist_ok=True)
FONTES = gf.carregar_todas(pasta_psf)
RE_TXT = re.compile(r"<text([^>]*)>(.*?)</text>", re.S)


def attr(a, nome, padrao=None):
    m = re.search(r'\b%s="([^"]*)"' % nome, a)
    return m.group(1) if m else padrao


def ler_ppm(p):
    d = open(p, "rb").read()
    partes = d.split(b"\n", 3)
    w, h = map(int, partes[1].split())
    return w, h, bytearray(partes[3])


def cor(hexa):
    hexa = hexa.lstrip("#")
    if len(hexa) == 3:
        hexa = "".join(c * 2 for c in hexa)
    return tuple(int(hexa[i:i + 2], 16) for i in (0, 2, 4))


def escrever(pix, W, H, f, esc, rgb, x, y, texto, anc):
    larg = gf.medir(f, texto, esc)
    if anc == "middle":
        x -= larg // 2
    elif anc == "end":
        x -= larg
    topo = y - f["base"] * esc
    for i, ch in enumerate(texto):
        w, linhas = f["glifos"].get(ord(ch)) or f["glifos"][ord("?")]
        for r, bits in enumerate(linhas):
            for c in range(w):
                if (bits >> (w - 1 - c)) & 1:
                    for dy in range(esc):
                        for dx in range(esc):
                            px, py = x + c * esc + dx, topo + r * esc + dy
                            if 0 <= px < W and 0 <= py < H:
                                k = (py * W + px) * 3
                                pix[k:k + 3] = bytes(rgb)
        x += ((w if w else f["espaco"]) + f["gap"]) * esc


for nome in sorted(os.listdir(pasta_svg)):
    if not nome.endswith(".svg"):
        continue
    svg = open(os.path.join(pasta_svg, nome)).read()
    textos = []
    for a, conteudo in RE_TXT.findall(svg):
        conteudo = html.unescape(re.sub(r"<[^>]+>", "", conteudo))
        tam = round(float(attr(a, "font-size", "10")))
        peso = int(attr(a, "font-weight", "400"))
        neg = peso >= 700 or (peso >= 600 and conteudo == conteudo.upper())
        textos.append((float(attr(a, "x", "0")), float(attr(a, "y", "0")), tam, neg,
                       attr(a, "fill", "#ffffff"), attr(a, "text-anchor", "start"), conteudo))
    fundo = RE_TXT.sub("", svg)
    base = os.path.join(saida, nome[:-4])
    open(base + "-fundo.svg", "w").write(fundo)
    subprocess.run(["convert", "-background", "black", base + "-fundo.svg", "-resize", "320x240!", "-depth", "8",
                    base + ".ppm"], check=True)
    W, H, pix = ler_ppm(base + ".ppm")
    for x, y, tam, neg, fill, anc, t in textos:
        nomef, esc = gf.escolher(tam, neg)
        escrever(pix, W, H, FONTES[nomef], esc, cor(fill), int(round(x)), int(round(y)), t, anc)
    open(base + ".ppm", "wb").write(b"P6\n%d %d\n255\n" % (W, H) + bytes(pix))
    subprocess.run(["convert", base + ".ppm", base + ".png"], check=True)
    subprocess.run(["convert", base + ".ppm", "-filter", "point", "-resize", "300%", base + "-3x.png"], check=True)
    os.remove(base + ".ppm")
    os.remove(base + "-fundo.svg")
    print("ok", base + ".png")
