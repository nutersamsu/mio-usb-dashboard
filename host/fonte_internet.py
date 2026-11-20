"""Teste de queda da internet (ping a partir do pve) e horario de silencio do alarme."""
import subprocess
import threading


def _ping(alvo):
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "2", "-n", alvo],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def em_silencio(hora, faixa):
    """faixa "23-7": silencio das 23h ate antes das 7h. Vazia/invalida = nunca."""
    try:
        ini, fim = (int(x) for x in faixa.split("-"))
    except (ValueError, AttributeError):
        return False
    if ini <= fim:
        return ini <= hora < fim
    return hora >= ini or hora < fim


class TesteInternet:
    def __init__(self, alvos=("1.1.1.1", "8.8.8.8"), falhas=3, ping=_ping):
        self.alvos, self.falhas, self.ping = list(alvos), falhas, ping
        self._seguidas = 0
        self._fora_desde = None

    def registrar(self, ok, agora):
        if ok:
            self._seguidas = 0
            self._fora_desde = None
            return
        self._seguidas += 1
        if self._seguidas >= self.falhas and self._fora_desde is None:
            self._fora_desde = agora

    def testar(self, agora):
        """Pinga todos os alvos em paralelo; basta um responder."""
        res = [False] * len(self.alvos)

        def um(i, alvo):
            res[i] = self.ping(alvo)

        fios = [threading.Thread(target=um, args=(i, a)) for i, a in enumerate(self.alvos)]
        for f in fios:
            f.start()
        for f in fios:
            f.join()
        self.registrar(any(res), agora)

    def minutos_fora(self, agora):
        return 0 if self._fora_desde is None else int((agora - self._fora_desde) // 60)

    def estado(self, agora):
        return {"net": "0" if self._fora_desde is not None else "1"}
