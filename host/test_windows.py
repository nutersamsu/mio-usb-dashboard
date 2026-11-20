"""Suporte ao Windows (experimental): saida do ping e do route do Windows, escolha do transporte
e USB direto (libusb) com um dispositivo falso. Roda em qualquer sistema."""
import types
import unittest

import fonte_rede
import transporte

PING_PT = """
Disparando 1.1.1.1 com 32 bytes de dados:
Resposta de 1.1.1.1: bytes=32 tempo=11ms TTL=57
Resposta de 1.1.1.1: bytes=32 tempo=13ms TTL=57
Esgotado o tempo limite do pedido.

Estatísticas do Ping para 1.1.1.1:
    Pacotes: Enviados = 3, Recebidos = 2, Perdidos = 1 (33% de perda),
"""
PING_IT = """
Esecuzione di Ping 8.8.8.8 con 32 byte di dati:
Risposta da 8.8.8.8: byte=32 durata=20ms TTL=117
Risposta da 8.8.8.8: byte=32 durata<1ms TTL=117
Risposta da 8.8.8.8: byte=32 durata=22ms TTL=117
"""
PING_INALCANCAVEL = """
Resposta de 192.168.1.1: Host de destino inacessível.
Resposta de 192.168.1.1: Host de destino inacessível.
"""
ROUTE_PRINT = """
===========================================================================
Rotas ativas:
Destino de rede       Máscara        Ender. gateway    Interface   Custo
          0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.50     25
===========================================================================
"""


class TestPingWindows(unittest.TestCase):
    def test_portugues_com_perda(self):
        self.assertEqual(fonte_rede.ler_ping_windows(PING_PT, 3), (3, 2, 12.0))

    def test_italiano_e_menor_que_1ms(self):
        self.assertEqual(fonte_rede.ler_ping_windows(PING_IT, 3), (3, 3, 14.3))   # (20 + 1 + 22) / 3

    def test_inalcancavel_nao_e_resposta(self):
        # o ping do Windows devolve 0 nesse caso; so 'TTL=' prova resposta
        self.assertEqual(fonte_rede.ler_ping_windows(PING_INALCANCAVEL, 2), (2, 0, None))

    def test_um_ping(self):
        self.assertEqual(fonte_rede.ms_de_um_ping(PING_IT.splitlines()[2]), 20.0)
        self.assertIsNone(fonte_rede.ms_de_um_ping(PING_INALCANCAVEL))


class TestRouteWindows(unittest.TestCase):
    def test_gateway(self):
        self.assertEqual(fonte_rede.gateway_windows(ROUTE_PRINT), "192.168.1.1")
        self.assertIsNone(fonte_rede.gateway_windows("lixo"))


class TestEscolha(unittest.TestCase):
    def test_tipo(self):
        self.assertEqual(transporte.tipo("usb"), "usb")
        self.assertEqual(transporte.tipo("COM5"), "pyserial")
        self.assertEqual(transporte.tipo("/dev/mio", nome_so="posix"), "posix")
        self.assertEqual(transporte.tipo("/dev/ttyUSB0", nome_so="nt"), "pyserial")


class DispositivoFalso:
    def __init__(self, ctrl_falhas=0):
        self.escrito, self.ctrl, self.ctrl_falhas = [], 0, ctrl_falhas
        self.entrada = [b"MIO OLA 1\r\n"]

    def is_kernel_driver_active(self, i):
        return True

    def detach_kernel_driver(self, i):
        self.solto = True

    def set_configuration(self):
        pass

    def ctrl_transfer(self, tipo, req, valor, indice, dados, timeout):
        self.ctrl += 1
        if self.ctrl <= self.ctrl_falhas:
            raise UsbErro("pipe")
        self.ultimo_ctrl = (tipo, req, valor, indice)

    def write(self, ep, dados, timeout):
        self.escrito.append((ep, bytes(dados)))
        return len(dados)

    def read(self, ep, tam, timeout):
        if self.entrada:
            return self.entrada.pop(0)
        raise UsbErro("timeout")


class UsbErro(Exception):
    pass


def usb_falso(disp):
    core = types.SimpleNamespace(find=lambda idVendor, idProduct: disp, USBError=UsbErro)
    util = types.SimpleNamespace(claim_interface=lambda d, i: None, release_interface=lambda d, i: None,
                                 dispose_resources=lambda d: None)
    return types.SimpleNamespace(core=core, util=util)


class TestUsbDireto(unittest.TestCase):
    def test_acorda_escreve_e_descarta(self):
        d = DispositivoFalso(ctrl_falhas=2)
        t = transporte.TransporteUsb(usb=usb_falso(d), espera=0)
        t.escrever(b"D|h=1\r\n")
        t.descartar_entrada()
        t.fechar()
        self.assertTrue(d.solto)
        self.assertEqual(d.ultimo_ctrl, (0x21, 0x22, 1, 0))   # o mesmo que o driver ipaq manda
        self.assertEqual(d.escrito, [(0x04, b"D|h=1\r\n")])
        self.assertEqual(d.entrada, [])

    def test_sem_mio(self):
        u = usb_falso(None)
        with self.assertRaises(OSError):
            transporte.TransporteUsb(usb=u, espera=0)


if __name__ == "__main__":
    unittest.main()


class TestPosixComPty(unittest.TestCase):
    """O caminho do Linux (termios) continua igual: testa com um pseudo-terminal."""
    def test_escreve_e_descarta(self):
        import os
        if os.name != "posix":
            self.skipTest("so Linux/Unix")
        mestre, escravo = os.openpty()
        nome = os.ttyname(escravo)
        t = transporte.TransportePosix(nome, 115200)
        t.escrever(b"D|h=12:00\r\n")
        self.assertEqual(os.read(mestre, 64), b"D|h=12:00\r\n")
        os.write(mestre, b"MIO OLA 1\r\n")
        t.descartar_entrada()                  # nao pode travar nem levantar erro
        t.fechar()
        os.close(mestre)
        os.close(escravo)
