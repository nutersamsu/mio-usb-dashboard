import unittest

import server


def dados_exemplo():
    return {
        "host": "pve", "hora": "19:58:01", "cpu": 10.0, "ram_u": 17676, "ram_t": 23725,
        "ram": 74.5, "disco_livre": 84.3, "disco_total": 100.9, "disco": 11.9, "temp": 34.0,
        "uptime": "1d 08h55m", "iface": "vmbr0", "rx": 0.3, "tx": 1.0, "ping_alvo": "192.168.1.1",
        "ping": 0.1, "pve": (2, 3, 1, 1),
        "servicos": [("Jellyfin", False), ("DNS", True)],
        "alertas": ["Jellyfin fora do ar", "RAM 92%"],
        "extra": {"wok": "1", "wd": "94,2", "wu": "8,6",
                  "wg": ",".join("%d/%d" % (v, v // 10) for v in range(80, 100)),
                  "wm": "100", "hd": "12,4 GB", "hu": "1,1 GB", "ht": "13,5 GB",
                  "md": "318,0 GB", "mu": "41,0 GB", "mt": "359,0 GB", "mes": "NOVEMBRO",
                  "dia": "20", "ndias": "30", "nvm": "3/4",
                  "vm1": "server;VM 100;1;18%;9,1 GB", "vm2": "x|y;CT 101;1;4%;1,2 GB",
                  "sv1": "Jellyfin;0;", "sv2": "DNS;1;1", "nsv": "1/2"},
    }


class TestLinhaSerial(unittest.TestCase):
    def setUp(self):
        self.linha = server.linha_serial(dados_exemplo())

    def test_formato(self):
        self.assertTrue(self.linha.startswith(b"D|"))
        self.assertTrue(self.linha.endswith(b"\r\n"))
        self.assertLessEqual(len(self.linha), 2048)

    def test_campos_novos(self):
        campos = dict(c.split("=", 1) for c in self.linha.decode().strip().split("|")[1:])
        for k in ("wd", "wu", "wg", "hd", "mt", "mes", "vm1", "sv1", "nvm", "nsv", "alr"):
            self.assertIn(k, campos)
        self.assertEqual(campos["wd"], "94,2")
        self.assertEqual(campos["alr"], "Jellyfin fora do ar;RAM 92%")

    def test_valor_sem_barra(self):
        campos = self.linha.decode().strip().split("|")[1:]
        self.assertTrue(all("=" in c for c in campos))
        self.assertIn("vm2=x/y;CT 101;1;4%;1,2 GB", campos)


class TestPiorCaso(unittest.TestCase):
    def test_no_maximo_48_campos_com_6_vms_e_9_servicos(self):
        d = dados_exemplo()
        for k in range(1, 7):
            d["extra"]["vm%d" % k] = "maquina%d;VM 10%d;1;5%%;1,0 GB" % (k, k)
        for k in range(1, 10):
            d["extra"]["sv%d" % k] = "Servico%d;1;2" % k
        d["extra"]["rot"] = "20"
        campos = server.linha_serial(d).decode().strip().split("|")[1:]
        self.assertLessEqual(len(campos), 48)
        nomes = [c.split("=", 1)[0] for c in campos]
        for k in ("wok", "wu", "wd", "rot", "vm6", "sv9"):
            self.assertIn(k, nomes)


class TestExtrasRobustos(unittest.TestCase):
    def test_falha_numa_fonte_nao_derruba_as_outras(self):
        c = server.Coletor.__new__(server.Coletor)
        c.cfg = server.carregar_config(None)
        c._extra, c._extra_em = {}, {}
        c.ler_pve = None
        c._ok_em, c._inicio, c.crowdsec = {}, 1000.0, None

        class Quebrada:
            def atualizar(self, agora):
                raise RuntimeError("inesperado")
        c.internet = Quebrada()
        orig_m, orig_s = server.ler_maquinas, server.testar_servicos
        server.ler_maquinas = lambda ler: {"nvm": "1/1", "vm1": "a;VM 1;1;1%;1,0 GB"}
        server.testar_servicos = lambda lista: (_ for _ in ()).throw(KeyError("nome"))
        try:
            d = c.extras(1000.0)
        finally:
            server.ler_maquinas, server.testar_servicos = orig_m, orig_s
        self.assertEqual(d["wok"], "0")
        self.assertEqual(d["nvm"], "1/1")
        self.assertEqual(d["nsv"], "-")


class TestDadosVelhos(unittest.TestCase):
    def test_nao_envia_dados_parados(self):
        self.assertTrue(server.dados_frescos({"_em": 100.0}, agora=110.0))
        self.assertFalse(server.dados_frescos({"_em": 100.0}, agora=130.0))
        self.assertFalse(server.dados_frescos({}, agora=130.0))


class TestAlarmeInternet(unittest.TestCase):
    def test_som_respeita_silencio_e_config(self):
        cfg = {"internet_teste": {"som": True, "silencio": "23-7"}}
        self.assertEqual(server.som_ativo(cfg, 12), "1")
        self.assertEqual(server.som_ativo(cfg, 23), "0")
        self.assertEqual(server.som_ativo({"internet_teste": {"som": False}}, 12), "0")
        self.assertEqual(server.som_ativo({}, 12), "1")

    def test_alerta_internet_caiu_com_acento_em_cp1252(self):
        c = server.Coletor.__new__(server.Coletor)
        c.cfg = server.carregar_config(None)
        c._ping_falhas = 0
        c._internet_falha_desde = 0.0
        d = dados_exemplo()
        d["ram"] = 50
        d["servicos"] = []
        d["extra"].update({"net": "0", "netmin": "3"})
        d["alertas"] = c.alertas(d, agora=1000.0)
        self.assertIn("Internet caiu há 3 min", d["alertas"])
        linha = server.linha_serial(d)
        self.assertIn("Internet caiu h\xe1 3 min".encode("latin-1"), linha)
        self.assertNotIn(b"netmin=", linha)
        self.assertIn(b"net=0", linha)


class TestAlertas(unittest.TestCase):
    def test_servico_fora_e_opnsense_sem_dados(self):
        c = server.Coletor.__new__(server.Coletor)
        c.cfg = server.carregar_config(None)
        c._ping_falhas = 0
        c._internet_falha_desde = 0.0
        d = dados_exemplo()
        d["ram"] = 50
        a = c.alertas(d, agora=1000.0)
        self.assertIn("Jellyfin fora do ar", a)
        d["extra"]["wok"] = "0"
        c.alertas(d, agora=1000.0)
        self.assertIn("OPNsense sem dados", c.alertas(d, agora=1200.0))


class TestTempoTela(unittest.TestCase):
    def test_padrao_e_limites(self):
        self.assertEqual(server.tempo_tela({}), "10")
        self.assertEqual(server.tempo_tela({"tempo_tela": 30}), "30")
        self.assertEqual(server.tempo_tela({"tempo_tela": 1}), "5")
        self.assertEqual(server.tempo_tela({"tempo_tela": 9999}), "600")
        self.assertEqual(server.tempo_tela({"tempo_tela": "x"}), "10")


if __name__ == "__main__":
    unittest.main()
