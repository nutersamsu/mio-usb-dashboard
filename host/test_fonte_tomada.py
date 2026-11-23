import json
import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from fonte_tomada import Tomada

ROMA = ZoneInfo("Europe/Rome")


def t(ano, mes, dia, h=12, m=0, s=0):
    return datetime(ano, mes, dia, h, m, s, tzinfo=ROMA).timestamp()


def dps(w=0.0, v=230.0, ma=0, ligada=True):
    return {"1": ligada, "18": ma, "19": int(round(w * 10)), "20": int(round(v * 10))}


class Leitor:
    """Devolve as leituras da fila; Exception na fila = falha de rede."""
    def __init__(self, *fila):
        self.fila = list(fila)

    def __call__(self):
        r = self.fila.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def partes(saida):
    p = saida["tm"].split(";")
    return dict(zip(["te", "tw", "tv", "ta", "to", "tkd", "tkm", "ted", "tem", "teh", "hist"], p))


class TestTomada(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.estado = os.path.join(self.dir, "tomada.json")

    def nova(self, leitor, **cfg):
        base = {"estado": self.estado, "preco_kwh": 0.25}
        base.update(cfg)
        return Tomada(base, ler=leitor)

    def test_converte_os_valores(self):
        tom = self.nova(Leitor(dps(w=238.4, v=222.7, ma=1030)))
        p = partes(tom.atualizar(t(2026, 11, 23)))
        self.assertEqual((p["te"], p["tw"], p["tv"], p["ta"], p["to"]), ("1", "238", "223", "1.03", "1"))
        self.assertEqual(p["teh"], "0.060")      # 238,4 W x 0,25 EUR/kWh

    def test_integra_a_potencia(self):
        tom = self.nova(Leitor(dps(w=1000), dps(w=1000)))
        tom.atualizar(t(2026, 11, 23, 12, 0, 0))
        p = partes(tom.atualizar(t(2026, 11, 23, 12, 0, 36)))   # 1000 W por 36 s = 0,01 kWh
        self.assertEqual((p["tkd"], p["tkm"]), ("0.010", "0.01"))
        self.assertEqual(p["ted"], "0.00")      # 0,0025 EUR arredonda para 0,00
        self.assertAlmostEqual(tom.kwh_dia, 0.01, places=6)

    def test_buraco_maior_que_60s_nao_soma(self):
        tom = self.nova(Leitor(dps(w=1000), dps(w=1000)))
        tom.atualizar(t(2026, 11, 23, 12, 0, 0))
        tom.atualizar(t(2026, 11, 23, 12, 5, 0))
        self.assertEqual(tom.kwh_dia, 0)

    def test_falha_de_leitura_marca_sem_resposta_e_mantem_totais(self):
        tom = self.nova(Leitor(dps(w=1000), dps(w=1000), OSError("timeout"), dps(w=1000)))
        tom.atualizar(t(2026, 11, 23, 12, 0, 0))
        tom.atualizar(t(2026, 11, 23, 12, 0, 36))
        p = partes(tom.atualizar(t(2026, 11, 23, 12, 0, 46)))
        self.assertEqual((p["te"], p["tw"], p["tkd"]), ("0", "-", "0.010"))
        tom.atualizar(t(2026, 11, 23, 12, 0, 56))         # volta: não conta o intervalo da falha
        self.assertAlmostEqual(tom.kwh_dia, 0.01, places=6)

    def test_rele_desligado_conta_zero(self):
        tom = self.nova(Leitor(dps(w=50, ligada=False), dps(w=50, ligada=False)))
        tom.atualizar(t(2026, 11, 23, 12, 0, 0))
        p = partes(tom.atualizar(t(2026, 11, 23, 12, 0, 30)))
        self.assertEqual((p["to"], p["tw"]), ("0", "0"))
        self.assertEqual(tom.kwh_dia, 0)

    def test_virada_do_dia_zera_o_dia_e_mantem_o_mes(self):
        tom = self.nova(Leitor(dps(w=3600), dps(w=3600)))
        tom.atualizar(t(2026, 11, 23, 23, 59, 50))
        tom.atualizar(t(2026, 11, 24, 0, 0, 10))            # 20 s a 3600 W = 0,02 kWh, metade em cada dia
        self.assertAlmostEqual(tom.kwh_dia, 0.01, places=6)
        self.assertAlmostEqual(tom.kwh_mes, 0.02, places=6)

    def test_virada_do_mes_zera_os_dois(self):
        tom = self.nova(Leitor(dps(w=3600), dps(w=3600)))
        tom.atualizar(t(2026, 11, 30, 23, 59, 50))
        tom.atualizar(t(2026, 12, 1, 0, 0, 10))
        self.assertAlmostEqual(tom.kwh_dia, 0.01, places=6)
        self.assertAlmostEqual(tom.kwh_mes, 0.01, places=6)

    def test_estado_sobrevive_ao_reinicio(self):
        tom = self.nova(Leitor(dps(w=1000), dps(w=1000)))
        tom.atualizar(t(2026, 11, 23, 12, 0, 0))
        tom.atualizar(t(2026, 11, 23, 12, 0, 36))
        outra = self.nova(Leitor(dps(w=0)))
        p = partes(outra.atualizar(t(2026, 11, 23, 13, 0, 0)))
        self.assertEqual((p["tkd"], p["tkm"]), ("0.010", "0.01"))

    def test_estado_de_outro_dia_conta_so_o_mes(self):
        tom = self.nova(Leitor(dps(w=1000), dps(w=1000)))
        tom.atualizar(t(2026, 11, 22, 12, 0, 0))
        tom.atualizar(t(2026, 11, 22, 12, 0, 36))
        outra = self.nova(Leitor(dps(w=0)))
        p = partes(outra.atualizar(t(2026, 11, 23, 9, 0, 0)))
        self.assertEqual((p["tkd"], p["tkm"]), ("0.000", "0.01"))

    def test_estado_corrompido_recomeca(self):
        with open(self.estado, "w") as f:
            f.write("{isto nao e json")
        p = partes(self.nova(Leitor(dps(w=10))).atualizar(t(2026, 11, 23)))
        self.assertEqual((p["te"], p["tkd"]), ("1", "0.000"))

    def test_historico_tem_12_medias_de_5_minutos(self):
        fila = [dps(w=100)] * 4
        tom = self.nova(Leitor(*fila))
        for s in (0, 10, 20, 30):
            saida = tom.atualizar(t(2026, 11, 23, 12, 0, s))
        hist = partes(saida)["hist"].split(",")
        self.assertEqual(len(hist), 12)
        self.assertEqual(hist[-1], "100")
        self.assertEqual(hist[0], "-")

    def test_sem_chave_e_sem_leitor_fica_em_erro(self):
        tom = Tomada({"estado": self.estado, "chave_arquivo": os.path.join(self.dir, "nao-existe.json")})
        p = partes(tom.atualizar(t(2026, 11, 23)))
        self.assertEqual(p["te"], "e")
        self.assertTrue(tom.ultimo_erro)

    def test_leitor_tinytuya_com_chave_falsa_do_arquivo(self):
        chave = os.path.join(self.dir, "chave.json")
        with open(chave, "w") as f:
            json.dump({"id": "x", "ip": "192.0.2.1", "versao": 3.5, "chave": "0123456789abcdef"}, f)
        tom = Tomada({"estado": self.estado, "chave_arquivo": chave, "timeout": 0.2})
        p = partes(tom.atualizar(t(2026, 11, 23)))
        self.assertIn(p["te"], ("0", "e"))   # 0 = sem resposta (tinytuya presente), e = sem tinytuya


if __name__ == "__main__":
    unittest.main()
