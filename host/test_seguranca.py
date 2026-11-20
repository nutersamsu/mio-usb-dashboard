"""Bloco 1 de seguranca: HTTP so local/desligado, API do Proxmox com token, config invalida."""
import json
import os
import tempfile
import unittest

import fonte_pve
import server


class TestHttp(unittest.TestCase):
    def test_padrao_escuta_so_local(self):
        self.assertEqual(server.CONFIG_PADRAO["listen"], "127.0.0.1")

    def test_pode_desligar(self):
        self.assertFalse(server.http_ativo({"http": False}))
        self.assertTrue(server.http_ativo({}))


class TestConfigInvalida(unittest.TestCase):
    def test_json_quebrado_sai_com_78(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{lixo")
        try:
            with self.assertRaises(SystemExit) as c:
                server.carregar_config_ou_sair(f.name)
            self.assertEqual(c.exception.code, 78)
        finally:
            os.unlink(f.name)


class TestApiProxmox(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.tok = os.path.join(self.dir, "pve.token")
        with open(self.tok, "w") as f:
            f.write("mio@pve!painel=abc-123\n")
        self.pedidos = []

    def abrir(self, req, timeout):
        self.pedidos.append(req)
        return json.dumps({"data": [{"vmid": 100, "name": "server", "type": "qemu",
                                     "status": "running", "cpu": 0.1, "mem": 2 ** 30}]}).encode()

    def test_usa_token_no_cabecalho_e_devolve_lista(self):
        ler = fonte_pve.leitor_api("https://127.0.0.1:8006", self.tok, None, abrir=self.abrir)
        d = fonte_pve.ler_maquinas(ler)
        self.assertEqual(d["nvm"], "1/1")
        req = self.pedidos[0]
        self.assertEqual(req.get_header("Authorization"), "PVEAPIToken=mio@pve!painel=abc-123")
        self.assertTrue(req.full_url.endswith("/api2/json/cluster/resources?type=vm"))

    def test_token_ausente_nao_quebra(self):
        ler = fonte_pve.leitor_api("https://127.0.0.1:8006", "/nao/existe", None, abrir=self.abrir)
        self.assertEqual(fonte_pve.ler_maquinas(ler), {"nvm": "-"})
        self.assertEqual(self.pedidos, [])

    def test_resposta_sem_data_nao_quebra(self):
        ler = fonte_pve.leitor_api("https://x", self.tok, None, abrir=lambda r, timeout: b'{"erro":1}')
        self.assertEqual(fonte_pve.ler_maquinas(ler), {"nvm": "-"})

    def test_coletor_escolhe_api_quando_configurada(self):
        cfg = server.carregar_config(None)
        cfg["proxmox_api"] = {"url": "https://127.0.0.1:8006", "token_arquivo": self.tok}
        self.assertIsNot(server.Coletor(cfg).ler_pve, fonte_pve._pvesh)
        self.assertIs(server.Coletor(server.carregar_config(None)).ler_pve, fonte_pve._pvesh)


if __name__ == "__main__":
    unittest.main()
