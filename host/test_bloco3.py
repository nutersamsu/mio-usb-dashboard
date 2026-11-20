"""Bloco 3: niveis de alerta, bip so para criticos, eventos e campos compostos da linha."""
import os
import tempfile
import unittest

import server
from eventos import Eventos
from test_bloco2 import coletor
from test_linha import dados_exemplo


def niveis(**extra):
    d = dados_exemplo()
    d["ram"], d["servicos"] = 50, []
    d["extra"].update(extra)
    return coletor().alertas_nivel(d, agora=1000.0)


class TestNiveis(unittest.TestCase):
    def nivel_de(self, chave, lista):
        return {c: (n, b) for c, n, b, _ in lista}[chave]

    def test_criticos_que_apitam(self):
        self.assertEqual(self.nivel_de("internet", niveis(net="0", netmin="3")), (2, True))
        self.assertEqual(self.nivel_de("cs", niveis(cs="0")), (2, True))
        self.assertEqual(self.nivel_de("old:pve", niveis(old="pve")), (2, True))

    def test_avisos_sem_som(self):
        self.assertEqual(self.nivel_de("dns", niveis(dns="0", nst="dns")), (1, False))
        self.assertEqual(self.nivel_de("cs", niveis(cs="e")), (1, False))
        self.assertEqual(self.nivel_de("old:crowdsec", niveis(old="crowdsec")), (1, False))

    def test_temperatura_critica_disco_aviso(self):
        d = dados_exemplo()
        d["ram"], d["servicos"], d["temp"], d["disco"] = 50, [], 90.0, 95.0
        lista = coletor().alertas_nivel(d, agora=1000.0)
        self.assertEqual(self.nivel_de("temp", lista), (2, True))
        self.assertEqual(self.nivel_de("disco", lista), (1, False))

    def test_gateway_critico(self):
        c = coletor()
        c._ping_falhas = 3
        d = dados_exemplo()
        d["ram"], d["servicos"] = 50, []
        self.assertEqual(self.nivel_de("gw", c.alertas_nivel(d, agora=1000.0)), (2, True))

    def test_vm_importante_desligada_e_aviso(self):
        c = coletor()
        c.cfg["maquinas_importantes"] = ["server", "jellyfin"]
        d = dados_exemplo()
        d["ram"], d["servicos"] = 50, []
        d["extra"]["vm1"] = "server;VM 100;0;;desligada"
        d["extra"]["vm2"] = "jellyfin;CT 101;1;4%;1,2 GB"
        lista = c.alertas_nivel(d, agora=1000.0)
        self.assertEqual(self.nivel_de("vm:server", lista), (1, False))
        self.assertNotIn("vm:jellyfin", [x[0] for x in lista])

    def test_alertas_continua_devolvendo_textos(self):
        d = dados_exemplo()
        d["ram"], d["servicos"] = 50, []
        d["extra"]["cs"] = "0"
        self.assertIn("CrowdSec parado", coletor().alertas(d, agora=1000.0))


class TestCamposAlerta(unittest.TestCase):
    def test_bip_e_id_so_dos_criticos(self):
        lista = [("internet", 2, True, "Internet caiu"), ("dns", 1, False, "DNS falhando")]
        c = server.campos_alerta(lista)
        self.assertEqual(c["alv"], "2;1")
        self.assertEqual(c["bip"], "1")
        self.assertEqual(len(c["aid"]), 4)
        # mesmo critico, texto diferente (minutos) -> mesmo id: nao volta a apitar
        lista2 = [("internet", 2, True, "Internet caiu há 5 min"), ("disco", 1, False, "DISCO 95%")]
        self.assertEqual(server.campos_alerta(lista2)["aid"], c["aid"])
        # outro critico -> id novo
        lista3 = lista + [("gw", 2, True, "Gateway sem resposta")]
        self.assertNotEqual(server.campos_alerta(lista3)["aid"], c["aid"])

    def test_sem_critico(self):
        c = server.campos_alerta([("dns", 1, False, "DNS falhando")])
        self.assertEqual((c["bip"], c["aid"]), ("0", "-"))
        self.assertEqual(server.campos_alerta([])["alv"], "")


class TestEventos(unittest.TestCase):
    def setUp(self):
        self.arq = os.path.join(tempfile.mkdtemp(), "ev.json")

    def test_sobe_e_desce(self):
        e = Eventos(self.arq, hora=lambda t: "20:%02d" % (t // 60 % 60))
        e.atualizar([("internet", 2, True, "Internet caiu há 0 min")], 120)
        e.atualizar([("internet", 2, True, "Internet caiu há 1 min")], 180)
        e.atualizar([], 600)
        self.assertEqual(e.campo(), "20:10,0,Internet voltou;20:02,2,Internet caiu")

    def test_pisca_pisca_nao_enche_a_lista(self):
        e = Eventos(None, hora=lambda t: "x")
        for t in range(0, 200, 20):                 # sobe e desce a cada 10 s
            e.atualizar([("dns", 1, False, "DNS falhando")] if t % 40 == 0 else [], t)
        self.assertEqual(len(e.lista), 2)            # 1 subida e 1 descida em 5 min

    def test_texto_limpo_e_curto(self):
        e = Eventos(None, hora=lambda t: "x")
        e.info("Mio, conectado; a|b " + "y" * 60, 0)
        txt = e.lista[0][2]
        self.assertNotIn(",", txt)
        self.assertNotIn(";", txt)
        self.assertNotIn("|", txt)
        self.assertLessEqual(len(txt), 30)

    def test_persiste(self):
        e = Eventos(self.arq, hora=lambda t: "10:00")
        e.info("Serviço iniciado", 0)
        self.assertEqual(Eventos(self.arq).campo(), "10:00,0,Serviço iniciado")

    def test_arquivo_ruim_nao_quebra(self):
        with open(self.arq, "w") as f:
            f.write("lixo")
        self.assertEqual(Eventos(self.arq).campo(), "")


class TestLinhaV3(unittest.TestCase):
    def linha(self):
        d = dados_exemplo()
        for k in range(1, 7):
            d["extra"]["vm%d" % k] = "maquina%d;VM 10%d;1;5%%;1,0 GB" % (k, k)
        for k in range(1, 10):
            d["extra"]["sv%d" % k] = "Servico%d;1;2" % k
        d["extra"].update({"rot": "20", "gw": "1", "lat": "12", "per": "0", "dns": "1",
                           "nst": "ok", "nlv": "0", "cs": "1", "csb": "3", "csn": "12",
                           "csl": "15176", "csi": "40", "old": "pve,zabbix,crowdsec", "net": "1",
                           "som": "1", "llat": "150", "lper": "5",
                           "alv": "2;1", "bip": "1", "aid": "ab12",
                           "ev": ";".join("20:0%d,2,%s" % (k, "x" * 28) for k in range(4)),
                           "ver": server.VERSAO})
        return server.linha_serial(d)

    def test_compostos(self):
        campos = dict(c.split("=", 1) for c in self.linha().decode("cp1252").strip().split("|")[1:])
        self.assertEqual(campos["cn"], "1;1;12;0;ok;0;150;5")
        self.assertEqual(campos["cs"], "1;3;12;15176;40")
        for k in ("gw", "lat", "per", "dns", "nst", "nlv", "csb", "csn", "csl", "csi", "llat", "lper"):
            self.assertNotIn(k, campos)
        self.assertIn("net", campos)              # o alarme antigo do Mio ainda usa

    def test_cabe_no_mio(self):
        linha = self.linha()
        campos = linha.decode("cp1252").strip().split("|")[1:]
        self.assertLessEqual(len(campos), 56)     # MAX_CAMPOS 64 no MioDash
        self.assertLess(len(linha), 2048)
        self.assertTrue(all(len(c.split("=", 1)[1]) < 200 for c in campos))   # Campo.v[200]

    def test_cs_fora_sem_numeros(self):
        d = dados_exemplo()
        d["extra"].update({"cs": "0", "csi": "300"})
        campos = dict(c.split("=", 1) for c in server.linha_serial(d).decode("cp1252").strip().split("|")[1:])
        self.assertEqual(campos["cs"], "0;;;;300")


if __name__ == "__main__":
    unittest.main()
