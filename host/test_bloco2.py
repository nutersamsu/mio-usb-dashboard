"""Bloco 2: diagnostico da internet, CrowdSec e dados velhos por fonte, ligados ao servidor."""
import unittest

import server
from test_linha import dados_exemplo


def coletor():
    c = server.Coletor.__new__(server.Coletor)
    c.cfg = server.carregar_config(None)
    c._ping_falhas = 0
    c._internet_falha_desde = 0.0
    return c


class TestAlertasNovos(unittest.TestCase):
    def alertas(self, **extra):
        d = dados_exemplo()
        d["ram"] = 50
        d["servicos"] = []
        d["extra"].update(extra)
        return coletor().alertas(d, agora=1000.0)

    def test_tudo_ok_sem_alerta(self):
        self.assertEqual(self.alertas(gw="1", dns="1", nst="ok", lat="12", per="0", cs="1"), [])

    def test_gateway(self):
        c = coletor()
        c._ping_falhas = 3
        d = dados_exemplo()
        d["ram"], d["servicos"] = 50, []
        self.assertIn("Gateway sem resposta", c.alertas(d, agora=1000.0))

    def test_dns_nao_e_queda(self):
        a = self.alertas(net="1", dns="0", nst="dns")
        self.assertIn("DNS falhando", a)
        self.assertFalse(any("Internet caiu" in x for x in a))

    def test_perda_e_latencia(self):
        self.assertIn("Perda de pacotes 12%", self.alertas(nst="perda", per="12"))
        self.assertIn("Latência alta 180 ms", self.alertas(nst="lat", lat="180"))

    def test_crowdsec(self):
        self.assertIn("CrowdSec parado", self.alertas(cs="0"))
        self.assertIn("CrowdSec sem leitura", self.alertas(cs="e"))
        self.assertEqual(self.alertas(cs="-"), [])

    def test_fonte_sem_dados(self):
        self.assertIn("Sem dados: Proxmox", self.alertas(old="pve"))
        a = self.alertas(old="pve,crowdsec")
        self.assertIn("Sem dados: CrowdSec", a)


class TestDadosVelhos(unittest.TestCase):
    def test_fonte_falhando_vira_velha_e_volta(self):
        c = coletor()
        c._extra, c._extra_em, c._ok_em, c._inicio = {}, {}, {}, 0.0
        c.internet = None
        c.crowdsec = None
        c.diag = None
        estado = {"ok": True}
        c.ler_pve = None
        orig = server.ler_maquinas
        server.ler_maquinas = lambda ler: {"nvm": "1/1"} if estado["ok"] else {"nvm": "-"}
        try:
            self.assertEqual(c.extras(10.0).get("old", ""), "")
            estado["ok"] = False
            self.assertEqual(c.extras(40.0).get("old", ""), "")     # ainda dentro do limite
            self.assertEqual(c.extras(200.0)["old"], "pve")
            estado["ok"] = True
            self.assertEqual(c.extras(300.0).get("old", ""), "")
        finally:
            server.ler_maquinas = orig

    def test_no_inicio_nao_acusa(self):
        c = coletor()
        c._extra, c._extra_em, c._ok_em, c._inicio = {}, {}, {}, 1000.0
        self.assertEqual(c.velhas(1010.0), [])


class TestLinhaCabe(unittest.TestCase):
    def test_pior_caso_com_campos_novos(self):
        d = dados_exemplo()
        for k in range(1, 7):
            d["extra"]["vm%d" % k] = "maquina%d;VM 10%d;1;5%%;1,0 GB" % (k, k)
        for k in range(1, 10):
            d["extra"]["sv%d" % k] = "Servico%d;1;2" % k
        d["extra"].update({"rot": "20", "gw": "1", "lat": "12", "per": "0", "dns": "1",
                           "nst": "ok", "nlv": "0", "cs": "1", "csb": "3", "csn": "12",
                           "csl": "15176", "old": "pve,zabbix,crowdsec", "net": "1",
                           "som": "1"})
        linha = server.linha_serial(d)
        campos = linha.decode().strip().split("|")[1:]
        # MioDash: MAX_CAMPOS 64 (campos a mais sao descartados), linha ate 2048 bytes
        self.assertLessEqual(len(campos), 56)
        self.assertLess(len(linha), 2048)
        nomes = [c.split("=", 1)[0] for c in campos]
        for k in ("wok", "vm6", "sv9", "cn", "cs", "old"):   # nst vai dentro de cn (bloco 3)
            self.assertIn(k, nomes)
        self.assertTrue(all(len(n) < 12 for n in nomes))      # Campo.k[12] no Mio


if __name__ == "__main__":
    unittest.main()
