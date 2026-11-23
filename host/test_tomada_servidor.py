"""Tela ENERGIA: a tomada entra na linha do Mio e nos alertas (opcionais)."""
import unittest

import server
import test_bloco3
from test_bloco2 import coletor
from test_linha import dados_exemplo

TM = "1;238;223;1.03;1;1.420;19.20;0.36;4.80;0.060;" + ",".join(["120"] * 12)


class FonteFalsa:
    def __init__(self, saida):
        self.saida, self.chamadas = saida, 0

    def atualizar(self, t):
        self.chamadas += 1
        return {"tm": self.saida}


def niveis(c, agora, **extra):
    d = dados_exemplo()
    d["ram"], d["servicos"] = 50, []
    d["extra"].update(extra)
    return {k: (n, b, txt) for k, n, b, txt in c.alertas_nivel(d, agora=agora)}


class TestConfig(unittest.TestCase):
    def test_sem_bloco_tomada_nao_cria_fonte(self):
        c = server.Coletor(server.carregar_config(None))
        self.assertIsNone(c.tomada)

    def test_bloco_desligado_nao_cria_fonte(self):
        cfg = server.carregar_config(None)
        cfg["tomada"] = {"ativo": False, "chave_arquivo": "/nao/existe.json"}
        self.assertIsNone(server.Coletor(cfg).tomada)

    def test_bloco_ligado_sem_chave_cria_fonte_em_erro(self):
        cfg = server.carregar_config(None)
        cfg["tomada"] = {"ativo": True, "chave_arquivo": "/nao/existe.json"}
        c = server.Coletor(cfg)
        self.assertEqual(c.tomada.atualizar(0)["tm"].split(";")[0], "e")


class TestLinha(unittest.TestCase):
    def test_tm_vai_na_linha_e_cabe_no_mio(self):
        self.assertNotIn("tm=", server.linha_serial(dados_exemplo()).decode("cp1252"))
        d = dados_exemplo()
        d["extra"]["tm"] = TM
        campos = dict(c.split("=", 1) for c in server.linha_serial(d).decode("cp1252").strip().split("|")[1:])
        self.assertEqual(len(campos["tm"].split(";")), 11)

    def test_linha_completa_com_tomada_ainda_cabe(self):
        t = test_bloco3.TestLinhaV3()
        orig = server.linha_serial

        def com_tm(d):
            d["extra"]["tm"] = TM
            return orig(d)
        server.linha_serial = com_tm
        try:
            linha = t.linha()
        finally:
            server.linha_serial = orig
        campos = linha.decode("cp1252").strip().split("|")[1:]
        self.assertLessEqual(len(campos), 56)
        self.assertLess(len(linha), 2048)


class TestExtras(unittest.TestCase):
    def test_tarefa_da_tomada_roda_a_cada_10s(self):
        cfg = server.carregar_config(None)
        cfg["servicos"] = []                      # sem checagens reais de serviço no teste
        c = server.Coletor(cfg)
        c.tomada = FonteFalsa(TM)
        c.internet = None
        c.ler_pve = lambda *a, **k: (_ for _ in ()).throw(OSError("sem pve"))
        c._testar_net = lambda agora: {"net": "1", "som": "0"}
        self.assertEqual(c.extras(1000.0)["tm"], TM)
        c.extras(1005.0)
        self.assertEqual(c.tomada.chamadas, 1)
        c.extras(1010.0)
        self.assertEqual(c.tomada.chamadas, 2)


class TestAlertas(unittest.TestCase):
    def test_sem_resposta_so_avisa_se_ligado_e_depois_de_5_min(self):
        c = coletor()
        c._tomada_falha_desde = 0.0
        sem = "0;-;-;-;-;0.100;1.00;0.03;0.25;-;" + ",".join(["-"] * 12)
        self.assertNotIn("tomada", niveis(c, 1000.0, tm=sem))          # alerta desligado (padrão)
        c.cfg["tomada"] = {"alerta_sem_resposta": True}
        self.assertNotIn("tomada", niveis(c, 1000.0, tm=sem))
        self.assertNotIn("tomada", niveis(c, 1200.0, tm=sem))
        self.assertEqual(niveis(c, 1301.0, tm=sem)["tomada"][:2], (1, False))
        self.assertNotIn("tomada", niveis(c, 1310.0, tm=TM))           # voltou

    def test_potencia_acima_do_limite_e_aviso(self):
        c = coletor()
        c._tomada_falha_desde = 0.0
        c.cfg["tomada"] = {"alerta_w": 200}
        n = niveis(c, 1000.0, tm=TM)
        self.assertEqual(n["tomada:w"][:2], (1, False))
        self.assertIn("238 W", n["tomada:w"][2])
        c.cfg["tomada"] = {"alerta_w": 300}
        self.assertNotIn("tomada:w", niveis(c, 1000.0, tm=TM))


if __name__ == "__main__":
    unittest.main()
