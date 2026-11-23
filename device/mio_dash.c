/*
 * MioDash - cliente do dashboard para o Mio DigiWalker C250 (WinCE 5.0 Core, ARMv4)
 *
 * Le linhas "D|chave=valor|..." da porta serial USB (COM9: no C250) enviadas pelo
 * host/server.py e desenha 3 vistas em tela cheia 320x240:
 *   SISTEMA (cpu/ram/disco/temp/uptime) -> REDE (rx/tx/ping/servicos) -> ALERTAS
 * Se chegar alerta, fixa a tela vermelha de alerta ate normalizar.
 *
 * Toque na tela: passa para a proxima vista.
 * Toque no canto superior direito (40x40): fecha o programa.
 * Mantem a tela acesa chamando SystemIdleTimerReset() periodicamente.
 *
 * Compilar (CeGCC / mingw32ce, no Linux):
 *   arm-mingw32ce-gcc -O2 -Wall -o MioDash.exe mio_dash.c
 * Porta: argumento opcional, ex.  MioDash.exe COM9:
 *
 * Tema "sensor panel" Neon, 7 telas (internet, conexao, servidor, maquinas, servicos,
 * seguranca, sistema) + ANIME (se houver anime.bin ao lado do exe) + alerta. Alerta ambar (aviso, sem som) ou vermelho (critico, bip;
 * um toque reconhece). Desenho: docs/telas-mio-v3.html.
 */
#include <windows.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <math.h>

/* coredll.dll exporta; alguns headers do mingw32ce nao declaram */
void WINAPI SystemIdleTimerReset(void);
/* CeRunAppAtEvent e opcional no WinCE (componente Notify): carregada em tempo
 * de execucao para o exe abrir mesmo numa ROM sem ela. */
typedef BOOL (WINAPI *PFN_RUNAPPATEVENT)(WCHAR *, LONG);
#ifndef NOTIFICATION_EVENT_NONE
#define NOTIFICATION_EVENT_NONE 0
#endif

static void cancelar_repllog_automatico(void)
{
    HMODULE core = LoadLibraryW(L"coredll.dll");
    PFN_RUNAPPATEVENT f;
    if (!core) return;
    f = (PFN_RUNAPPATEVENT)GetProcAddressW(core, L"CeRunAppAtEvent");
    if (f) {
        f(L"\\Windows\\repllog.exe", NOTIFICATION_EVENT_NONE);
        f(L"repllog.exe", NOTIFICATION_EVENT_NONE);
    }
    FreeLibrary(core);
}

/* ---- fechar quem segura a COM9 (no C250: MutDevice*.exe, servico da Mitac).
 * toolhelp.dll e carregada em tempo de execucao: se nao existir, nada acontece. */
typedef struct {
    DWORD dwSize, cntUsage, th32ProcessID, th32DefaultHeapID, th32ModuleID,
          cntThreads, th32ParentProcessID;
    LONG  pcPriClassBase;
    DWORD dwFlags;
    WCHAR szExeFile[MAX_PATH];
    DWORD th32MemoryBase, th32AccessKey;
} PROCESSO_CE;
typedef HANDLE (WINAPI *PFN_SNAP)(DWORD, DWORD);
typedef BOOL   (WINAPI *PFN_P32)(HANDLE, PROCESSO_CE *);
typedef BOOL   (WINAPI *PFN_CLOSESNAP)(HANDLE);

static char g_fechado[48] = "";       /* ultimo processo fechado (mostrado na tela) */

static int comeca_com(const WCHAR *nome, const WCHAR *prefixo)
{
    while (*prefixo) {
        WCHAR a = *nome++, b = *prefixo++;
        if (a >= L'A' && a <= L'Z') a += 32;
        if (b >= L'A' && b <= L'Z') b += 32;
        if (a != b) return 0;
    }
    return 1;
}

static int fechar_donos_da_porta(void)
{
    static const WCHAR *alvos[] = { L"MutDevice", L"repllog", L"rapiclnt", L"rnaapp", NULL };
    HMODULE th = LoadLibraryW(L"toolhelp.dll");
    PFN_SNAP snap; PFN_P32 primeiro, proximo; PFN_CLOSESNAP fechar;
    PROCESSO_CE pe;
    HANDLE s;
    int n = 0, ok, i;
    DWORD eu = GetCurrentProcessId();
    if (!th) return 0;
    snap = (PFN_SNAP)GetProcAddressW(th, L"CreateToolhelp32Snapshot");
    primeiro = (PFN_P32)GetProcAddressW(th, L"Process32First");
    proximo = (PFN_P32)GetProcAddressW(th, L"Process32Next");
    fechar = (PFN_CLOSESNAP)GetProcAddressW(th, L"CloseToolhelp32Snapshot");
    if (!snap || !primeiro || !proximo) { FreeLibrary(th); return 0; }
    s = snap(2 /* TH32CS_SNAPPROCESS */, 0);
    if (s == INVALID_HANDLE_VALUE) { FreeLibrary(th); return 0; }
    memset(&pe, 0, sizeof(pe));
    pe.dwSize = sizeof(pe);
    for (ok = primeiro(s, &pe); ok; ok = proximo(s, &pe)) {
        if (pe.th32ProcessID == eu) continue;
        for (i = 0; alvos[i]; i++) {
            if (comeca_com(pe.szExeFile, alvos[i])) {
                HANDLE p = OpenProcess(0, FALSE, pe.th32ProcessID);
                if (p) {
                    if (TerminateProcess(p, 0)) {
                        WideCharToMultiByte(CP_ACP, 0, pe.szExeFile, -1,
                                            g_fechado, sizeof(g_fechado) - 1, NULL, NULL);
                        n++;
                    }
                    CloseHandle(p);
                }
                break;
            }
        }
        pe.dwSize = sizeof(pe);
    }
    if (fechar) fechar(s); else CloseHandle(s);
    FreeLibrary(th);
    return n;
}

#define ID_TIMER_IDLE  2
#define ID_TIMER_PROG  3
#define WM_DADOS       (WM_APP + 1)
#define ROTACAO_PADRAO 10      /* segundos; o host manda "rot" (config tempo_tela) */
#define PROG_MS        250
#define SEM_DADOS_MS   15000
#define MAX_CAMPOS     64
#define VERSAO         L"3.1"
#define N_TELAS        7       /* sem contar a de alerta */
#define LARG           320
#define ALT            240

/* ---- tema Neon (mesmas cores do mockup docs/telas-mio-v2.html) */
#define K_BG    RGB(0x0a, 0x0b, 0x0e)
#define K_PAN   RGB(0x14, 0x16, 0x1b)
#define K_BORDA RGB(0x34, 0x38, 0x43)
#define K_OFF   RGB(0x26, 0x29, 0x31)
#define K_ABA   RGB(0x19, 0x1c, 0x22)
#define K_TIT   RGB(0xc8, 0xcc, 0xd6)
#define K_TXT   RGB(0xf1, 0xf3, 0xf7)
#define K_MUT   RGB(0x8a, 0x90, 0xa0)
#define K_OK    RGB(0x34, 0xd3, 0x99)
#define K_AL    RGB(0xf8, 0x71, 0x71)

typedef struct { COLORREF a, b, c; } Paleta;
static const Paleta PAL_NEON   = { RGB(0xff, 0x4f, 0xa3), RGB(0xa8, 0x55, 0xf7), RGB(0x3b, 0x82, 0xf6) };
static const Paleta PAL_ALERTA = { RGB(0xb9, 0x1c, 0x1c), RGB(0xef, 0x44, 0x44), RGB(0xfc, 0xa5, 0xa5) };
static const Paleta PAL_AVISO  = { RGB(0xc2, 0x41, 0x0c), RGB(0xf5, 0x9e, 0x0b), RGB(0xfc, 0xd3, 0x4d) };
#define K_AM    RGB(0xf5, 0x9e, 0x0b)
static const Paleta *g_pal = &PAL_NEON;

typedef struct { char k[12]; char v[200]; } Campo;

static Campo   g_campos[MAX_CAMPOS];
static int     g_ncampos = 0;
static CRITICAL_SECTION g_cs;
static DWORD   g_ultimo = 0;          /* GetTickCount da ultima linha valida */
static int     g_vista = 0;           /* posicao na rotacao: 0 internet .. 6 sistema, 7 alerta */
static DWORD   g_inicio = 0;          /* GetTickCount de quando a tela atual comecou */
static HWND    g_hwnd;
static WCHAR   g_porta[16] = L"COM9:";
static volatile int g_rodando = 1;
static char    g_status[64] = "abrindo porta";
/* diagnostico da serial: bytes recebidos/enviados e ultimo erro */
static volatile DWORD g_rx = 0, g_tx = 0, g_err = 0;
static volatile DWORD g_linhas = 0, g_sinais = 0;   /* linhas validas e "MIO OLA" enviados */

/* ------------------------------------------------------------ dados */
static const char *val(const char *k)
{
    int i;
    for (i = 0; i < g_ncampos; i++)
        if (strcmp(g_campos[i].k, k) == 0) return g_campos[i].v;
    return "-";
}

static void interpretar(char *linha)
{
    Campo novos[MAX_CAMPOS];
    int n = 0;
    char *p = linha, *sep;
    if (linha[0] != 'D' || linha[1] != '|') return;
    p += 2;
    while (*p && n < MAX_CAMPOS) {
        char *eq;
        sep = strchr(p, '|');
        if (sep) *sep = 0;
        eq = strchr(p, '=');
        if (eq) {
            *eq = 0;
            strncpy(novos[n].k, p, sizeof(novos[n].k) - 1);
            novos[n].k[sizeof(novos[n].k) - 1] = 0;
            strncpy(novos[n].v, eq + 1, sizeof(novos[n].v) - 1);
            novos[n].v[sizeof(novos[n].v) - 1] = 0;
            n++;
        }
        if (!sep) break;
        p = sep + 1;
    }
    EnterCriticalSection(&g_cs);
    memcpy(g_campos, novos, n * sizeof(Campo));
    g_ncampos = n;
    g_ultimo = GetTickCount();
    g_linhas++;
    LeaveCriticalSection(&g_cs);
    PostMessage(g_hwnd, WM_DADOS, 0, 0);
}

/* ------------------------------------------------------------ serial */
static DWORD WINAPI leitor(LPVOID arg)
{
    char buf[256], linha[2048];
    int len = 0;
    (void)arg;
    while (g_rodando) {
        HANDLE h = CreateFileW(g_porta, GENERIC_READ | GENERIC_WRITE, 0, NULL,
                               OPEN_EXISTING, 0, NULL);
        if (h == INVALID_HANDLE_VALUE) {
            /* 32 = outro programa com a porta; 55/1167 = sem dispositivo;
             * 2 = porta nao existe; 5 = acesso negado */
            g_err = GetLastError();
            strcpy(g_status, "porta indisponivel");
            /* 12/32: outro processo tem a porta -> fecha o dono e tenta logo */
            if ((g_err == 12 || g_err == 32) && fechar_donos_da_porta() > 0) {
                strcpy(g_status, "porta liberada");
                PostMessage(g_hwnd, WM_DADOS, 0, 0);
                Sleep(800);
                continue;
            }
            PostMessage(g_hwnd, WM_DADOS, 0, 0);
            Sleep(3000);
            continue;
        }
        {
            DCB dcb;
            COMMTIMEOUTS to;
            memset(&dcb, 0, sizeof(dcb));
            dcb.DCBlength = sizeof(dcb);
            GetCommState(h, &dcb);
            dcb.BaudRate = CBR_115200;
            dcb.ByteSize = 8;
            dcb.Parity = NOPARITY;
            dcb.StopBits = ONESTOPBIT;
            dcb.fBinary = TRUE;
            dcb.fDtrControl = DTR_CONTROL_ENABLE;
            dcb.fRtsControl = RTS_CONTROL_ENABLE;
            SetCommState(h, &dcb);
            memset(&to, 0, sizeof(to));
            to.ReadIntervalTimeout = 50;
            to.ReadTotalTimeoutConstant = 1000;
            to.WriteTotalTimeoutConstant = 1000;    /* nunca ficar preso na escrita */
            SetCommTimeouts(h, &to);
        }
        strcpy(g_status, "aguardando dados");
        PostMessage(g_hwnd, WM_DADOS, 0, 0);
        len = 0;
        {
            DWORD ultimo_ping = 0, nping = 0;
        while (g_rodando) {
            DWORD lidos = 0, i;
            /* sinal de vida para o host: prova que a COM e o canal certo */
            if (GetTickCount() - ultimo_ping >= 2000) {
                char ping[32];
                DWORD escritos = 0;
                int n = _snprintf(ping, sizeof(ping), "MIO OLA %lu\r\n", (unsigned long)nping++);
                if (WriteFile(h, ping, n, &escritos, NULL)) { g_tx += escritos; g_sinais++; }
                else g_err = GetLastError();
                ultimo_ping = GetTickCount();
                PostMessage(g_hwnd, WM_DADOS, 0, 0);
            }
            if (!ReadFile(h, buf, sizeof(buf), &lidos, NULL)) {        /* cabo saiu */
                g_err = GetLastError();
                break;
            }
            g_rx += lidos;
            for (i = 0; i < lidos; i++) {
                char c = buf[i];
                if (c == '\n' || c == '\r') {
                    if (len > 0) { linha[len] = 0; interpretar(linha); }
                    len = 0;
                } else if (len < (int)sizeof(linha) - 1) {
                    linha[len++] = c;
                } else {
                    len = 0;                                         /* linha longa demais */
                }
            }
        }
        }
        CloseHandle(h);
        strcpy(g_status, "reconectando");
        Sleep(1000);
    }
    return 0;
}


/* ------------------------------------------------------------ som
 * Bip gerado na memoria (WAV 11025 Hz, 8 bits, mono, onda quadrada).
 * PlaySoundW e waveOutSetVolume carregados em tempo de execucao. */
#ifndef SND_ASYNC
#define SND_ASYNC     0x0001
#define SND_NODEFAULT 0x0002
#define SND_MEMORY    0x0004
#endif
#define ALARME_MS     10000
typedef BOOL (WINAPI *PFN_PLAYSOUND)(LPCWSTR, HMODULE, DWORD);
typedef UINT (WINAPI *PFN_WAVEVOL)(HANDLE, DWORD);
typedef struct { int hz, ms; } Nota;

static PFN_PLAYSOUND g_play = NULL;
static PFN_WAVEVOL   g_vol = NULL;
static BYTE *g_som_alarme = NULL, *g_som_ok = NULL;
static int   g_bip_ant = 0;
static char  g_aid_sil[8] = "";       /* conjunto de criticos ja reconhecido (toque) */
static DWORD g_ultimo_bip = 0;

static void pos32(BYTE *b, DWORD v) { b[0] = (BYTE)v; b[1] = (BYTE)(v >> 8); b[2] = (BYTE)(v >> 16); b[3] = (BYTE)(v >> 24); }
static void pos16(BYTE *b, WORD v)  { b[0] = (BYTE)v; b[1] = (BYTE)(v >> 8); }

static BYTE *gerar_wav(const Nota *n, int qtd)
{
    const DWORD taxa = 11025;
    DWORD total = 0, p = 44;
    int i, k;
    BYTE *b;
    for (i = 0; i < qtd; i++) total += taxa * n[i].ms / 1000;
    b = (BYTE *)malloc(44 + total);
    if (!b) return NULL;
    memcpy(b, "RIFF", 4); pos32(b + 4, 36 + total); memcpy(b + 8, "WAVEfmt ", 8);
    pos32(b + 16, 16); pos16(b + 20, 1); pos16(b + 22, 1); pos32(b + 24, taxa);
    pos32(b + 28, taxa); pos16(b + 32, 1); pos16(b + 34, 8);
    memcpy(b + 36, "data", 4); pos32(b + 40, total);
    for (i = 0; i < qtd; i++) {
        int amostras = (int)(taxa * n[i].ms / 1000);
        for (k = 0; k < amostras; k++)
            b[p++] = n[i].hz == 0 ? 128 : (((k * 2 * n[i].hz / (int)taxa) & 1) ? 218 : 38);
    }
    return b;
}

static void carregar_som(void)
{
    static const Nota alarme[] = { {2000, 180}, {0, 120}, {2000, 180}, {0, 120}, {2000, 180}, {0, 60} };
    static const Nota ok[] = { {800, 150}, {0, 80}, {1200, 220}, {0, 40} };
    HMODULE core = LoadLibraryW(L"coredll.dll");
    if (core) {
        g_play = (PFN_PLAYSOUND)GetProcAddressW(core, L"PlaySoundW");
        g_vol = (PFN_WAVEVOL)GetProcAddressW(core, L"waveOutSetVolume");
    }
    g_som_alarme = gerar_wav(alarme, sizeof(alarme) / sizeof(alarme[0]));
    g_som_ok = gerar_wav(ok, sizeof(ok) / sizeof(ok[0]));
}

static void tocar(BYTE *wav)
{
    if (!g_play || !wav) return;
    if (g_vol) g_vol(0, 0xFFFFFFFF);                 /* volume no maximo */
    g_play((LPCWSTR)wav, NULL, SND_MEMORY | SND_ASYNC | SND_NODEFAULT);
}

/* estado vindo do host: bip=1 ha critico que apita; aid identifica o conjunto;
 * som=1 pode tocar agora (fora do horario de silencio). Host antigo sem 'bip':
 * vale o alarme da v2 (net=0). */
static int critico_ativo(char *aid, int *pode_tocar)
{
    int ativo, semdados;
    const char *b;
    EnterCriticalSection(&g_cs);
    semdados = (g_ncampos == 0) || (GetTickCount() - g_ultimo > SEM_DADOS_MS);
    b = val("bip");
    if (b[0] == '-') ativo = !semdados && strcmp(val("net"), "0") == 0;
    else ativo = !semdados && strcmp(b, "1") == 0;
    if (aid) { strncpy(aid, b[0] == '-' ? "net" : val("aid"), 7); aid[7] = 0; }
    if (pode_tocar) *pode_tocar = strcmp(val("som"), "1") == 0;
    LeaveCriticalSection(&g_cs);
    return ativo;
}

static int silenciado(void)
{
    char aid[8];
    return critico_ativo(aid, NULL) && strcmp(aid, g_aid_sil) == 0;
}

static void verificar_alarme(void)
{
    char aid[8];
    int som = 0, ativo = critico_ativo(aid, &som);
    if (ativo) {
        if (strcmp(aid, g_aid_sil) != 0 && som && GetTickCount() - g_ultimo_bip >= ALARME_MS) {
            tocar(g_som_alarme);
            g_ultimo_bip = GetTickCount();
        }
    } else if (g_bip_ant) {                           /* os criticos acabaram */
        g_aid_sil[0] = 0;
        g_ultimo_bip = 0;
        if (som) tocar(g_som_ok);
    }
    g_bip_ant = ativo;
}

/* toque: reconhece o conjunto de criticos atual (para de apitar ate surgir outro) */
static void reconhecer(void)
{
    char aid[8];
    if (critico_ativo(aid, NULL)) strcpy(g_aid_sil, aid);
}

/* ------------------------------------------------------------ desenho
 * Tema "sensor panel" Neon: paineis chanfrados, arcos e barras segmentados.
 * Coordenadas iguais ao mockup docs/telas-mio-v2.html (320x240). */

/* ---- cores */
static COLORREF mix(COLORREF x, COLORREF y, int t)          /* t = 0..256 */
{
    return RGB(GetRValue(x) + (GetRValue(y) - GetRValue(x)) * t / 256,
               GetGValue(x) + (GetGValue(y) - GetGValue(x)) * t / 256,
               GetBValue(x) + (GetBValue(y) - GetBValue(x)) * t / 256);
}

static COLORREF grad(int t)                                  /* a -> b -> c */
{
    if (t < 128) return mix(g_pal->a, g_pal->b, t * 2);
    return mix(g_pal->b, g_pal->c, (t - 128) * 2);
}

/* ---- primitivas */
static void ret(HDC dc, int x, int y, int w, int h, COLORREF c)
{
    RECT r;
    HBRUSH b = CreateSolidBrush(c);
    SetRect(&r, x, y, x + w, y + h);
    FillRect(dc, &r, b);
    DeleteObject(b);
}

static void poli(HDC dc, POINT *p, int n, COLORREF fundo, COLORREF borda)
{
    HBRUSH b = CreateSolidBrush(fundo);
    HPEN pen = CreatePen(PS_SOLID, 1, borda);
    HGDIOBJ ob = SelectObject(dc, b), op = SelectObject(dc, pen);
    Polygon(dc, p, n);
    SelectObject(dc, ob); SelectObject(dc, op);
    DeleteObject(b); DeleteObject(pen);
}

static void circulo(HDC dc, int cx, int cy, int r, COLORREF c)
{
    HBRUSH b = CreateSolidBrush(c);
    HPEN pen = CreatePen(PS_SOLID, 1, c);
    HGDIOBJ ob = SelectObject(dc, b), op = SelectObject(dc, pen);
    Ellipse(dc, cx - r, cy - r, cx + r + 1, cy + r + 1);
    SelectObject(dc, ob); SelectObject(dc, op);
    DeleteObject(b); DeleteObject(pen);
}

/* ---- texto: fonte de pixel Terminus embutida (fontes_pixel.h, gerada por
 * fontes/gerar_fontes.py). Nitida na tela 320x240, sem depender das fontes da ROM.
 * "tam" continua sendo o tamanho Tahoma do desenho; y = linha de base, como no SVG. */
#define ESQ 0
#define MEIO 1
#define DIR 2
#include "fontes_pixel.h"

static const GlifoPx *glifo_px(const FontePx *f, WCHAR c)
{
    int a = 0, b = f->n - 1, m;
    while (a <= b) {
        m = (a + b) / 2;
        if (f->g[m].cp == c) return &f->g[m];
        if (f->g[m].cp < c) a = m + 1; else b = m - 1;
    }
    return c == L'?' ? &f->g[0] : glifo_px(f, L'?');
}

static int largura_px(const FontePx *f, int esc, const WCHAR *s)
{
    int t = 0;
    for (; *s; s++) {
        const GlifoPx *g = glifo_px(f, *s);
        t += (g->w ? g->w : f->espaco) + (s[1] ? f->gap : 0);
    }
    return t * esc;
}

static int txt(HDC dc, int tam, int neg, COLORREF cor, int x, int y, const WCHAR *s, int alinh)
{
    const FontePx *f;
    int esc, larg, topo;
    HBRUSH br;
    HGDIOBJ ob;
    fpx_escolher(tam, neg, &f, &esc);
    larg = largura_px(f, esc, s);
    if (alinh == MEIO) x -= larg / 2;
    else if (alinh == DIR) x -= larg;
    topo = y - f->base * esc;
    br = CreateSolidBrush(cor);
    ob = SelectObject(dc, br);
    for (; *s; s++) {
        const GlifoPx *g = glifo_px(f, *s);
        const unsigned char *d = f->d + g->off;
        int nb = (g->w + 7) / 8, r, c, ini;
        for (r = 0; r < f->alt; r++, d += nb) {
            /* pinta cada trecho continuo da linha com um PatBlt (bem menos chamadas
             * que SetPixel) */
            for (c = 0; c < g->w; ) {
                if (!(d[c >> 3] & (0x80 >> (c & 7)))) { c++; continue; }
                ini = c;
                while (c < g->w && (d[c >> 3] & (0x80 >> (c & 7)))) c++;
                PatBlt(dc, x + ini * esc, topo + r * esc, (c - ini) * esc, esc, PATCOPY);
            }
        }
        x += ((g->w ? g->w : f->espaco) + f->gap) * esc;
    }
    SelectObject(dc, ob);
    DeleteObject(br);
    return larg;
}

static int txta(HDC dc, int tam, int neg, COLORREF cor, int x, int y, const char *s, int alinh)
{
    WCHAR w[128];
    MultiByteToWideChar(CP_ACP, 0, s, -1, w, 128);
    w[127] = 0;
    return txt(dc, tam, neg, cor, x, y, w, alinh);
}

/* ---- dados */
static double num(const char *s)                 /* "94,2" -> 94.2 ; "-" -> -1 */
{
    char b[32];
    int i;
    if (!s[0] || s[0] == '-') return -1;
    for (i = 0; s[i] && i < 31; i++) b[i] = (s[i] == ',') ? '.' : s[i];
    b[i] = 0;
    return atof(b);
}

/* parte n (0..) de "a;b;c" em dest */
static void parte(const char *s, int n, char *dest, int tam)
{
    int i = 0;
    while (n > 0 && *s) { if (*s++ == ';') n--; }
    while (*s && *s != ';' && i < tam - 1) dest[i++] = *s++;
    dest[i] = 0;
}

static int tem_alerta(void)
{
    const char *a = val("alr");
    return a[0] && strcmp(a, "-") != 0;
}

/* 0 nada, 1 aviso (ambar), 2 critico (vermelho). Host sem 'alv': todo alerta e critico. */
static int nivel_alerta(void)
{
    const char *v = val("alv");
    if (!tem_alerta()) return 0;
    if (v[0] == '-') return 2;
    return strchr(v, '2') ? 2 : 1;
}

/* titulo fixo + valor recebido (ASCII); dest com 48 WCHAR */
static void titulo_com(WCHAR *dest, const WCHAR *fixo, const char *valor)
{
    int n;
    wcsncpy(dest, fixo, 40);
    dest[40] = 0;
    n = wcslen(dest);
    MultiByteToWideChar(CP_ACP, 0, valor, -1, dest + n, 47 - n);
    dest[47] = 0;
}

/* ---- elementos do tema */
static void painel(HDC dc, int x, int y, int w, int h, const WCHAR *tit, int t)
{
    POINT p[8];
    p[0].x = x + 6;     p[0].y = y;      p[1].x = x + w - 6; p[1].y = y;
    p[2].x = x + w;     p[2].y = y + 6;  p[3].x = x + w;     p[3].y = y + h - 6;
    p[4].x = x + w - 6; p[4].y = y + h;  p[5].x = x + 6;     p[5].y = y + h;
    p[6].x = x;         p[6].y = y + h - 6; p[7].x = x;      p[7].y = y + 6;
    poli(dc, p, 8, K_PAN, K_BORDA);
    ret(dc, x + w / 2 - w * 18 / 100, y + h - 2, w * 36 / 100, 2, mix(g_pal->b, g_pal->c, t));
    if (tit) {
        int cx = x + w / 2;
        int lw = txt(dc, 9, 1, K_TIT, cx, y + 13, tit, MEIO) / 2 + 4;
        ret(dc, cx - lw - 12, y + 9, 10, 1, g_pal->b);
        ret(dc, cx + lw + 2, y + 9, 10, 1, g_pal->b);
    }
}

/* arco de 270 graus, comecando embaixo a esquerda; frac = 0..1000 */
static void arco(HDC dc, int cx, int cy, int r, int larg, int frac, int n)
{
    int k, on = (frac * n + 500) / 1000;
    for (k = 0; k < n; k++) {
        double a0 = (135.0 + k * 270.0 / n + 1.0) * 3.14159265 / 180.0;
        double a1 = (135.0 + (k + 1) * 270.0 / n - 1.0) * 3.14159265 / 180.0;
        POINT p[4];
        COLORREF c = k < on ? grad(k * 256 / (n - 1)) : K_OFF;
        p[0].x = cx + (int)(r * cos(a0));          p[0].y = cy + (int)(r * sin(a0));
        p[1].x = cx + (int)(r * cos(a1));          p[1].y = cy + (int)(r * sin(a1));
        p[2].x = cx + (int)((r - larg) * cos(a1)); p[2].y = cy + (int)((r - larg) * sin(a1));
        p[3].x = cx + (int)((r - larg) * cos(a0)); p[3].y = cy + (int)((r - larg) * sin(a0));
        poli(dc, p, 4, c, c);
    }
}

/* barra em tracinhos; frac = 0..1000 */
static void barra(HDC dc, int x, int y, int w, int h, int frac, int n)
{
    int k, on = (frac * n + 500) / 1000, sw = (w - (n - 1)) / n;
    if (sw < 1) sw = 1;
    for (k = 0; k < n; k++)
        ret(dc, x + k * (sw + 1), y, sw, h, k < on ? grad(k * 256 / (n - 1)) : K_OFF);
}

static void tri(HDC dc, int x, int y, COLORREF c, int baixo)
{
    POINT p[3];
    p[0].x = x;     p[0].y = baixo ? y : y + 8;
    p[1].x = x + 8; p[1].y = baixo ? y : y + 8;
    p[2].x = x + 4; p[2].y = baixo ? y + 8 : y;
    poli(dc, p, 3, c, c);
}

/* ---- animacao: anime.bin ao lado do exe (gerado por device/anime/gerar_anime.py).
 * RGB565 com RLE; cada quadro e montado num DIB de 16 bits e copiado com um BitBlt.
 * Sem o arquivo, a tela de animacao simplesmente nao entra na rotacao. */
#define ID_TIMER_ANIM  4
#define ANIM_ALT_MAX   206
static unsigned char *g_anim = NULL;
static DWORD   g_atam = 0;
static int     g_aw, g_ah, g_an, g_aatraso, g_aquadro = 0, g_anime_na_tela = 0;
static unsigned short g_afundo;
static HDC     g_adc = NULL;
static unsigned short *g_abits = NULL;

static unsigned u16(const unsigned char *p) { return p[0] | (p[1] << 8); }
static DWORD u32(const unsigned char *p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((DWORD)p[3] << 24); }

static void anim_carregar(void)
{
    WCHAR cam[MAX_PATH], *b;
    HANDLE f;
    DWORD lido = 0;
    int i, ok;
    GetModuleFileNameW(NULL, cam, MAX_PATH);
    b = wcsrchr(cam, L'\\');
    if (!b) return;
    wcscpy(b + 1, L"anime.bin");
    f = CreateFileW(cam, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (f == INVALID_HANDLE_VALUE) return;
    g_atam = GetFileSize(f, NULL);
    if (g_atam > 16 && g_atam < 8 * 1024 * 1024 && (g_anim = malloc(g_atam)) != NULL)
        if (!ReadFile(f, g_anim, g_atam, &lido, NULL) || lido != g_atam) { free(g_anim); g_anim = NULL; }
    CloseHandle(f);
    if (!g_anim) return;
    g_aw = u16(g_anim + 4); g_ah = u16(g_anim + 6); g_an = u16(g_anim + 8);
    g_aatraso = u16(g_anim + 10); g_afundo = (unsigned short)u16(g_anim + 12);
    ok = memcmp(g_anim, "MIOA", 4) == 0 && g_aw > 0 && g_aw <= LARG - 12 && !(g_aw & 1)
         && g_ah > 0 && g_ah <= ANIM_ALT_MAX && g_an > 0 && 16 + 4 * (DWORD)g_an <= g_atam;
    for (i = 0; ok && i < g_an; i++) ok = u32(g_anim + 16 + 4 * i) < g_atam;
    if (!ok) { free(g_anim); g_anim = NULL; return; }
    if (g_aatraso < 40) g_aatraso = 40;
}

static void anim_preparar(HWND h)
{
    struct { BITMAPINFOHEADER h; DWORD m[3]; } bi;
    HDC s;
    HBITMAP bmp;
    if (!g_anim) return;
    memset(&bi, 0, sizeof(bi));
    bi.h.biSize = sizeof(BITMAPINFOHEADER);
    bi.h.biWidth = g_aw;
    bi.h.biHeight = g_ah;                      /* de baixo para cima (o mais compativel) */
    bi.h.biPlanes = 1;
    bi.h.biBitCount = 16;
    bi.h.biCompression = BI_BITFIELDS;
    bi.m[0] = 0xF800; bi.m[1] = 0x07E0; bi.m[2] = 0x001F;
    s = GetDC(h);
    g_adc = CreateCompatibleDC(s);
    bmp = CreateDIBSection(s, (BITMAPINFO *)&bi, DIB_RGB_COLORS, (void **)&g_abits, NULL, 0);
    ReleaseDC(h, s);
    if (!g_adc || !bmp || !g_abits) {               /* sem memoria: fica sem a tela */
        if (bmp) DeleteObject(bmp);
        if (g_adc) DeleteDC(g_adc);
        g_adc = NULL; g_abits = NULL;
        free(g_anim); g_anim = NULL;
        return;
    }
    SelectObject(g_adc, bmp);
}

static void anim_quadro(HDC dc)
{
    const unsigned char *p, *fim;
    unsigned short *lin;
    int x = 0, y = 0, n, i;
    if (!g_anim || !g_abits) return;
    for (i = 0; i < g_aw * g_ah; i++) g_abits[i] = g_afundo;
    p = g_anim + u32(g_anim + 16 + 4 * (g_aquadro % g_an));
    fim = g_anim + g_atam;
    lin = g_abits + (g_ah - 1) * g_aw;            /* linha 0 da imagem = ultima do DIB */
    while (y < g_ah && p < fim) {
        int b = *p++;
        n = (b & 0x7f) + 1;
        if (b & 0x80) {
            for (; n > 0 && y < g_ah && p + 2 <= fim; n--, p += 2) {
                lin[x] = (unsigned short)(p[0] | (p[1] << 8));
                if (++x == g_aw) { x = 0; if (++y < g_ah) lin -= g_aw; }
            }
            if (n > 0) break;                       /* arquivo truncado */
        } else {
            x += n;
            while (x >= g_aw && y < g_ah) { x -= g_aw; if (++y < g_ah) lin -= g_aw; }
        }
    }
    BitBlt(dc, (LARG - g_aw) / 2, 25 + (ANIM_ALT_MAX + 4 - g_ah) / 2, g_aw, g_ah, g_adc, 0, 0, SRCCOPY);
}

static int tem_tomada(void);
/* telas fixas + ENERGIA (so com o campo tm) + ANIME (so com anime.bin) */
static int n_base(void) { return N_TELAS + tem_tomada() + (g_anim ? 1 : 0); }

static void topo(HDC dc, const WCHAR *tit, int idx, int prog)
{
    POINT p[4];
    char hora[6];
    int i;
    ret(dc, 0, 0, LARG, ALT, K_BG);
    p[0].x = 96; p[0].y = 0; p[1].x = 224; p[1].y = 0; p[2].x = 214; p[2].y = 16; p[3].x = 106; p[3].y = 16;
    poli(dc, p, 4, K_ABA, K_BORDA);
    txt(dc, 10, 1, g_pal != &PAL_NEON ? g_pal->c : RGB(0xdf, 0xe2, 0xea), 160, 12, tit, MEIO);
    strncpy(hora, val("h"), 5);
    hora[5] = 0;
    txta(dc, 11, 1, K_TXT, 6, 12, hora, ESQ);
    for (i = 0; i < n_base(); i++) ret(dc, 40 + i * 7, 6, 5, 3, i == idx ? g_pal->b : K_OFF);
    ret(dc, 234, 7, 30, 2, g_pal->b);
    txt(dc, 13, 1, K_MUT, 314, 13, L"\x00D7", DIR);
    ret(dc, 0, 18, LARG, 1, K_OFF);
    ret(dc, 0, 18, prog, 1, g_pal->c);
}

/* ---- telas */
static void tela_internet(HDC dc, int prog)
{
    char s[64], gd[200];
    double wd;
    int frac;
    topo(dc, L"INTERNET", 0, prog);
    if (strcmp(val("wok"), "1") != 0) {
        painel(dc, 4, 23, 312, 213, L"INTERNET", 128);
        txt(dc, 16, 1, g_pal->a, 160, 120, L"sem dados do OPNsense", MEIO);
        txt(dc, 10, 0, K_MUT, 160, 142, L"o Zabbix n\x00E3o respondeu", MEIO);
        return;
    }
    /* download: arco em escala log 1..1000 Mbit/s */
    painel(dc, 4, 23, 154, 213, L"DOWNLOAD", 0);
    wd = num(val("wd"));
    frac = wd <= 1 ? 0 : (int)(log10(wd) / 3.0 * 1000);
    if (frac > 1000) frac = 1000;
    arco(dc, 81, 122, 66, 9, frac, 36);
    txta(dc, 28, 1, K_TXT, 81, 124, val("wd"), MEIO);
    txt(dc, 10, 1, g_pal->a, 81, 142, L"MBIT/S", MEIO);
    ret(dc, 30, 158, 102, 1, mix(g_pal->a, g_pal->b, 128));
    tri(dc, 44, 167, g_pal->c, 0);
    txt(dc, 10, 1, K_MUT, 57, 175, L"UP", ESQ);
    _snprintf(s, sizeof(s), "%s Mbit/s", val("wu"));
    txta(dc, 12, 1, K_TXT, 134, 175, s, DIR);
    txt(dc, 8, 0, K_MUT, 81, 196, L"1 \x00B7 10 \x00B7 100 \x00B7 1000", MEIO);
    _snprintf(s, sizeof(s), "pico 10 min  %s", val("wm"));
    txta(dc, 9, 0, K_MUT, 81, 220, s, MEIO);

    /* hoje */
    painel(dc, 162, 23, 154, 62, L"HOJE", 77);
    txta(dc, 19, 1, K_TXT, 239, 57, val("ht"), MEIO);
    tri(dc, 170, 69, g_pal->b, 1);
    txta(dc, 9, 1, g_pal->b, 181, 77, val("hd"), ESQ);
    tri(dc, 240, 69, g_pal->c, 0);
    txta(dc, 9, 1, g_pal->c, 251, 77, val("hu"), ESQ);

    /* mes */
    {
        WCHAR wt[32];
        int dia = atoi(val("dia")), nd = atoi(val("ndias"));
        MultiByteToWideChar(CP_ACP, 0, val("mes"), -1, wt, 32);
        wt[31] = 0;
        painel(dc, 162, 89, 154, 70, wt, 154);
        txta(dc, 19, 1, K_TXT, 239, 123, val("mt"), MEIO);
        barra(dc, 172, 133, 134, 6, nd > 0 ? dia * 1000 / nd : 0, 30);
        _snprintf(s, sizeof(s), "dia %d de %d", dia, nd);
        txta(dc, 9, 0, K_MUT, 239, 152, s, MEIO);
    }

    /* grafico 10 min: "d/u,d/u,..." com valores 0..99 */
    painel(dc, 162, 163, 154, 73, L"10 MIN", 230);
    strncpy(gd, val("wg"), sizeof(gd) - 1);
    gd[sizeof(gd) - 1] = 0;
    {
        POINT pd[24], pu[24];
        int n = 0, k;
        char *tok = gd;
        while (tok && *tok && n < 22) {
            char *virg = strchr(tok, ','), *barra_ = strchr(tok, '/');
            if (virg) *virg = 0;
            if (barra_) {
                *barra_ = 0;
                pd[n].y = atoi(tok);
                pu[n].y = atoi(barra_ + 1);
                n++;
            }
            tok = virg ? virg + 1 : NULL;
        }
        if (n >= 2) {
            POINT area[26];
            HPEN pen;
            HGDIOBJ op;
            int serie;
            for (k = 0; k < n; k++) {
                pd[k].x = pu[k].x = 170 + k * 138 / (n - 1);
                pd[k].y = 226 - pd[k].y * 46 / 100;
                pu[k].y = 226 - pu[k].y * 46 / 100;
            }
            for (serie = 0; serie < 2; serie++) {
                POINT *p = serie ? pu : pd;
                COLORREF c = serie ? g_pal->c : g_pal->b;
                area[0].x = 170; area[0].y = 226;
                for (k = 0; k < n; k++) area[k + 1] = p[k];
                area[n + 1].x = 308; area[n + 1].y = 226;
                poli(dc, area, n + 2, mix(K_PAN, c, 72), mix(K_PAN, c, 72));
                pen = CreatePen(PS_SOLID, 2, c);
                op = SelectObject(dc, pen);
                Polyline(dc, p, n);
                SelectObject(dc, op);
                DeleteObject(pen);
            }
        } else {
            txt(dc, 9, 0, K_MUT, 239, 210, L"juntando dados...", MEIO);
        }
    }
}

static void tela_servidor(HDC dc, int prog)
{
    char s[64], up[16];
    double ramu = num(val("ramu")), ramt = num(val("ramt")), png = num(val("png"));
    int cpu = atoi(val("cpu")), ram = atoi(val("ram")), dsk = atoi(val("dsk")), i;
    topo(dc, L"SERVIDOR \x00B7 PVE", 2, prog);

    painel(dc, 4, 23, 154, 152, L"CPU", 0);
    arco(dc, 81, 104, 58, 8, cpu * 10, 36);
    txta(dc, 28, 1, K_TXT, 78, 108, val("tmp"), MEIO);
    txt(dc, 10, 1, K_TXT, 98, 100, L"\x00B0" L"C", ESQ);
    _snprintf(s, sizeof(s), "%s %% LOAD", val("cpu"));
    txta(dc, 11, 1, g_pal->a, 81, 128, s, MEIO);
    _snprintf(s, sizeof(s), "%s \xB7 Proxmox", val("host"));
    txta(dc, 9, 0, K_MUT, 81, 162, s, MEIO);

    painel(dc, 162, 23, 154, 152, L"MEM\x00D3RIA", 102);
    arco(dc, 239, 104, 58, 8, ram * 10, 36);
    _snprintf(s, sizeof(s), "%.1f", ramu / 1024.0);
    for (i = 0; s[i]; i++) if (s[i] == '.') s[i] = ',';
    txta(dc, 26, 1, K_TXT, 239, 108, s, MEIO);
    _snprintf(s, sizeof(s), "%d %% USADA", ram);
    txta(dc, 11, 1, g_pal->b, 239, 128, s, MEIO);
    _snprintf(s, sizeof(s), "de %.1f GB", ramt / 1024.0);
    for (i = 0; s[i]; i++) if (s[i] == '.') s[i] = ',';
    txta(dc, 9, 0, K_MUT, 239, 162, s, MEIO);

    painel(dc, 4, 179, 154, 57, L"DISCO", 154);
    _snprintf(s, sizeof(s), "%d %%", dsk);
    txta(dc, 15, 1, K_TXT, 14, 208, s, ESQ);
    _snprintf(s, sizeof(s), "%.0f GB livres", num(val("dskl")));
    txta(dc, 9, 0, K_MUT, 148, 208, s, DIR);
    barra(dc, 14, 216, 134, 7, dsk * 10, 26);

    painel(dc, 162, 179, 74, 57, L"LIGADO", 205);
    strncpy(up, val("up"), sizeof(up) - 1);
    up[sizeof(up) - 1] = 0;
    { char *h = strchr(up, 'h'); if (h) h[1] = 0; }
    txta(dc, 13, 1, K_TXT, 199, 216, up, MEIO);

    painel(dc, 240, 179, 76, 57, L"PING", 256);
    if (png < 0) txt(dc, 13, 1, K_AL, 278, 216, L"falhou", MEIO);
    else {
        _snprintf(s, sizeof(s), "%.1f ms", png);
        for (i = 0; s[i]; i++) if (s[i] == '.') s[i] = ',';
        txta(dc, 13, 1, K_OK, 278, 216, s, MEIO);
    }
}

static void tela_maquinas(HDC dc, int prog)
{
    WCHAR tit[48];
    char chave[16], nome[32], rot[16], on[4], cpu[8], mem[16];
    int k, n = 0, alt;
    for (k = 1; k <= 6; k++) { sprintf(chave, "vm%d", k); if (val(chave)[0] != '-') n = k; }
    titulo_com(tit, L"M\x00C1QUINAS \x00B7 ", val("nvm"));
    topo(dc, tit, 3, prog);
    if (n == 0) { txt(dc, 14, 1, K_MUT, 160, 130, L"sem dados do Proxmox", MEIO); return; }
    alt = n > 5 ? 36 : 43;
    for (k = 0; k < n; k++) {
        int y = 23 + k * alt, ligada;
        sprintf(chave, "vm%d", k + 1);
        parte(val(chave), 0, nome, sizeof(nome));
        parte(val(chave), 1, rot, sizeof(rot));
        parte(val(chave), 2, on, sizeof(on));
        parte(val(chave), 3, cpu, sizeof(cpu));
        parte(val(chave), 4, mem, sizeof(mem));
        ligada = on[0] == '1';
        painel(dc, 4, y, 312, alt - 4, NULL, n > 1 ? k * 256 / (n - 1) : 0);
        circulo(dc, 17, y + (alt - 4) / 2, 4, ligada ? K_OK : K_OFF);
        txta(dc, 13, 1, ligada ? K_TXT : K_MUT, 28, y + 17, nome, ESQ);
        txta(dc, 9, 1, g_pal->b, 28, y + alt - 12, rot, ESQ);
        if (ligada) {
            int c = atoi(cpu) * 10;
            barra(dc, 160, y + 11, 96, 6, c < 20 ? 20 : c, 16);
            {
                char s[16];
                _snprintf(s, sizeof(s), "CPU %s", cpu);
                txta(dc, 9, 0, K_MUT, 160, y + alt - 12, s, ESQ);
            }
            txta(dc, 12, 1, K_TXT, 308, y + (alt - 4) / 2 + 5, mem, DIR);
        } else {
            txta(dc, 11, 0, K_MUT, 308, y + (alt - 4) / 2 + 5, mem, DIR);
        }
    }
}

static void tela_servicos(HDC dc, int prog)
{
    WCHAR tit[48];
    char chave[16], nome[32], on[4], ms[8], s[16];
    int k;
    titulo_com(tit, L"SERVI\x00C7OS \x00B7 ", val("nsv"));
    topo(dc, tit, 4, prog);
    for (k = 0; k < 9; k++) {
        int x = 4 + (k % 3) * 105, y = 23 + (k / 3) * 72, ok;
        sprintf(chave, "sv%d", k + 1);
        if (val(chave)[0] == '-') continue;
        parte(val(chave), 0, nome, sizeof(nome));
        parte(val(chave), 1, on, sizeof(on));
        parte(val(chave), 2, ms, sizeof(ms));
        ok = on[0] == '1';
        painel(dc, x, y, 101, 68, NULL, (k % 3) * 128);
        circulo(dc, x + 14, y + 18, 5, ok ? K_OK : K_AL);
        txta(dc, 12, 1, K_TXT, x + 24, y + 22, nome, ESQ);
        if (ok) { _snprintf(s, sizeof(s), "%s ms", ms); txta(dc, 15, 1, K_TXT, x + 50, y + 50, s, MEIO); }
        else txt(dc, 15, 1, K_AL, x + 50, y + 50, L"FORA", MEIO);
    }
}

/* ---- ajudantes das telas v3 */
static COLORREF cor_estado(int e) { return e == 1 ? K_OK : e == 0 ? K_AL : K_OFF; }

/* anel de estado: 1 ok, 0 falha, -1 desconhecido */
static void anel(HDC dc, int cx, int cy, int e)
{
    COLORREF c = cor_estado(e);
    circulo(dc, cx, cy, 8, c);
    circulo(dc, cx, cy, 6, mix(K_PAN, c, 64));
    circulo(dc, cx, cy, 3, c);
}

static int largura(HDC dc, int tam, int neg, const WCHAR *s)
{
    const FontePx *f;
    int esc;
    (void)dc;
    fpx_escolher(tam, neg, &f, &esc);
    return largura_px(f, esc, s);
}

/* pastilha de estado alinhada pela direita em xd */
static void pastilha(HDC dc, int xd, int y, const WCHAR *s, COLORREF c)
{
    POINT p[4];
    int w = largura(dc, 10, 1, s) + 16;
    p[0].x = xd - w; p[0].y = y; p[1].x = xd; p[1].y = y;
    p[2].x = xd; p[2].y = y + 17; p[3].x = xd - w; p[3].y = y + 17;
    poli(dc, p, 4, mix(K_PAN, c, 56), c);
    txt(dc, 10, 1, c, xd - w / 2, y + 13, s, MEIO);
}

static void traco(HDC dc, POINT *p, int n, COLORREF c, int larg)
{
    HPEN pen = CreatePen(PS_SOLID, larg, c);
    HGDIOBJ op = SelectObject(dc, pen);
    Polyline(dc, p, n);
    SelectObject(dc, op);
    DeleteObject(pen);
}

/* segundos -> "ha 40 s" / "ha 3 min" / "ha 2 h" (cp1252) */
static void idade(char *dest, int tam, long s)
{
    if (s < 0) _snprintf(dest, tam, "-");
    else if (s < 120) _snprintf(dest, tam, "h\xE1 %ld s", s);
    else if (s < 7200) _snprintf(dest, tam, "h\xE1 %ld min", s / 60);
    else _snprintf(dest, tam, "h\xE1 %ld h", s / 3600);
    dest[tam - 1] = 0;
}

/* "15057" -> "15.057" */
static void milhar(char *dest, int tam, const char *n)
{
    int len = strlen(n), i, j = 0;
    for (i = 0; i < len && j < tam - 2; i++) {
        dest[j++] = n[i];
        if ((len - i - 1) % 3 == 0 && i < len - 1) dest[j++] = '.';
    }
    dest[j] = 0;
}

static void virgula(char *s) { for (; *s; s++) if (*s == '.') *s = ','; }

/* ---- CONEXAO: diagnostico do host (campo cn = gw;dns;lat;per;nst;nlv;llat;lper) */
static void tela_conexao(HDC dc, int prog)
{
    static const int xs[4] = { 44, 124, 204, 284 };
    static const WCHAR *nomes[4] = { L"PVE", L"GATEWAY", L"INTERNET", L"DNS" };
    char cn[96], gw[4], dns[4], lat[12], per[8], nst[12], nlv[4], llat[8], lper[8], s[48];
    const WCHAR *titulo, *rotulo;
    COLORREF cor;
    int e[4], nv, k;
    double vlat, vper;
    strncpy(cn, val("cn"), sizeof(cn) - 1);
    cn[sizeof(cn) - 1] = 0;
    topo(dc, L"CONEX\x00C3O", 1, prog);
    if (cn[0] == '-') {
        painel(dc, 4, 23, 312, 213, L"CONEX\x00C3O", 128);
        txt(dc, 16, 1, g_pal->a, 160, 120, L"sem diagn\x00F3stico", MEIO);
        txt(dc, 10, 0, K_MUT, 160, 142, L"o host ainda n\x00E3o mandou", MEIO);
        return;
    }
    parte(cn, 0, gw, sizeof(gw));   parte(cn, 1, dns, sizeof(dns));
    parte(cn, 2, lat, sizeof(lat)); parte(cn, 3, per, sizeof(per));
    parte(cn, 4, nst, sizeof(nst)); parte(cn, 5, nlv, sizeof(nlv));
    parte(cn, 6, llat, sizeof(llat)); parte(cn, 7, lper, sizeof(lper));
    nv = atoi(nlv);
    e[0] = 1;
    e[1] = gw[0] == '1' ? 1 : 0;
    e[2] = e[1] != 1 ? -1 : (strcmp(val("net"), "0") == 0 ? 0 : 1);
    e[3] = e[2] != 1 ? -1 : (dns[0] == '1' ? 1 : 0);
    if (!strcmp(nst, "gw")) titulo = L"GATEWAY FORA";
    else if (!strcmp(nst, "net")) titulo = L"INTERNET FORA";
    else if (!strcmp(nst, "dns")) titulo = L"DNS FALHANDO";
    else if (!strcmp(nst, "perda")) titulo = L"PERDA DE PACOTES";
    else if (!strcmp(nst, "lat")) titulo = L"LAT\x00CANCIA ALTA";
    else titulo = L"INTERNET OK";
    cor = nv == 2 ? K_AL : nv == 1 ? K_AM : K_OK;
    rotulo = nv == 2 ? L"CR\x00CDTICO" : nv == 1 ? L"ALERTA" : L"OK";

    painel(dc, 4, 23, 312, 46, L"ESTADO", 0);
    txt(dc, 20, 1, K_TXT, 16, 57, titulo, ESQ);
    pastilha(dc, 306, 42, rotulo, cor);

    painel(dc, 4, 73, 312, 78, L"CAMINHO", 77);
    for (k = 0; k < 3; k++) {
        COLORREF c = (e[k] == 1 && e[k + 1] == 1) ? mix(K_OK, K_PAN, 90) : e[k + 1] == 0 ? K_AL : K_OFF;
        ret(dc, xs[k] + 10, 111, xs[k + 1] - xs[k] - 20, 2, c);
    }
    for (k = 0; k < 4; k++) {
        txt(dc, 9, 1, K_MUT, xs[k], 97, nomes[k], MEIO);
        anel(dc, xs[k], 112, e[k]);
    }
    txt(dc, 11, 1, K_TXT, xs[0], 139, L"local", MEIO);
    if (e[1] == 1) {
        _snprintf(s, sizeof(s), "%s ms", val("png"));
        virgula(s);
        txta(dc, 11, 1, K_TXT, xs[1], 139, s, MEIO);
    } else txt(dc, 11, 1, K_AL, xs[1], 139, L"sem resposta", MEIO);
    if (e[2] == 1) txt(dc, 11, 1, K_TXT, xs[2], 139, L"responde", MEIO);
    else if (e[2] == 0) txt(dc, 11, 1, K_AL, xs[2], 139, L"sem resposta", MEIO);
    else txt(dc, 11, 1, K_MUT, xs[2], 139, L"\x2013", MEIO);
    if (e[3] == 1) txt(dc, 11, 1, K_TXT, xs[3], 139, L"resolve", MEIO);
    else if (e[3] == 0) txt(dc, 11, 1, K_AM, xs[3], 139, L"falhou", MEIO);
    else txt(dc, 11, 1, K_MUT, xs[3], 139, L"\x2013", MEIO);

    vlat = num(lat);
    painel(dc, 4, 155, 101, 81, L"LAT\x00CANCIA", 0);
    if (vlat < 0) txt(dc, 26, 1, K_MUT, 52, 197, L"\x2013", DIR);
    else { _snprintf(s, sizeof(s), "%.0f", vlat); txta(dc, 26, 1, K_TXT, 52, 197, s, DIR); }
    txt(dc, 10, 1, g_pal->a, 56, 197, L"ms", ESQ);
    barra(dc, 14, 207, 81, 6, vlat < 0 ? 0 : (vlat >= 300 ? 1000 : (int)(vlat * 1000 / 300)), 14);
    _snprintf(s, sizeof(s), "limite %s", llat);
    txta(dc, 9, 0, K_MUT, 54, 228, s, MEIO);

    vper = num(per);
    painel(dc, 109, 155, 101, 81, L"PERDA", 128);
    if (vper < 0) txt(dc, 26, 1, K_MUT, 157, 197, L"\x2013", DIR);
    else { _snprintf(s, sizeof(s), "%.0f", vper); txta(dc, 26, 1, K_TXT, 157, 197, s, DIR); }
    txt(dc, 12, 1, g_pal->a, 161, 197, L"%", ESQ);
    barra(dc, 119, 207, 81, 6, vper < 0 ? 0 : (vper >= 100 ? 1000 : (int)(vper * 10)), 14);
    _snprintf(s, sizeof(s), "limite %s %%", lper);
    txta(dc, 9, 0, K_MUT, 159, 228, s, MEIO);

    painel(dc, 214, 155, 102, 81, L"DNS", 256);
    if (e[3] == 1) txt(dc, 22, 1, K_OK, 265, 197, L"OK", MEIO);
    else if (e[3] == 0) txt(dc, 22, 1, K_AM, 265, 197, L"FALHA", MEIO);
    else txt(dc, 22, 1, K_MUT, 265, 197, L"\x2013", MEIO);
    txt(dc, 9, 0, K_MUT, 265, 215, L"3 falhas = alerta", MEIO);
    txt(dc, 9, 0, K_MUT, 265, 228, L"n\x00E3o \x00E9 queda", MEIO);
}

/* ---- SEGURANCA: CrowdSec (campo cs = estado;bloqueados;novos24h;lista;idade_s) */
static void tela_seguranca(HDC dc, int prog)
{
    char cs[96], st[4], b[16], nn[16], l[16], idd[16], s[48];
    const WCHAR *estado, *l1, *l2;
    COLORREF cor;
    POINT esc[7];
    int ok;
    strncpy(cs, val("cs"), sizeof(cs) - 1);
    cs[sizeof(cs) - 1] = 0;
    topo(dc, L"SEGURAN\x00C7" L"A", 5, prog);
    parte(cs, 0, st, sizeof(st)); parte(cs, 1, b, sizeof(b)); parte(cs, 2, nn, sizeof(nn));
    parte(cs, 3, l, sizeof(l));   parte(cs, 4, idd, sizeof(idd));
    if (cs[0] == '-') { cor = K_MUT; estado = L"SEM CROWDSEC"; l1 = L"n\x00E3o configurado"; l2 = L"no host"; }
    else if (st[0] == '1') { cor = K_OK; estado = L"PROTEGIDO"; l1 = L"LAPI no ar"; l2 = L"s\x00F3 leitura"; }
    else if (st[0] == '0') { cor = K_AL; estado = L"PARADO"; l1 = L"LAPI fora do ar"; l2 = L"sem novas detec\x00E7\x00F5" L"es"; }
    else { cor = K_AM; estado = L"SEM LEITURA"; l1 = L"LAPI no ar"; l2 = L"chave ou rede falhou"; }
    ok = cs[0] != '-' && st[0] == '1';

    painel(dc, 4, 23, 154, 152, L"CROWDSEC", 0);
    esc[0].x = 81;  esc[0].y = 44;  esc[1].x = 111; esc[1].y = 55; esc[2].x = 111; esc[2].y = 84;
    esc[3].x = 81;  esc[3].y = 110; esc[4].x = 51;  esc[4].y = 84; esc[5].x = 51;  esc[5].y = 55;
    poli(dc, esc, 6, mix(K_PAN, cor, 52), cor);
    esc[6] = esc[0];
    traco(dc, esc, 7, cor, 2);
    if (ok) {
        POINT v[3];
        v[0].x = 67; v[0].y = 77; v[1].x = 77; v[1].y = 88; v[2].x = 96; v[2].y = 64;
        traco(dc, v, 3, cor, 4);
    } else txt(dc, 34, 1, cor, 81, 96, cs[0] == '-' ? L"?" : L"!", MEIO);
    txt(dc, wcslen(estado) > 10 ? 13 : 17, 1, cor, 81, 136, estado, MEIO);
    txt(dc, 9, 0, K_MUT, 81, 154, l1, MEIO);
    txt(dc, 9, 0, K_MUT, 81, 166, l2, MEIO);

    painel(dc, 162, 23, 154, 152, L"BLOQUEIOS", 102);
    if (ok) {
        txta(dc, 52, 1, K_TXT, 239, 98, b, MEIO);
        txt(dc, 9, 1, g_pal->a, 239, 118, atoi(b) == 1 ? L"IP BLOQUEADO AGORA" : L"IPS BLOQUEADOS AGORA", MEIO);
        ret(dc, 184, 128, 110, 1, mix(g_pal->a, g_pal->b, 128));
        txta(dc, 18, 1, K_TXT, 239, 150, nn, DIR);
        txt(dc, 10, 0, K_MUT, 244, 150, L"novos em 24 h", ESQ);
        txt(dc, 9, 0, K_MUT, 239, 166, L"detec\x00E7\x00F5" L"es locais e cscli", MEIO);
    } else {
        txt(dc, 34, 1, K_MUT, 239, 104, L"\x2013", MEIO);
        txt(dc, 10, 0, K_MUT, 239, 132, L"sem leitura agora", MEIO);
    }

    painel(dc, 4, 179, 154, 57, L"LISTA DA COMUNIDADE", 179);
    if (ok && l[0] && l[0] != '-') {
        milhar(s, sizeof(s), l);
        txta(dc, 17, 1, K_TXT, 81, 216, s, DIR);
        txt(dc, 10, 1, g_pal->b, 86, 216, L"IPs", ESQ);
    } else txt(dc, 15, 1, K_MUT, 81, 216, L"\x2013", MEIO);

    painel(dc, 162, 179, 154, 57, L"LEITURA", 256);
    if (idd[0]) { idade(s, sizeof(s), atol(idd)); txta(dc, 16, 1, K_TXT, 239, 216, s, MEIO); }
    else txt(dc, 15, 1, K_MUT, 239, 216, L"\x2013", MEIO);
}

/* ---- SISTEMA: serial, idade dos dados, fontes e ultimos eventos (ev = hh:mm,n,texto;...) */
static void fonte_linha(HDC dc, int y, const WCHAR *nome, int estado)
{
    /* estado: 1 em dia, 0 velho, 2 parado, -1 nao configurado */
    COLORREF c = estado == 1 ? K_OK : estado == 0 ? K_AM : estado == 2 ? K_AL : K_OFF;
    const WCHAR *t = estado == 1 ? L"em dia" : estado == 0 ? L"velho" : estado == 2 ? L"parado" : L"\x2013";
    circulo(dc, 176, y - 4, 3, c);
    txt(dc, 10, 0, K_TXT, 185, y, nome, ESQ);
    txt(dc, 9, 1, c, 306, y, t, DIR);
}

static void tela_sistema(HDC dc, int prog)
{
    char s[64], ev[200], *tok, *prox, old[48], cs = val("cs")[0];
    int k, y, n = 0;
    topo(dc, L"SISTEMA", 6, prog);

    painel(dc, 4, 23, 154, 104, L"USB SERIAL", 0);
    circulo(dc, 18, 48, 5, K_OK);
    txt(dc, 13, 1, K_TXT, 29, 52, L"CONECTADO", ESQ);
    _snprintf(s, sizeof(s), "%S \xB7 115200", g_porta);
    txta(dc, 9, 0, K_MUT, 14, 68, s, ESQ);
    for (k = 0; k < 3; k++) {
        static const WCHAR *rot[3] = { L"linhas recebidas", L"sinais enviados", L"\x00FAltimo erro" };
        y = 88 + k * 14;
        if (k == 0) _snprintf(s, sizeof(s), "%lu", (unsigned long)g_linhas);
        else if (k == 1) _snprintf(s, sizeof(s), "%lu", (unsigned long)g_sinais);
        else if (g_err) _snprintf(s, sizeof(s), "c\xF3" "digo %lu", (unsigned long)g_err);
        else _snprintf(s, sizeof(s), "nenhum");
        txt(dc, 9, 0, K_MUT, 14, y, rot[k], ESQ);
        txta(dc, 10, 1, K_TXT, 148, y, s, DIR);
    }

    painel(dc, 162, 23, 154, 104, L"DADOS", 102);
    idade(s, sizeof(s), (long)((GetTickCount() - g_ultimo) / 1000));
    txta(dc, 20, 1, K_TXT, 239, 56, s, MEIO);
    txt(dc, 9, 0, K_MUT, 239, 69, L"\x00FAltima linha do pve", MEIO);
    strncpy(old, val("old"), sizeof(old) - 1);
    old[sizeof(old) - 1] = 0;
    fonte_linha(dc, 88, L"Proxmox", strstr(old, "pve") ? 0 : 1);
    fonte_linha(dc, 102, L"Zabbix", (strstr(old, "zabbix") || strcmp(val("wok"), "1") != 0) ? 0 : 1);
    fonte_linha(dc, 116, L"CrowdSec", cs == '-' ? -1 : cs == '0' ? 2 : (cs == 'e' || strstr(old, "crowdsec")) ? 0 : 1);

    painel(dc, 4, 131, 312, 105, L"\x00DALTIMOS EVENTOS", 205);
    strncpy(ev, val("ev"), sizeof(ev) - 1);
    ev[sizeof(ev) - 1] = 0;
    y = 156;
    for (tok = ev; ev[0] != '-' && tok && *tok && n < 4; tok = prox, n++) {
        char hora[8], niv[4], texto[40];
        COLORREF c;
        prox = strchr(tok, ';');
        if (prox) *prox++ = 0;
        {   /* "hh:mm,n,texto" -> troca ',' por ';' para usar parte() */
            char *q;
            for (q = tok; *q; q++) if (*q == ',') *q = ';';
        }
        parte(tok, 0, hora, sizeof(hora));
        parte(tok, 1, niv, sizeof(niv));
        parte(tok, 2, texto, sizeof(texto));
        c = niv[0] == '2' ? K_AL : niv[0] == '1' ? K_AM : K_MUT;
        txta(dc, 10, 1, K_MUT, 14, y, hora, ESQ);
        ret(dc, 46, y - 9, 3, 11, c);
        txta(dc, 11, 1, K_TXT, 55, y, texto, ESQ);
        txt(dc, 8, 1, c, 306, y, niv[0] == '2' ? L"CR\x00CDTICO" : niv[0] == '1' ? L"ALERTA" : L"INFO", DIR);
        y += 18;
    }
    if (n == 0) txt(dc, 10, 0, K_MUT, 160, 180, L"nenhum evento ainda", MEIO);
    _snprintf(s, sizeof(s), "MioDash %S \xB7 host %s", VERSAO, val("ver"));
    txta(dc, 8, 0, K_MUT, 160, 231, s, MEIO);
}

static void tela_alerta(HDC dc, int prog)
{
    char lista[200], niveis[64], nv[4], *tok, *p;
    const WCHAR *rodape;
    int n = 0, y, i = 0, crit = nivel_alerta() == 2;
    topo(dc, crit ? L"CR\x00CDTICO" : L"ALERTA", -1, prog);
    painel(dc, 4, 23, 312, 213, L"PROBLEMAS", 128);
    strncpy(lista, val("alr"), sizeof(lista) - 1);
    lista[sizeof(lista) - 1] = 0;
    strncpy(niveis, val("alv"), sizeof(niveis) - 1);
    niveis[sizeof(niveis) - 1] = 0;
    for (p = lista; *p; p++) if (*p == ';') n++;
    n++;
    /* rodape em y=226: as linhas terminam ate y=212 para nao encostar nele */
    if (n <= 2) {
        arco(dc, 160, 92, 42, 7, 1000, 28);
        txt(dc, 34, 1, RGB(255, 255, 255), 160, 106, L"!", MEIO);
        y = 146;
    } else y = 34;
    for (tok = lista; tok && *tok && y <= 182; tok = p, i++) {
        p = strchr(tok, ';');
        if (p) *p++ = 0;
        parte(niveis, i, nv, sizeof(nv));
        painel(dc, 14, y, 292, 30, NULL, 128);
        ret(dc, 15, y + 6, 3, 18, (nv[0] == '1') ? K_AM : K_AL);   /* sem 'alv' = critico */
        txta(dc, 13, 1, K_TXT, 26, y + 20, tok, ESQ);
        y += 36;
    }
    if (critico_ativo(NULL, NULL))
        rodape = silenciado() ? L"alarme reconhecido"
               : strcmp(val("som"), "1") != 0 ? L"sil\x00EAncio (23h \x00E0s 7h)"
               : L"toque para reconhecer e silenciar";
    else rodape = L"aviso sem som";
    txt(dc, 10, 0, g_pal->c, 160, 226, rodape, MEIO);
}

static void tela_sem_dados(HDC dc)
{
    char s[96];
    topo(dc, L"MIO DASHBOARD", -1, 0);
    painel(dc, 4, 23, 312, 213, L"AGUARDANDO", 128);
    txt(dc, 22, 1, g_pal->a, 160, 92, L"SEM DADOS", MEIO);
    _snprintf(s, sizeof(s), "%s - %S", g_status, g_porta);
    txta(dc, 11, 0, K_MUT, 160, 118, s, MEIO);
    _snprintf(s, sizeof(s), "rx %lu  tx %lu  erro %lu",
              (unsigned long)g_rx, (unsigned long)g_tx, (unsigned long)g_err);
    txta(dc, 11, 1, K_TXT, 160, 142, s, MEIO);
    if (g_fechado[0]) {
        _snprintf(s, sizeof(s), "fechei: %s", g_fechado);
        txta(dc, 10, 0, g_pal->c, 160, 164, s, MEIO);
    }
    txt(dc, 10, 0, K_MUT, 160, 214, L"toque no \x00D7 para sair", MEIO);
}

/* ---- ENERGIA: tomada Tuya (tm = te;tw;tv;ta;to;tkd;tkm;ted;tem;teh;hist). So aparece com o campo tm. */

static void valor_euro(HDC dc, int x, int y, int tam, const char *v)
{
    char b[24];
    strncpy(b, v, sizeof(b) - 1);
    b[sizeof(b) - 1] = 0;
    virgula(b);
    txta(dc, tam, 1, K_TXT, x - 4, y, b, DIR);
    txt(dc, tam * 2 / 3, 1, g_pal->a, x, y, L"\x20AC", ESQ);
}

static void tela_energia(HDC dc, int prog)
{
    char tm[220], te[4], w[12], v[12], a[12], on[4], kd[16], km[16], ed[16], em[16], eh[16], hist[100], s[48];
    int ok;
    strncpy(tm, val("tm"), sizeof(tm) - 1);
    tm[sizeof(tm) - 1] = 0;
    parte(tm, 0, te, sizeof(te)); parte(tm, 1, w, sizeof(w));   parte(tm, 2, v, sizeof(v));
    parte(tm, 3, a, sizeof(a));   parte(tm, 4, on, sizeof(on)); parte(tm, 5, kd, sizeof(kd));
    parte(tm, 6, km, sizeof(km)); parte(tm, 7, ed, sizeof(ed)); parte(tm, 8, em, sizeof(em));
    parte(tm, 9, eh, sizeof(eh)); parte(tm, 10, hist, sizeof(hist));
    topo(dc, L"ENERGIA", N_TELAS, prog);
    ok = te[0] == '1';

    /* agora */
    painel(dc, 4, 23, 154, 110, L"AGORA", 0);
    if (ok) {
        txta(dc, 30, 1, K_TXT, 81, 76, w, MEIO);
        txt(dc, 10, 1, g_pal->a, 81, 92, L"WATTS", MEIO);
        strncpy(s, eh, sizeof(s) - 1); s[sizeof(s) - 1] = 0; virgula(s);
        strncat(s, " \x80/h", sizeof(s) - strlen(s) - 1);        /* 0x80 = euro no cp1252 */
        txta(dc, 11, 1, g_pal->b, 81, 108, s, MEIO);
        _snprintf(s, sizeof(s), "%s V  %s A", v, a);
        virgula(s);
        txta(dc, 9, 0, K_MUT, 81, 125, s, MEIO);
        txt(dc, 9, 1, on[0] == '1' ? K_OK : K_MUT, 150, 38, on[0] == '1' ? L"LIGADA" : L"DESLIGADA", DIR);
    } else {
        txt(dc, 34, 1, te[0] == '0' ? K_AM : K_MUT, 81, 82, L"\x2013", MEIO);
        txt(dc, 10, 1, te[0] == '0' ? K_AM : K_MUT, 81, 104,
            te[0] == '0' ? L"SEM RESPOSTA" : L"SEM LEITURA", MEIO);
        txt(dc, 9, 0, K_MUT, 81, 120, te[0] == '0' ? L"tomada fora da rede?" : L"chave ou biblioteca", MEIO);
    }

    /* hoje */
    painel(dc, 162, 23, 154, 110, L"HOJE", 102);
    valor_euro(dc, 239, 84, 26, ed);
    strncpy(s, kd, sizeof(s) - 6); s[sizeof(s) - 6] = 0; virgula(s); strcat(s, " kWh");
    txta(dc, 11, 1, g_pal->b, 239, 108, s, MEIO);

    /* mes */
    painel(dc, 4, 137, 154, 99, L"M\x00CA" L"S", 179);
    valor_euro(dc, 81, 190, 24, em);
    strncpy(s, km, sizeof(s) - 6); s[sizeof(s) - 6] = 0; virgula(s); strcat(s, " kWh");
    txta(dc, 11, 1, g_pal->b, 81, 212, s, MEIO);

    /* ultima hora: 12 barras de 5 min (W) */
    painel(dc, 162, 137, 154, 99, L"\x00DALTIMA HORA", 256);
    {
        int vals[12], n = 0, k, maior = 0;
        char *tok = hist;
        while (tok && *tok && n < 12) {
            char *virg = strchr(tok, ',');
            if (virg) *virg = 0;
            vals[n++] = (tok[0] == '-') ? -1 : atoi(tok);
            tok = virg ? virg + 1 : NULL;
        }
        for (k = 0; k < n; k++) if (vals[k] > maior) maior = vals[k];
        if (n == 0 || maior < 0) {
            txt(dc, 9, 0, K_MUT, 239, 192, L"juntando dados...", MEIO);
        } else {
            for (k = 0; k < n; k++) {
                int x = 172 + k * 11, h;
                if (vals[k] < 0) { ret(dc, x, 224, 8, 1, K_OFF); continue; }
                h = maior > 0 ? vals[k] * 52 / maior : 0;
                if (h < 1) h = 1;
                ret(dc, x, 225 - h, 8, h, k == n - 1 ? g_pal->b : mix(K_PAN, g_pal->b, 150));
            }
            _snprintf(s, sizeof(s), "pico %d W", maior);
            txta(dc, 8, 0, K_MUT, 308, 166, s, DIR);
        }
    }
}

static int tem_tomada(void) { const char *t = val("tm"); return t[0] && t[0] != '-' ? 1 : 0; }

/* ANIME: so ela dancando, sem dados (a animacao roda no seu proprio timer) */
static void tela_anime(HDC dc, int prog)
{
    topo(dc, L"ANIME", N_TELAS + tem_tomada(), prog);
    painel(dc, 4, 23, 312, 213, NULL, 128);
    anim_quadro(dc);
}

static int n_telas(void) { return tem_alerta() ? n_base() + 1 : n_base(); }

static DWORD rotacao_ms(void)
{
    int s;
    EnterCriticalSection(&g_cs);
    s = atoi(val("rot"));
    LeaveCriticalSection(&g_cs);
    if (s < 5 || s > 600) s = ROTACAO_PADRAO;
    return (DWORD)s * 1000;
}

static void desenhar(HDC dc)
{
    int semdados, prog;
    DWORD agora = GetTickCount();
    EnterCriticalSection(&g_cs);
    semdados = (g_ncampos == 0) || (agora - g_ultimo > SEM_DADOS_MS);
    {
        int nv = semdados ? 0 : nivel_alerta();
        g_pal = nv == 2 ? &PAL_ALERTA : nv == 1 ? &PAL_AVISO : &PAL_NEON;
    }
    prog = (int)((agora - g_inicio) * LARG / rotacao_ms());
    if (prog > LARG) prog = LARG;
    g_anime_na_tela = !semdados && g_anim && g_vista % n_telas() == N_TELAS + tem_tomada();
    if (semdados) tela_sem_dados(dc);
    else if (g_anime_na_tela) tela_anime(dc, prog);
    else if (tem_tomada() && g_vista % n_telas() == N_TELAS) tela_energia(dc, prog);
    else switch (g_vista % n_telas()) {
        case 0: tela_internet(dc, prog); break;
        case 1: tela_conexao(dc, prog); break;
        case 2: tela_servidor(dc, prog); break;
        case 3: tela_maquinas(dc, prog); break;
        case 4: tela_servicos(dc, prog); break;
        case 5: tela_seguranca(dc, prog); break;
        case 6: tela_sistema(dc, prog); break;
        default: tela_alerta(dc, prog); break;
    }
    LeaveCriticalSection(&g_cs);
}

/* ------------------------------------------------------------ janela */
static void proxima_tela(HWND h)
{
    EnterCriticalSection(&g_cs);
    g_vista = (g_vista + 1) % n_telas();
    LeaveCriticalSection(&g_cs);
    g_inicio = GetTickCount();                         /* reinicia a contagem */
    InvalidateRect(h, NULL, FALSE);
}

static LRESULT CALLBACK WndProc(HWND h, UINT m, WPARAM w, LPARAM l)
{
    switch (m) {
    case WM_CREATE:
        g_inicio = GetTickCount();
        SetTimer(h, ID_TIMER_PROG, PROG_MS, NULL);
        SetTimer(h, ID_TIMER_IDLE, 10000, NULL);
        anim_preparar(h);
        if (g_anim) SetTimer(h, ID_TIMER_ANIM, g_aatraso, NULL);
        return 0;
    case WM_TIMER:
        if (w == ID_TIMER_PROG) {
            verificar_alarme();
            if (GetTickCount() - g_inicio >= rotacao_ms()) proxima_tela(h);
            else InvalidateRect(h, NULL, FALSE);
        }
        else if (w == ID_TIMER_ANIM) {
            if (g_anime_na_tela) {                /* so o retangulo dela, direto na tela */
                HDC d = GetDC(h);
                g_aquadro = (g_aquadro + 1) % g_an;
                anim_quadro(d);
                ReleaseDC(h, d);
            }
        }
        else SystemIdleTimerReset();             /* mantem tela/backlight ligados */
        return 0;
    case WM_DADOS:
        InvalidateRect(h, NULL, FALSE);
        return 0;
    case WM_LBUTTONDOWN: {
        RECT rc;
        int x = LOWORD(l), y = HIWORD(l);
        GetClientRect(h, &rc);
        if (x > rc.right - 40 && y < 40) { DestroyWindow(h); return 0; }
        reconhecer();                                 /* toque reconhece o critico atual */
        proxima_tela(h);
        return 0;
    }
    case WM_PAINT: {
        PAINTSTRUCT ps;
        RECT rc;
        HDC dc = BeginPaint(h, &ps), mem;
        HBITMAP bmp, antigo;
        GetClientRect(h, &rc);
        /* desenha fora da tela e copia de uma vez: evita piscar */
        mem = CreateCompatibleDC(dc);
        bmp = CreateCompatibleBitmap(dc, rc.right, rc.bottom);
        antigo = (HBITMAP)SelectObject(mem, bmp);
        desenhar(mem);
        BitBlt(dc, 0, 0, rc.right, rc.bottom, mem, 0, 0, SRCCOPY);
        SelectObject(mem, antigo);
        DeleteObject(bmp);
        DeleteDC(mem);
        EndPaint(h, &ps);
        return 0;
    }
    case WM_ERASEBKGND:
        return 1;
    case WM_DESTROY:
        g_rodando = 0;
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPWSTR cmd, int show)
{
    WNDCLASSW wc;
    MSG msg;
    HANDLE th;
    (void)prev; (void)show;

    {   /* instancia unica: so um MioDash pode ter a COM aberta */
        HWND outro = FindWindowW(L"MioDash", NULL);
        if (outro) {
            SetForegroundWindow(outro);
            return 0;
        }
    }
    /* O WinCE abre o repllog.exe (ActiveSync) quando o cabo USB e ligado e
     * ele toma a COM9. Cancela esse agendamento (vale ate um hard reset). */
    cancelar_repllog_automatico();

    if (cmd && cmd[0]) {                      /* porta pela linha de comando */
        wcsncpy(g_porta, cmd, 15);
        g_porta[15] = 0;
    }
    InitializeCriticalSection(&g_cs);
    carregar_som();
    anim_carregar();

    memset(&wc, 0, sizeof(wc));
    wc.lpfnWndProc = WndProc;
    wc.hInstance = inst;
    wc.lpszClassName = L"MioDash";
    RegisterClassW(&wc);

    g_hwnd = CreateWindowExW(WS_EX_TOPMOST, L"MioDash", L"MioDash", WS_VISIBLE | WS_POPUP,
                             0, 0, GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN),
                             NULL, NULL, inst, NULL);
    if (!g_hwnd) return 1;

    th = CreateThread(NULL, 0, leitor, NULL, 0, NULL);
    if (th) CloseHandle(th);

    while (GetMessageW(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    Sleep(1200);                              /* deixa a thread fechar a porta */
    return 0;
}
