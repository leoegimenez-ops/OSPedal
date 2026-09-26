"""Lectura de la pedalera MIDI real (el backend que faltaba de engine/midi_engine.py).

Lee el dispositivo MIDI crudo de ALSA (`/dev/snd/midiC<tarjeta>D<disp>`): cualquier pedalera USB
class-compliant aparece ahí sin drivers. Son bytes MIDI tal cual, así que alcanza con abrir el
archivo y pasárselos a `ParserMidi` -- sin dependencias (ni rtmidi ni ALSA seq).

Corre en un hilo propio. Si la pedalera se desenchufa, reintenta cada 2 s y sigue sola cuando
vuelve (en vivo alguien pisa el cable). `select` con timeout permite detenerlo limpio.

Para pruebas sin hardware, PS_MIDI_EXTRA="/ruta/a/un/fifo" agrega esa ruta a la lista como si
fuera una pedalera (un FIFO de Linux se lee igual que el dispositivo crudo).
"""

from __future__ import annotations

import glob
import os
import re
import select
import threading
import time
from pathlib import Path
from typing import Callable

from engine.midi_engine import MensajeMidi, ParserMidi


def listar_dispositivos() -> list[dict[str, str]]:
    nombres: dict[int, str] = {}
    try:
        for linea in Path("/proc/asound/cards").read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*(\d+)\s+\[[^\]]*\]:\s*(.*?)\s+-\s+(.*)", linea)
            if m:
                nombres[int(m.group(1))] = m.group(3).strip()
    except OSError:
        pass
    salida = []
    for ruta in sorted(glob.glob("/dev/snd/midiC*D*")):
        m = re.search(r"midiC(\d+)D(\d+)", ruta)
        tarjeta, disp = int(m.group(1)), int(m.group(2))
        salida.append({"ruta": ruta, "id": f"hw:{tarjeta},{disp}",
                       "nombre": nombres.get(tarjeta, f"MIDI {tarjeta}:{disp}")})
    for extra in filter(None, os.environ.get("PS_MIDI_EXTRA", "").split(":")):
        salida.append({"ruta": extra, "id": extra, "nombre": f"Test device ({Path(extra).name})"})
    return salida


class LectorMidi:
    def __init__(self, ruta: str, al_recibir: Callable[[MensajeMidi], None]) -> None:
        self.ruta = ruta
        self.al_recibir = al_recibir
        self.conectado = False
        self.error: str | None = None
        self._parar = threading.Event()
        self._hilo = threading.Thread(target=self._bucle, name=f"midi:{ruta}", daemon=True)

    def iniciar(self) -> None:
        self._hilo.start()

    def detener(self) -> None:
        self._parar.set()
        self._hilo.join(timeout=2)

    def _bucle(self) -> None:
        while not self._parar.is_set():
            try:
                fd = os.open(self.ruta, os.O_RDONLY | os.O_NONBLOCK)
            except OSError as exc:
                self.conectado = False
                self.error = f"Can't open {self.ruta}: {exc.strerror or exc}"
                self._parar.wait(2.0)
                continue
            self.conectado, self.error = True, None
            parser = ParserMidi()
            try:
                while not self._parar.is_set():
                    listos, _, _ = select.select([fd], [], [], 0.25)
                    if not listos:
                        continue
                    try:
                        datos = os.read(fd, 256)
                    except BlockingIOError:
                        continue
                    if not datos:
                        # FIFO sin escritor (o dispositivo que se fue): esperar sin quemar CPU.
                        time.sleep(0.05)
                        continue
                    for mensaje in parser.alimentar(datos):
                        try:
                            self.al_recibir(mensaje)
                        except Exception:  # noqa: BLE001 -- un error de acción no mata la pedalera
                            pass
            except OSError as exc:
                self.error = f"Device lost: {exc.strerror or exc}"
            finally:
                self.conectado = False
                os.close(fd)
            self._parar.wait(2.0)
