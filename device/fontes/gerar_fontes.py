"""Gera device/fontes_pixel.h (fonte de pixel do MioDash) a partir da Terminus em PSF.

Uso: python3 gerar_fontes.py <pasta com Uni2-Terminus*.psf.gz> ../fontes_pixel.h
     (os .psf.gz vem do pacote console-setup-linux do Debian; Terminus = SIL OFL 1.1)

Cada glifo e recortado nas colunas com tinta (fonte proporcional): o avanco e a largura
da tinta + o espaco natural da Terminus. A tabela TAMANHOS liga o tamanho "Tahoma" usado
no mio_dash.c (px, negrito) a uma fonte e escala; o C e a previa usam a mesma tabela.
"""
import os
import re
import sys

import psf

# fontes embutidas: nome -> (arquivo, negrito sintetico)
FONTES = {
    "t12":  ("Uni2-Terminus12x6.psf.gz", False),
    "t12b": ("Uni2-Terminus12x6.psf.gz", True),
    "t14":  ("Uni2-Terminus14.psf.gz", False),
    "t14b": ("Uni2-TerminusBold14.psf.gz", False),
    "t16b": ("Uni2-TerminusBold16.psf.gz", False),
    "t18b": ("Uni2-TerminusBold18x10.psf.gz", False),
    "t20b": ("Uni2-TerminusBold20x10.psf.gz", False),
    "t22b": ("Uni2-TerminusBold22x11.psf.gz", False),
    "t24b": ("Uni2-TerminusBold24x12.psf.gz", False),
    "t28b": ("Uni2-TerminusBold28x14.psf.gz", False),
    "t32b": ("Uni2-TerminusBold32x16.psf.gz", False),
}

# (tamanho maximo em px, negrito) -> (fonte, escala). Percorrida em ordem; 1a que servir.
TAMANHOS = [
    (9, 0, "t12", 1), (9, 1, "t12b", 1),
    (10, 0, "t12", 1), (10, 1, "t12b", 1),
    (11, 0, "t14", 1), (11, 1, "t14b", 1),
    (13, 0, "t14", 1), (13, 1, "t16b", 1),
    (14, 1, "t16b", 1), (14, 0, "t16b", 1),
    (16, 1, "t18b", 1), (16, 0, "t18b", 1),
    (17, 1, "t20b", 1), (17, 0, "t20b", 1),
    (19, 1, "t22b", 1), (19, 0, "t22b", 1),
    (22, 1, "t24b", 1), (22, 0, "t24b", 1),
    (26, 1, "t28b", 1), (26, 0, "t28b", 1),
    (36, 1, "t32b", 1), (36, 0, "t32b", 1),
    (999, 1, "t28b", 2), (999, 0, "t28b", 2),
]


def escolher(tam, neg):
    neg = 1 if neg else 0
    for maximo, n, nome, esc in TAMANHOS:
        if tam <= maximo and n == neg:
            return nome, esc
    raise ValueError(tam)


# ASCII + Latin-1 + extras do cp1252 que o host pode mandar
CARACTERES = sorted(set(range(0x20, 0x7F)) | set(range(0xA0, 0x100)) |
                    {0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2026, 0x20AC,
                     0x2190, 0x2191, 0x2192, 0x2193, 0x25B2, 0x25BC})


def carregar(pasta, nome):
    arq, bold = FONTES[nome]
    f = psf.ler(os.path.join(pasta, arq))
    m = psf.metricas(f)
    h = psf.glifo(f, ord("H"))
    cols_h = [c for c in range(f["larg"]) if any((r >> (f["larg"] - 1 - c)) & 1 for r in h)]
    espaco_natural = f["larg"] - (cols_h[-1] - cols_h[0] + 1)
    larg = f["larg"] + (1 if bold else 0)
    glifos = {}
    for cp in CARACTERES:
        g = psf.glifo(f, cp)
        if g is None:
            continue
        linhas = list(g)
        if bold and not any(re.search("101", format(r, "b")) for r in linhas):
            # negrito: duplica 1 px a direita; pula glifos com tracos a 1 px (m, w, %...)
            linhas = [(r << 1) | r for r in linhas]
        cols = [c for c in range(larg) if any((r >> (larg - 1 - c)) & 1 for r in linhas)]
        if not cols:
            glifos[cp] = (0, [0] * f["alt"])
            continue
        c0, c1 = cols[0], cols[-1]
        w = c1 - c0 + 1
        recorte = [(r >> (larg - 1 - c1)) & ((1 << w) - 1) for r in linhas]
        glifos[cp] = (w, recorte)
    return {
        "nome": nome, "alt": f["alt"], "base": m["base"], "cap": m["cap"],
        "gap": max(1, espaco_natural), "espaco": max(2, (larg + 1) // 2),
        "glifos": glifos,
    }


def medir(fonte, texto, esc=1):
    """largura em px (igual ao C)."""
    total = 0
    for i, ch in enumerate(texto):
        g = fonte["glifos"].get(ord(ch)) or fonte["glifos"][ord("?")]
        total += (g[0] if g[0] else fonte["espaco"])
        if i < len(texto) - 1:
            total += fonte["gap"]
    return total * esc


def gerar_c(fontes, saida):
    out = ["/* GERADO por device/fontes/gerar_fontes.py - nao editar a mao.",
           " * Fonte: Terminus (c) Dimitar Zhekov, SIL Open Font License 1.1. */",
           "typedef struct { unsigned short cp; unsigned char w; unsigned short off; } GlifoPx;",
           "typedef struct { unsigned char alt, base, gap, espaco; int n;",
           "                 const GlifoPx *g; const unsigned char *d; } FontePx;", ""]
    nomes = list(FONTES)
    for nome in nomes:
        f = fontes[nome]
        dados, idx = [], []
        for cp in sorted(f["glifos"]):
            w, linhas = f["glifos"][cp]
            idx.append((cp, w, len(dados)))
            nb = (w + 7) // 8
            for r in linhas:
                r <<= nb * 8 - w  # alinha a esquerda (MSB = 1a coluna)
                dados.extend(r.to_bytes(nb, "big") if nb else b"")
        out.append(f"static const unsigned char FPX_{nome}_d[{max(1, len(dados))}] = {{")
        for i in range(0, len(dados), 24):
            out.append("  " + ",".join(str(b) for b in dados[i:i + 24]) + ",")
        out.append("};")
        out.append(f"static const GlifoPx FPX_{nome}_g[{len(idx)}] = {{")
        for i in range(0, len(idx), 6):
            out.append("  " + " ".join("{%d,%d,%d}," % t for t in idx[i:i + 6]))
        out.append("};")
    out.append("static const FontePx FPX[] = {")
    for nome in nomes:
        f = fontes[nome]
        n = len(f["glifos"])
        out.append(f"  {{{f['alt']},{f['base']},{f['gap']},{f['espaco']},{n},FPX_{nome}_g,FPX_{nome}_d}}, /* {nome} */")
    out.append("};")
    out.append("/* tamanho Tahoma (px, negrito) -> indice em FPX e escala */")
    out.append("static void fpx_escolher(int tam, int neg, const FontePx **f, int *esc)")
    out.append("{")
    out.append("    static const short t[][4] = {")
    for maximo, n, nome, esc in TAMANHOS:
        out.append(f"        {{{maximo},{n},{nomes.index(nome)},{esc}}},")
    out.append("    };")
    out.append("    int i;")
    out.append("    neg = neg ? 1 : 0;")
    out.append("    for (i = 0; i < (int)(sizeof(t) / sizeof(t[0])); i++)")
    out.append("        if (tam <= t[i][0] && neg == t[i][1]) { *f = &FPX[t[i][2]]; *esc = t[i][3]; return; }")
    out.append("    *f = &FPX[0]; *esc = 1;")
    out.append("}")
    open(saida, "w").write("\n".join(out) + "\n")


def carregar_todas(pasta):
    return {n: carregar(pasta, n) for n in FONTES}


if __name__ == "__main__":
    pasta, saida = sys.argv[1], sys.argv[2]
    fs = carregar_todas(pasta)
    gerar_c(fs, saida)
    print("ok:", saida, os.path.getsize(saida), "bytes;",
          ", ".join(f"{n} cap {f['cap']} gap {f['gap']}" for n, f in fs.items()))
