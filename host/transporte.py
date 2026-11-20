"""Como a linha chega ao Mio. A porta vem do config ("serial.porta"):

  /dev/mio, /dev/ttyUSB0  Linux com o driver ipaq (caminho testado, padrao)
  COM5                    Windows, se algum driver criar uma porta COM para o Mio (pyserial)
  usb                     USB direto pela libusb (pyusb), sem driver de porta serial.
                          No Windows: instalar o driver WinUSB no Mio com o Zadig.

O modo "usb" faz o mesmo que o driver ipaq do Linux: interface 0, controle 0x22/0x21 valor 1
para "acordar" o aparelho, escrita no endpoint bulk 0x04 e leitura no 0x81.
"""
import os
import time

VID, PID = 0x3340, 0x043A           # Mio DigiWalker USB Sync (C250)
EP_SAIDA, EP_ENTRADA = 0x04, 0x81


def tipo(porta, nome_so=None):
    nome_so = nome_so or os.name
    if porta.lower() == "usb":
        return "usb"
    if nome_so == "nt" or porta.upper().startswith("COM"):
        return "pyserial"
    return "posix"


class TransportePosix:
    """Linux/Unix: termios cru (o que ja rodava no pve)."""
    def __init__(self, porta, baud):
        import termios
        self._t = termios
        self.fd = os.open(porta, os.O_RDWR | os.O_NOCTTY)
        vel = getattr(termios, "B%d" % baud, termios.B115200)
        at = termios.tcgetattr(self.fd)
        at[0] = 0; at[1] = 0                      # iflag, oflag: cru
        at[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        at[3] = 0                                 # lflag: sem eco/canonico
        at[4] = at[5] = vel
        termios.tcsetattr(self.fd, termios.TCSANOW, at)

    def escrever(self, dados):
        os.write(self.fd, dados)

    def descartar_entrada(self):
        self._t.tcflush(self.fd, self._t.TCIFLUSH)

    def fechar(self):
        os.close(self.fd)


class TransportePySerial:
    """Windows (COMx) ou qualquer sistema com pyserial."""
    def __init__(self, porta, baud):
        import serial                              # pip install pyserial
        self.s = serial.Serial(porta, baud, timeout=0, write_timeout=1)

    def escrever(self, dados):
        self.s.write(dados)

    def descartar_entrada(self):
        self.s.reset_input_buffer()

    def fechar(self):
        self.s.close()


class TransporteUsb:
    """USB direto pela libusb (pip install pyusb; no Windows, driver WinUSB pelo Zadig)."""
    def __init__(self, vid=VID, pid=PID, usb=None, espera=0.5):
        if usb is None:
            import usb.core                        # noqa: F401
            import usb.util                        # noqa: F401
            import usb as usb_mod
            usb = usb_mod
        self.usb = usb
        self.dev = usb.core.find(idVendor=vid, idProduct=pid)
        if self.dev is None:
            raise OSError("Mio nao encontrado na USB (%04x:%04x)" % (vid, pid))
        try:                                       # Linux: tira o ipaq do caminho
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
        except (NotImplementedError, usb.core.USBError):
            pass                                   # Windows nao tem driver de kernel aqui
        try:
            self.dev.set_configuration()
        except usb.core.USBError:
            pass                                   # ja configurado
        usb.util.claim_interface(self.dev, 0)
        for _ in range(10):                        # o ipaq repete ate o aparelho aceitar
            try:
                self.dev.ctrl_transfer(0x21, 0x22, 0x1, 0, None, timeout=100)
                break
            except usb.core.USBError:
                time.sleep(espera)
        else:
            raise OSError("o Mio nao respondeu ao comando de abertura")

    def escrever(self, dados):
        self.dev.write(EP_SAIDA, dados, timeout=1000)

    def descartar_entrada(self):
        for _ in range(8):                         # o "MIO OLA" chega em pedacos de 64 bytes
            try:
                self.dev.read(EP_ENTRADA, 64, timeout=10)
            except self.usb.core.USBError:
                return

    def fechar(self):
        try:
            self.usb.util.release_interface(self.dev, 0)
        finally:
            self.usb.util.dispose_resources(self.dev)


def abrir(porta, baud=115200):
    t = tipo(porta)
    if t == "usb":
        return TransporteUsb()
    if t == "pyserial":
        return TransportePySerial(porta, baud)
    return TransportePosix(porta, baud)
