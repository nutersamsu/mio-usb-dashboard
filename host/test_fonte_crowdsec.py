import json
import os
import tempfile
import unittest
from urllib.error import HTTPError, URLError

from fonte_crowdsec import CrowdSec

DIA = 86400


class Falso:
    """Simula a LAPI: rota -> resposta (bytes) ou excecao."""
    def __init__(self, rotas):
        self.rotas, self.pedidos = rotas, []

    def __call__(self, req, timeout):
        self.pedidos.append(req)
        for trecho, resp in self.rotas.items():
            if trecho in req.full_url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError("rota inesperada " + req.full_url)


def dec(i, valor, tipo="ban"):
    return {"id": i, "value": valor, "type": tipo, "origin": "crowdsec", "scope": "Ip"}


class TestCrowdSec(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.chave = os.path.join(self.dir, "cs.key")
        with open(self.chave, "w") as f:
            f.write("CHAVE\n")
        self.estado = os.path.join(self.dir, "vistos.json")

    def cs(self, rotas, **kw):
        self.falso = Falso(rotas)
        return CrowdSec("http://lapi:8080", self.chave, self.estado, abrir=self.falso, **kw)

    def test_normal(self):
        c = self.cs({"/health": b'{"status":"up"}',
                     "origins=crowdsec": json.dumps([dec(1, "1.2.3.4"), dec(2, "1.2.3.4"),
                                                     dec(3, "5.6.7.8", "captcha")]).encode(),
                     "origins=CAPI": json.dumps([dec(9, "9.9.9.9")] * 4).encode()})
        self.assertEqual(c.atualizar(1000.0), {"cs": "1", "csb": "1", "csn": "3", "csl": "4"})
        req = [r for r in self.falso.pedidos if "decisions" in r.full_url][0]
        self.assertEqual(req.get_header("X-api-key"), "CHAVE")
        self.assertEqual(req.get_method(), "GET")

    def test_sem_decisoes_null(self):
        c = self.cs({"/health": b'{"status":"up"}', "origins=crowdsec": b"null",
                     "origins=CAPI": b"null"})
        self.assertEqual(c.atualizar(1000.0), {"cs": "1", "csb": "0", "csn": "0", "csl": "0"})

    def test_novos_24h_persistem_e_expiram(self):
        rotas = {"/health": b'{"status":"up"}',
                 "origins=crowdsec": json.dumps([dec(1, "1.1.1.1")]).encode()}
        c = self.cs(rotas, comunidade=False)
        self.assertEqual(c.atualizar(1000.0)["csn"], "1")
        # reinicio do servico: le o estado salvo, nao conta de novo
        c2 = self.cs(rotas, comunidade=False)
        self.assertEqual(c2.atualizar(1000.0 + 3600)["csn"], "1")
        self.assertEqual(c2.atualizar(1000.0 + DIA + 1)["csn"], "0")

    def test_lista_comunitaria_so_a_cada_30_min(self):
        c = self.cs({"/health": b'{"status":"up"}', "origins=crowdsec": b"[]",
                     "origins=CAPI": b"[]"})
        c.atualizar(1000.0)
        c.atualizar(1060.0)
        capi = [r for r in self.falso.pedidos if "CAPI" in r.full_url]
        self.assertEqual(len(capi), 1)

    def test_lapi_fora_e_servico_parado(self):
        c = self.cs({"/health": URLError("connection refused")})
        self.assertEqual(c.atualizar(1000.0), {"cs": "0"})

    def test_chave_recusada_e_erro_de_leitura(self):
        c = self.cs({"/health": b'{"status":"up"}',
                     "origins=crowdsec": HTTPError("u", 403, "Forbidden", {}, None)})
        self.assertEqual(c.atualizar(1000.0), {"cs": "e"})

    def test_chave_nunca_aparece_em_erro(self):
        c = self.cs({"/health": b'{"status":"up"}',
                     "origins=crowdsec": HTTPError("u", 403, "Forbidden", {}, None)})
        c.atualizar(1000.0)
        self.assertNotIn("CHAVE", c.ultimo_erro)

    def test_estado_ilegivel_nao_quebra(self):
        with open(self.estado, "w") as f:
            f.write("{lixo")
        c = self.cs({"/health": b'{"status":"up"}', "origins=crowdsec": b"[]"}, comunidade=False)
        self.assertEqual(c.atualizar(1000.0)["cs"], "1")


if __name__ == "__main__":
    unittest.main()
