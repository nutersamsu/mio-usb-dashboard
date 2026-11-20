import socket
import struct
import threading
import unittest

import fonte_rede
from fonte_rede import DiagnosticoRede, classificar, consulta_dns, ler_ping

SAIDA_OK = """PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.

--- 1.1.1.1 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 402ms
rtt min/avg/max/mdev = 11.204/12.500/13.900/1.100 ms
"""
SAIDA_PERDA = """--- 8.8.8.8 ping statistics ---
3 packets transmitted, 2 received, 33.3333% packet loss, time 403ms
rtt min/avg/max/mdev = 20.000/21.000/22.000/1.000 ms
"""
SAIDA_FORA = """--- 192.0.2.1 ping statistics ---
3 packets transmitted, 0 received, 100% packet loss, time 2050ms
"""


class TestLerPing(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(ler_ping(SAIDA_OK, 3), (3, 3, 12.5))

    def test_perda(self):
        self.assertEqual(ler_ping(SAIDA_PERDA, 3), (3, 2, 21.0))

    def test_fora_e_lixo(self):
        self.assertEqual(ler_ping(SAIDA_FORA, 3), (3, 0, None))
        self.assertEqual(ler_ping("", 3), (3, 0, None))


class ServidorDns:
    """Responde uma consulta UDP com o rcode e o numero de respostas pedidos."""
    def __init__(self, rcode=0, respostas=1, responder=True):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind(("127.0.0.1", 0))
        self.porta = self.s.getsockname()[1]
        self.rcode, self.respostas, self.responder = rcode, respostas, responder
        self.t = threading.Thread(target=self._um, daemon=True)
        self.t.start()

    def _um(self):
        dados, origem = self.s.recvfrom(512)
        if self.responder:
            tid = dados[:2]
            cab = tid + struct.pack(">HHHHH", 0x8180 | self.rcode, 1, self.respostas, 0, 0)
            self.s.sendto(cab + dados[12:], origem)

    def fechar(self):
        self.t.join(1)
        self.s.close()


class TestConsultaDns(unittest.TestCase):
    def test_resposta_valida(self):
        srv = ServidorDns()
        self.assertTrue(consulta_dns("127.0.0.1", "cloudflare.com", 1, srv.porta))
        srv.fechar()

    def test_servfail(self):
        srv = ServidorDns(rcode=2, respostas=0)
        self.assertFalse(consulta_dns("127.0.0.1", "cloudflare.com", 1, srv.porta))
        srv.fechar()

    def test_sem_resposta(self):
        srv = ServidorDns(responder=False)
        self.assertFalse(consulta_dns("127.0.0.1", "cloudflare.com", 0.3, srv.porta))
        srv.fechar()


class TestClassificar(unittest.TestCase):
    L = {"latencia": 150, "perda": 5}

    def test_prioridade(self):
        self.assertEqual(classificar(False, False, False, None, 100, self.L), ("gw", 2))
        self.assertEqual(classificar(True, False, False, None, 100, self.L), ("net", 2))
        self.assertEqual(classificar(True, True, False, 20, 0, self.L), ("dns", 1))
        self.assertEqual(classificar(True, True, True, 20, 12, self.L), ("perda", 1))
        self.assertEqual(classificar(True, True, True, 300, 0, self.L), ("lat", 1))
        self.assertEqual(classificar(True, True, True, 20, 0, self.L), ("ok", 0))


class TestDiagnostico(unittest.TestCase):
    def fazer(self, pings, dns_ok=True):
        fila = list(pings)
        return DiagnosticoRede(["a", "b"], "127.0.0.1", ["x.com"],
                               ping=lambda alvo: fila.pop(0),
                               dns=lambda srv, nome: dns_ok)

    def test_rodada_ok_e_latencia(self):
        d = self.fazer([(3, 3, 10.0), (3, 3, 20.0)])
        self.assertTrue(d.testar())
        self.assertEqual(d.perda(), 0)
        self.assertEqual(d.latencia(), 15.0)

    def test_perda_parcial(self):
        d = self.fazer([(3, 2, 10.0), (3, 3, 10.0)])
        d.testar()
        self.assertEqual(d.perda(), 17)

    def test_queda_total_nao_conta_como_perda(self):
        d = self.fazer([(3, 0, None), (3, 0, None), (3, 3, 10.0), (3, 3, 10.0)])
        self.assertFalse(d.testar())
        self.assertTrue(d.testar())
        self.assertEqual(d.perda(), 0)

    def test_dns_so_cai_apos_3_falhas(self):
        d = self.fazer([(3, 3, 10.0)] * 8, dns_ok=False)
        d.testar()
        d.testar()
        self.assertTrue(d.dns_ok())
        d.testar()
        self.assertFalse(d.dns_ok())

    def test_campos(self):
        d = self.fazer([(3, 3, 10.0), (3, 3, 30.0)])
        d.testar()
        c = d.campos(True, True, {"latencia": 150, "perda": 5})
        self.assertEqual(c, {"gw": "1", "lat": "20", "per": "0", "dns": "1",
                             "nst": "ok", "nlv": "0"})

    def test_campos_sem_medida(self):
        d = self.fazer([])
        c = d.campos(False, False, {"latencia": 150, "perda": 5})
        self.assertEqual((c["lat"], c["per"], c["nst"], c["nlv"]), ("-", "-", "gw", "2"))


class TestDnsAuto(unittest.TestCase):
    def test_resolv_conf(self):
        texto = "nameserver 127.0.0.53\nnameserver 192.168.1.1\n"
        self.assertEqual(fonte_rede.dns_do_sistema(texto, "10.0.0.1"), "192.168.1.1")
        self.assertEqual(fonte_rede.dns_do_sistema("", "10.0.0.1"), "10.0.0.1")


if __name__ == "__main__":
    unittest.main()
