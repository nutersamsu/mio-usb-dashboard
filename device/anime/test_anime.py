"""Confere um anime.bin: cabecalho e cada quadro decodificado com o mesmo laco do
anim_quadro() do mio_dash.c (fundo, pular/copiar, sem passar do fim).

Uso: python3 test_anime.py anime.bin [quadro.png]   (com .png, grava o quadro 0 para olhar)
"""
import struct
import subprocess
import sys


def decodificar(d, q):
    w, h, n, atraso, fundo = struct.unpack("<5H", d[4:14])
    (off,) = struct.unpack("<I", d[16 + 4 * q:20 + 4 * q])
    px = [fundo] * (w * h)
    p, x, y = off, 0, 0
    while y < h and p < len(d):
        b = d[p]
        p += 1
        k = (b & 0x7F) + 1
        if b & 0x80:
            while k > 0 and y < h and p + 2 <= len(d):
                px[y * w + x] = d[p] | (d[p + 1] << 8)
                p += 2
                k -= 1
                x += 1
                if x == w:
                    x, y = 0, y + 1
            assert k == 0, "quadro %d truncado" % q
        else:
            x += k
            while x >= w and y < h:
                x, y = x - w, y + 1
    assert y == h and x == 0, "quadro %d nao fecha em %dx%d (y=%d x=%d)" % (q, w, h, y, x)
    return w, h, px


def main():
    d = open(sys.argv[1], "rb").read()
    assert d[:4] == b"MIOA"
    w, h, n, atraso, fundo = struct.unpack("<5H", d[4:14])
    assert w % 2 == 0 and 0 < w <= 308 and 0 < h <= 206 and n > 0 and atraso >= 20
    for q in range(n):
        decodificar(d, q)
    print(f"ok: {w}x{h}, {n} quadros, {atraso} ms, fundo {fundo:04x}, {len(d)} bytes")
    if len(sys.argv) > 2:
        w, h, px = decodificar(d, 0)
        rgb = bytearray()
        for v in px:
            rgb += bytes((((v >> 11) & 31) << 3, ((v >> 5) & 63) << 2, (v & 31) << 3))
        subprocess.run(["convert", "-size", f"{w}x{h}", "-depth", "8", "rgb:-", sys.argv[2]],
                       input=bytes(rgb), check=True)


if __name__ == "__main__":
    main()
