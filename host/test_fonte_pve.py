import json
import socket
import unittest

from fonte_pve import ler_maquinas, limpar, maquinas, testar_servicos

EXEMPLO = json.dumps([
    {"vmid": 103, "name": "xpenology-teste", "type": "qemu", "status": "stopped",
     "cpu": 0, "mem": 0, "maxmem": 4294967296},
    {"vmid": 100, "name": "server", "type": "qemu", "status": "running",
     "cpu": 0.18, "mem": 9771741184, "maxmem": 12884901888},
    {"vmid": 101, "name": "jellyfin", "type": "lxc", "status": "running",
     "cpu": 0.04, "mem": 1288490188, "maxmem": 3221225472},
])


class TestLimpar(unittest.TestCase):
    def test_tira_separadores(self):
        self.assertEqual(limpar("a|b;c"), "abc")

    def test_corta_e_tira_quebra(self):
        self.assertEqual(limpar("x" * 40 + "\n"), "x" * 24)


class TestMaquinas(unittest.TestCase):
    def test_ordem_e_formato(self):
        self.assertEqual(maquinas(EXEMPLO), [
            "server;VM 100;1;18%;9,1 GB",
            "jellyfin;CT 101;1;4%;1,2 GB",
            "xpenology-teste;VM 103;0;;desligada",
        ])

    def test_contagem(self):
        d = ler_maquinas(lambda: EXEMPLO)
        self.assertEqual(d["nvm"], "2/3")
        self.assertEqual(d["vm1"], "server;VM 100;1;18%;9,1 GB")

    def test_json_invalido_nao_quebra(self):
        self.assertEqual(ler_maquinas(lambda: "{lixo"), {"nvm": "-"})

    def test_comando_falha_nao_quebra(self):
        def falha():
            raise OSError("pvesh sumiu")
        self.assertEqual(ler_maquinas(falha), {"nvm": "-"})


class TestServicos(unittest.TestCase):
    def test_porta_aberta_e_fechada(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        aberta = srv.getsockname()[1]
        livre = socket.socket()
        livre.bind(("127.0.0.1", 0))
        fechada = livre.getsockname()[1]
        livre.close()
        d = testar_servicos([{"nome": "Aberto", "check": "tcp:127.0.0.1:%d" % aberta},
                             {"nome": "Fe|chado", "check": "tcp:127.0.0.1:%d" % fechada}])
        srv.close()
        self.assertTrue(d["sv1"].startswith("Aberto;1;"))
        self.assertEqual(d["sv2"], "Fechado;0;")
        self.assertEqual(d["nsv"], "1/2")


if __name__ == "__main__":
    unittest.main()
