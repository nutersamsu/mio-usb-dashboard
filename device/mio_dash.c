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
 * Tema "sensor panel" Neon, 5 telas (internet, servidor, maquinas, servicos, alerta).
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
static const Paleta *g_pal = &PAL_NEON;

typedef struct { char k[12]; char v[200]; } Campo;

static Campo   g_campos[MAX_CAMPOS];
static int     g_ncampos = 0;
static CRITICAL_SECTION g_cs;
static DWORD   g_ultimo = 0;          /* GetTickCount da ultima linha valida */
static int     g_vista = 0;           /* posicao na rotacao: 0 internet .. 4 alerta */
static DWORD   g_inicio = 0;          /* GetTickCount de quando a tela atual comecou */
static HWND    g_hwnd;
static WCHAR   g_porta[16] = L"COM9:";
static volatile int g_rodando = 1;
static char    g_status[64] = "abrindo porta";
/* diagnostico da serial: bytes recebidos/enviados e ultimo erro */
static volatile DWORD g_rx = 0, g_tx = 0, g_err = 0;

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
                if (WriteFile(h, ping, n, &escritos, NULL)) g_tx += escritos;
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
static int   g_silenciado = 0, g_net_ant = 1;
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

/* estado vindo do host: internet fora (net=0) e se pode tocar (som=1) */
static int internet_fora(int *pode_tocar)
{
    int fora, semdados;
    EnterCriticalSection(&g_cs);
    semdados = (g_ncampos == 0) || (GetTickCount() - g_ultimo > SEM_DADOS_MS);
    fora = !semdados && strcmp(val("net"), "0") == 0;
    if (pode_tocar) *pode_tocar = strcmp(val("som"), "1") == 0;
    LeaveCriticalSection(&g_cs);
    return fora;
}

static void verificar_alarme(void)
{
    int som = 0, fora = internet_fora(&som);
    if (fora) {
        if (!g_silenciado && som && GetTickCount() - g_ultimo_bip >= ALARME_MS) {
            tocar(g_som_alarme);
            g_ultimo_bip = GetTickCount();
        }
    } else if (!g_net_ant) {                          /* a internet voltou */
        g_silenciado = 0;
        g_ultimo_bip = 0;
        if (som) tocar(g_som_ok);
    }
    g_net_ant = !fora;
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

/* ---- texto (fontes Tahoma em cache; y = linha de base, como no SVG) */
#define ESQ 0
#define MEIO 1
#define DIR 2
static HFONT g_fonte[24];
static int   g_ftam[24], g_fneg[24], g_nfontes = 0;

static HFONT fonte(int tam, int negrito)
{
    int i;
    LOGFONTW lf;
    for (i = 0; i < g_nfontes; i++)
        if (g_ftam[i] == tam && g_fneg[i] == negrito) return g_fonte[i];
    memset(&lf, 0, sizeof(lf));
    lf.lfHeight = -tam;
    lf.lfWeight = negrito ? FW_BOLD : FW_NORMAL;
    lf.lfQuality = ANTIALIASED_QUALITY;
    wcscpy(lf.lfFaceName, L"Tahoma");
    if (g_nfontes == 24) return g_fonte[23];
    g_fonte[g_nfontes] = CreateFontIndirectW(&lf);
    g_ftam[g_nfontes] = tam;
    g_fneg[g_nfontes] = negrito;
    return g_fonte[g_nfontes++];
}

static int txt(HDC dc, int tam, int neg, COLORREF cor, int x, int y, const WCHAR *s, int alinh)
{
    TEXTMETRICW tm;
    SIZE sz;
    int n = wcslen(s);
    SelectObject(dc, fonte(tam, neg));
    GetTextMetricsW(dc, &tm);
    GetTextExtentPoint32W(dc, s, n, &sz);
    if (alinh == MEIO) x -= sz.cx / 2;
    else if (alinh == DIR) x -= sz.cx;
    SetTextColor(dc, cor);
    SetBkMode(dc, TRANSPARENT);
    ExtTextOutW(dc, x, y - tm.tmAscent, 0, NULL, s, n, NULL);
    return sz.cx;
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

static void topo(HDC dc, const WCHAR *tit, int idx, int prog)
{
    POINT p[4];
    char hora[6];
    int i;
    ret(dc, 0, 0, LARG, ALT, K_BG);
    p[0].x = 96; p[0].y = 0; p[1].x = 224; p[1].y = 0; p[2].x = 214; p[2].y = 16; p[3].x = 106; p[3].y = 16;
    poli(dc, p, 4, K_ABA, K_BORDA);
    txt(dc, 10, 1, g_pal == &PAL_ALERTA ? g_pal->c : RGB(0xdf, 0xe2, 0xea), 160, 12, tit, MEIO);
    strncpy(hora, val("h"), 5);
    hora[5] = 0;
    txta(dc, 11, 1, K_TXT, 6, 12, hora, ESQ);
    for (i = 0; i < 4; i++) ret(dc, 40 + i * 9, 6, 6, 3, i == idx ? g_pal->b : K_OFF);
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
    topo(dc, L"SERVIDOR \x00B7 PVE", 1, prog);

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
    topo(dc, tit, 2, prog);
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
    topo(dc, tit, 3, prog);
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

static void tela_alerta(HDC dc, int prog)
{
    char lista[200], *tok, *p;
    int n = 0, y;
    topo(dc, L"ALERTA", -1, prog);
    painel(dc, 4, 23, 312, 213, L"PROBLEMAS", 128);
    strncpy(lista, val("alr"), sizeof(lista) - 1);
    lista[sizeof(lista) - 1] = 0;
    for (p = lista; *p; p++) if (*p == ';') n++;
    n++;
    if (n <= 2) {
        arco(dc, 160, 98, 46, 7, 1000, 28);
        txt(dc, 34, 1, RGB(255, 255, 255), 160, 112, L"!", MEIO);
        y = 156;
    } else y = 34;
    for (tok = lista; tok && *tok && y < 196; tok = p) {
        p = strchr(tok, ';');
        if (p) *p++ = 0;
        painel(dc, 14, y, 292, 30, NULL, 128);
        txta(dc, 13, 1, K_TXT, 26, y + 20, tok, ESQ);
        y += 36;
    }
    if (strcmp(val("net"), "0") == 0) {               /* situacao do alarme sonoro */
        const WCHAR *s = g_silenciado ? L"alarme silenciado"
                       : strcmp(val("som"), "1") != 0 ? L"sil\x00EAncio (23h \x00E0s 7h)"
                       : L"toque na tela para silenciar";
        txt(dc, 10, 0, g_pal->c, 160, 226, s, MEIO);
    }
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

static int n_telas(void) { return tem_alerta() ? 5 : 4; }

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
    g_pal = (!semdados && tem_alerta()) ? &PAL_ALERTA : &PAL_NEON;
    prog = (int)((agora - g_inicio) * LARG / rotacao_ms());
    if (prog > LARG) prog = LARG;
    if (semdados) tela_sem_dados(dc);
    else switch (g_vista % n_telas()) {
        case 0: tela_internet(dc, prog); break;
        case 1: tela_servidor(dc, prog); break;
        case 2: tela_maquinas(dc, prog); break;
        case 3: tela_servicos(dc, prog); break;
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
        return 0;
    case WM_TIMER:
        if (w == ID_TIMER_PROG) {
            verificar_alarme();
            if (GetTickCount() - g_inicio >= rotacao_ms()) proxima_tela(h);
            else InvalidateRect(h, NULL, FALSE);
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
        if (internet_fora(NULL)) g_silenciado = 1;    /* toque silencia o alarme */
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
    int i;
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
    for (i = 0; i < g_nfontes; i++) DeleteObject(g_fonte[i]);
    return 0;
}
