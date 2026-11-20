import unittest

from fonte_internet import TesteInternet, em_silencio


class TestEstado(unittest.TestCase):
    def test_cai_so_depois_de_3_falhas(self):
        t = TesteInternet(falhas=3)
        for _ in range(2):
            t.registrar(False, agora=0)
        self.assertEqual(t.estado(agora=0)["net"], "1")
        t.registrar(False, agora=30)
        self.assertEqual(t.estado(agora=30)["net"], "0")

    def test_um_sucesso_volta(self):
        t = TesteInternet(falhas=3)
        for s in range(3):
            t.registrar(False, agora=s * 10)
        t.registrar(True, agora=40)
        self.assertEqual(t.estado(agora=40)["net"], "1")

    def test_minutos_fora(self):
        t = TesteInternet(falhas=3)
        for s in range(3):
            t.registrar(False, agora=s * 10)       # cai em t=20
        self.assertEqual(t.minutos_fora(agora=20 + 180), 3)
        self.assertEqual(t.minutos_fora(agora=20 + 30), 0)

    def test_falha_intercalada_zera_contagem(self):
        t = TesteInternet(falhas=3)
        for ok in (False, False, True, False, False):
            t.registrar(ok, agora=0)
        self.assertEqual(t.estado(agora=0)["net"], "1")


class TestSilencio(unittest.TestCase):
    def test_noite_23_as_7(self):
        for h in (23, 0, 3, 6):
            self.assertTrue(em_silencio(h, "23-7"), h)
        for h in (7, 12, 22):
            self.assertFalse(em_silencio(h, "23-7"), h)

    def test_mesmo_dia_e_desligado(self):
        self.assertTrue(em_silencio(13, "12-14"))
        self.assertFalse(em_silencio(14, "12-14"))
        self.assertFalse(em_silencio(3, ""))
        self.assertFalse(em_silencio(3, "lixo"))


class TestTestar(unittest.TestCase):
    def test_qualquer_alvo_bom_basta(self):
        t = TesteInternet(alvos=["a", "b"], falhas=1, ping=lambda alvo: alvo == "b")
        t.testar(agora=0)
        self.assertEqual(t.estado(agora=0)["net"], "1")

    def test_todos_ruins_caem(self):
        t = TesteInternet(alvos=["a", "b"], falhas=1, ping=lambda alvo: False)
        t.testar(agora=0)
        self.assertEqual(t.estado(agora=0)["net"], "0")


if __name__ == "__main__":
    unittest.main()
