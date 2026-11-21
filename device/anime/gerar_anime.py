"""Converte um GIF animado em anime.bin para a tela de animacao do MioDash.

Uso: python3 gerar_anime.py entrada.gif anime.bin [--altura 204] [--previa pasta]
Requer o ImageMagick (convert) para abrir o GIF.

O que faz em cada quadro:
  1. tira o fundo liso (cor do canto) por preenchimento a partir das bordas;
  2. tira a sombra do chao (cinza claro sem cor na parte de baixo) e o contorno claro
     que sobra do antialias com o fundo branco;
  3. recorta todos os quadros pela mesma caixa, reduz para a altura pedida e mistura as
     bordas com a cor do painel (K_PAN), ja que o Mio desenha sobre um fundo liso;
  4. grava em RGB565 com RLE: pixels de fundo viram "pular", o resto "copiar".

Formato (little-endian):
  "MIOA" | u16 larg | u16 alt | u16 quadros | u16 atraso_ms | u16 fundo565 | u16 0
  | u32 deslocamento[quadros] (a partir do inicio do arquivo) | dados
  dados de um quadro, lidos em ordem de linha ate larg*alt pixels:
    byte b < 0x80  -> pula b+1 pixels (fundo)
    byte b >= 0x80 -> copia (b & 0x7f)+1 pixels u16 RGB565 que vem a seguir
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
from collections import deque

FUNDO = (0x14, 0x16, 0x1B)  # K_PAN do mio_dash.c


def sh(*a, entrada=None):
    return subprocess.run(a, check=True, capture_output=True, input=entrada).stdout


def quadros_do_gif(gif):
    with tempfile.TemporaryDirectory() as tmp:
        sh("convert", gif, "-coalesce", os.path.join(tmp, "q%03d.png"))
        nomes = sorted(os.listdir(tmp))
        w, h = map(int, sh("identify", "-format", "%w %h", os.path.join(tmp, nomes[0])).split())
        quadros = [bytearray(sh("convert", os.path.join(tmp, n), "-depth", "8", "rgba:-"))
                   for n in nomes]
    atrasos = sh("identify", "-format", "%T ", gif).split()
    atraso = int(atrasos[0]) * 10 if atrasos else 80
    return w, h, quadros, max(20, atraso)


def tirar_fundo(px, w, h, tol=18):
    fr, fg, fb = px[0], px[1], px[2]
    perto = lambda i: (abs(px[i] - fr) <= tol and abs(px[i + 1] - fg) <= tol
                       and abs(px[i + 2] - fb) <= tol)
    perto_estrito = lambda i: (abs(px[i] - fr) <= 4 and abs(px[i + 1] - fg) <= 4
                               and abs(px[i + 2] - fb) <= 4)
    visto = bytearray(w * h)
    fila = deque()
    for x in range(w):
        fila.extend(((x, 0), (x, h - 1)))
    for y in range(h):
        fila.extend(((0, y), (w - 1, y)))
    while fila:
        x, y = fila.popleft()
        k = y * w + x
        if visto[k]:
            continue
        visto[k] = 1
        if not perto(k * 4):
            continue
        px[k * 4 + 3] = 0
        if x > 0: fila.append((x - 1, y))
        if x < w - 1: fila.append((x + 1, y))
        if y > 0: fila.append((x, y - 1))
        if y < h - 1: fila.append((x, y + 1))

    # bolsoes de fundo presos (entre pernas, cabelo e braco): regioes da cor do fundo,
    # quase exata, que nao encostam na borda
    for k0 in range(w * h):
        if visto[k0] or not px[k0 * 4 + 3] or not perto_estrito(k0 * 4):
            continue
        regiao, fila2 = [], deque([k0])
        visto[k0] = 1
        borda_clara = borda = 0
        while fila2:
            k = fila2.popleft()
            regiao.append(k)
            x, y = k % w, k // w
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    nk = ny * w + nx
                    if visto[nk] and perto_estrito(nk * 4):
                        continue
                    if px[nk * 4 + 3] and perto_estrito(nk * 4):
                        visto[nk] = 1
                        fila2.append(nk)
                    else:
                        # fora da regiao: olha 3 px alem (pula o degrade da borda);
                        # o brilho da camisa e cercado de cinza claro, o bolsao nao
                        fx = min(w - 1, max(0, nx + 3 * (nx - x)))
                        fy = min(h - 1, max(0, ny + 3 * (ny - y)))
                        i = (fy * w + fx) * 4
                        borda += 1
                        if min(px[i:i + 3]) >= 165 and max(px[i:i + 3]) - min(px[i:i + 3]) < 20:
                            borda_clara += 1
        if len(regiao) >= 40 and borda_clara < borda * 0.5:
            for k in regiao:
                px[k * 4 + 3] = 0

    def cinza_claro(i, minimo):
        r, g, b = px[i], px[i + 1], px[i + 2]
        return max(r, g, b) - min(r, g, b) < 14 and min(r, g, b) >= minimo

    # sombra do chao: cinza claro sem cor no terco de baixo
    for y in range(int(h * 0.62), h):
        for x in range(w):
            i = (y * w + x) * 4
            if px[i + 3] and cinza_claro(i, 150):
                px[i + 3] = 0
    # contorno claro: 2 passadas tirando quase-branco encostado no transparente
    for _ in range(2):
        tirar = []
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                i = (y * w + x) * 4
                if px[i + 3] and cinza_claro(i, 200):
                    if (not px[i - 4 + 3] or not px[i + 4 + 3] or
                            not px[i - w * 4 + 3] or not px[i + w * 4 + 3]):
                        tirar.append(i)
        for i in tirar:
            px[i + 3] = 0
    # restos soltos da sombra: pedacos opacos pequenos sem ligacao com o corpo
    marca = bytearray(w * h)
    for k0 in range(w * h):
        if marca[k0] or not px[k0 * 4 + 3]:
            continue
        regiao, fila3 = [], deque([k0])
        marca[k0] = 1
        while fila3:
            k = fila3.popleft()
            regiao.append(k)
            x, y = k % w, k // w
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    nk = ny * w + nx
                    if not marca[nk] and px[nk * 4 + 3]:
                        marca[nk] = 1
                        fila3.append(nk)
        if len(regiao) < 60:
            for k in regiao:
                px[k * 4 + 3] = 0


def caixa(quadros, w, h):
    x0, y0, x1, y1 = w, h, -1, -1
    for px in quadros:
        for y in range(h):
            linha = px[y * w * 4:(y + 1) * w * 4]
            if not any(linha[3::4]):
                continue
            xs = [x for x in range(w) if linha[x * 4 + 3]]
            x0, x1 = min(x0, xs[0]), max(x1, xs[-1])
            y0, y1 = min(y0, y), max(y1, y)
    return x0, y0, x1 - x0 + 1, y1 - y0 + 1


def reduzir(px, w, h, cx, cy, cw, ch, nw, nh):
    bruto = bytes(px)
    return bytearray(sh("convert", "-size", f"{w}x{h}", "-depth", "8", "rgba:-",
                        "-crop", f"{cw}x{ch}+{cx}+{cy}", "+repage",
                        "-filter", "Lanczos", "-resize", f"{nw}x{nh}!", "rgba:-", entrada=bruto))


def rgb565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def codificar(px, w, h):
    """mistura com o fundo e gera o RLE; devolve (bytes, rgb final p/ previa)."""
    final = bytearray(w * h * 3)
    vals = []  # None = fundo
    for k in range(w * h):
        r, g, b, a = px[k * 4:k * 4 + 4]
        if a < 40:
            vals.append(None)
            final[k * 3:k * 3 + 3] = bytes(FUNDO)
            continue
        r = (r * a + FUNDO[0] * (255 - a)) // 255
        g = (g * a + FUNDO[1] * (255 - a)) // 255
        b = (b * a + FUNDO[2] * (255 - a)) // 255
        vals.append(rgb565(r, g, b))
        final[k * 3:k * 3 + 3] = bytes((r, g, b))
    out = bytearray()
    k, n = 0, len(vals)
    while k < n:
        if vals[k] is None:
            j = k
            while j < n and vals[j] is None and j - k < 128:
                j += 1
            out.append(j - k - 1)
        else:
            j = k
            while j < n and vals[j] is not None and j - k < 128:
                j += 1
            out.append(0x80 | (j - k - 1))
            for v in vals[k:j]:
                out += struct.pack("<H", v)
        k = j
    return bytes(out), final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gif")
    ap.add_argument("saida")
    ap.add_argument("--altura", type=int, default=204)
    ap.add_argument("--largura-max", type=int, default=300)
    ap.add_argument("--previa", help="pasta para gravar a previa (GIF sobre o fundo do painel)")
    a = ap.parse_args()

    w, h, quadros, atraso = quadros_do_gif(a.gif)
    print(f"{len(quadros)} quadros {w}x{h}, {atraso} ms", file=sys.stderr)
    for px in quadros:
        tirar_fundo(px, w, h)
    cx, cy, cw, ch = caixa(quadros, w, h)
    nh = a.altura
    nw = round(cw * nh / ch)
    if nw > a.largura_max:
        nw, nh = a.largura_max, round(ch * a.largura_max / cw)
    nw += nw & 1  # largura par: linha do DIB de 16 bits sem preenchimento
    print(f"caixa {cw}x{ch}+{cx}+{cy} -> {nw}x{nh}", file=sys.stderr)

    blocos, finais = [], []
    for px in quadros:
        dados, final = codificar(reduzir(px, w, h, cx, cy, cw, ch, nw, nh), nw, nh)
        blocos.append(dados)
        finais.append(final)

    cab = b"MIOA" + struct.pack("<6H", nw, nh, len(blocos), atraso, rgb565(*FUNDO), 0)
    pos = len(cab) + 4 * len(blocos)
    tabela = b""
    for d in blocos:
        tabela += struct.pack("<I", pos)
        pos += len(d)
    with open(a.saida, "wb") as f:
        f.write(cab + tabela + b"".join(blocos))
    print(f"ok: {a.saida} {os.path.getsize(a.saida)} bytes", file=sys.stderr)

    if a.previa:
        os.makedirs(a.previa, exist_ok=True)
        tira = b"".join(finais)
        sh("convert", "-size", f"{nw}x{nh}", "-depth", "8", f"rgb:-[0-{len(finais) - 1}]",
           "-delay", str(atraso // 10), "-loop", "0", os.path.join(a.previa, "anime-previa.gif"),
           entrada=tira)
        sh("convert", "-size", f"{nw}x{nh}", "-depth", "8", "rgb:-[0]",
           os.path.join(a.previa, "anime-quadro0.png"), entrada=finais[0])


if __name__ == "__main__":
    main()
