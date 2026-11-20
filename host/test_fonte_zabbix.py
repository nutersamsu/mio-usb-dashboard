import unittest
from datetime import datetime, timezone

from fonte_zabbix import (ErroZabbix, Internet, bytes_de_historico, bytes_de_trends,
                          formatar_gb, grafico, inicio_dia_mes)


def epoch(ano, mes, dia, h=0, m=0):
    return int(datetime(ano, mes, dia, h, m, tzinfo=timezone.utc).timestamp())


class TestPeriodos(unittest.TestCase):
    def test_dia_e_mes_no_fuso_de_roma(self):
        dia, mes = inicio_dia_mes(datetime(2026, 11, 20, 0, 30, tzinfo=timezone.utc))
        self.assertEqual(dia, epoch(2026, 11, 19, 23))      # 20/11 00:00 em Roma (UTC+1)
        self.assertEqual(mes, epoch(2026, 10, 31, 23))      # 01/11 00:00 em Roma

    def test_dia_com_horario_de_verao(self):
        dia, _ = inicio_dia_mes(datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(dia, epoch(2026, 3, 28, 23))       # 29/03 00:00 ainda UTC+1

    def test_virada_do_mes(self):
        dia, mes = inicio_dia_mes(datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc))
        self.assertEqual(dia, epoch(2026, 11, 30, 23))      # 01/12 00:30 em Roma
        self.assertEqual(mes, epoch(2026, 11, 30, 23))


class TestBytes(unittest.TestCase):
    def test_trends_hora_cheia(self):
        self.assertEqual(bytes_de_trends([{"value_avg": "8000000", "num": "60"}], 60), 3_600_000_000)

    def test_trends_hora_parcial_nao_inventa(self):
        # 20 amostras de 60 s (20 min) com media 8 Mbit/s = 1,2 GB, nao 3,6 GB
        self.assertEqual(bytes_de_trends([{"value_avg": "8000000", "num": "20"}], 60), 1_200_000_000)

    def test_historico_trapezio(self):
        self.assertEqual(bytes_de_historico([(0, 8e6), (10, 8e6)], 30), 10_000_000)

    def test_historico_ignora_lacuna(self):
        self.assertEqual(bytes_de_historico([(0, 8e6), (3600, 8e6)], 30), 0)

    def test_formatar(self):
        self.assertEqual(formatar_gb(13_500_000_000), "13,5 GB")
        self.assertEqual(formatar_gb(1_234_000_000_000), "1,2 TB")


class TestGrafico(unittest.TestCase):
    def test_normaliza_pelo_maximo(self):
        d = [(i, v * 1e6) for i, v in enumerate([10, 25, 50])]
        u = [(i, 5e6) for i in range(3)]
        gd, gu, mx = grafico(d, u, n=3)
        self.assertEqual(gd[-1], 99)
        self.assertEqual(gd[0], 19)
        self.assertEqual(mx, 50.0)
        self.assertEqual(len(gu), 3)

    def test_vazio(self):
        self.assertEqual(grafico([], [], n=20), ([], [], 0.0))


class ZabbixQuebrado:
    def chamar(self, metodo, params):
        raise ErroZabbix("fora do ar")


class ZabbixFalso:
    """Responde item.get/history.get; trend.get pode falhar; lastclock configuravel."""
    def __init__(self, lastclock, falha_trend=False):
        self.lastclock, self.falha_trend = lastclock, falha_trend

    def chamar(self, metodo, params):
        if metodo == "item.get":
            return [{"itemid": i, "lastvalue": "8000000", "lastclock": str(self.lastclock)}
                    for i in params["itemids"]]
        if metodo == "trend.get":
            if self.falha_trend:
                raise ErroZabbix("timeout")
            return []
        return [{"clock": str(self.lastclock - 10), "value": "8000000"},
                {"clock": str(self.lastclock), "value": "8000000"}]


class TestInternet(unittest.TestCase):
    AGORA = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)

    def test_falha_so_no_consumo_mantem_velocidade(self):
        ts = int(self.AGORA.timestamp())
        net = Internet(ZabbixFalso(ts - 5, falha_trend=True), "1", "2", "3", "4")
        d = net.atualizar(self.AGORA)
        self.assertEqual(d["wok"], "1")
        self.assertEqual(d["wd"], "8,0")
        self.assertEqual(d["ht"], "-")

    def test_velocidade_parada_marca_sem_dados(self):
        ts = int(self.AGORA.timestamp())
        net = Internet(ZabbixFalso(ts - 600), "1", "2", "3", "4")
        self.assertEqual(net.atualizar(self.AGORA)["wok"], "0")

    def test_zabbix_fora_marca_sem_dados(self):
        net = Internet(ZabbixQuebrado(), "53638", "53639", "50871", "50879")
        d = net.atualizar(datetime(2026, 11, 20, 12, tzinfo=timezone.utc))
        self.assertEqual(d["wok"], "0")


if __name__ == "__main__":
    unittest.main()
