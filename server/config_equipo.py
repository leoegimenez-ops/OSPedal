"""Configuración del equipo (no de los presets): audio, ruteo físico y pedalera MIDI.

Vive en `config/equipo.json` (PS_CONFIG para cambiarlo) y el mapa MIDI en `config/mapa-midi.json`
(la primera vez, copia de engine/ejemplo-mapa-midi.json). Son datos de ESTE equipo -- qué
interfaz tiene enchufada, qué entrada es la guitarra --, por eso no van al repo (.gitignore).

Se escribe a un temporal y se renombra: un corte de luz a mitad de camino deja la versión
anterior entera, nunca un JSON cortado (pedido del usuario: no perder ningún dato).
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
RUTA = Path(os.environ.get("PS_CONFIG", RAIZ / "config" / "equipo.json"))
RUTA_MAPA_MIDI = Path(os.environ.get("PS_MAPA_MIDI", RUTA.parent / "mapa-midi.json"))
_EJEMPLO_MAPA = RAIZ / "engine" / "ejemplo-mapa-midi.json"

POR_DEFECTO: dict[str, Any] = {
    # Servidor de audio (jackd). Se aplica al reiniciar el audio (lo arranca el servicio del OS).
    "audio": {"dispositivo": None, "frecuencia": 48000, "buffer": 256, "periodos": 2},
    # Qué entrada física alimenta a cada instrumento: {"guitarra1": "system:capture_1", ...}
    "entradas": {},
    # A qué salidas físicas va cada mezcla: {"pa": {"L": "system:playback_1", "R": ...}}
    "salidas": {},
    # Pedalera: qué dispositivo MIDI y qué instrumento controla.
    "midi": {"dispositivo": None, "linea": None},
}

_lock = threading.Lock()


def leer() -> dict[str, Any]:
    with _lock:
        datos = copy.deepcopy(POR_DEFECTO)
        try:
            crudo = json.loads(RUTA.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return datos
        for clave, valor in crudo.items():
            if isinstance(valor, dict) and isinstance(datos.get(clave), dict):
                datos[clave].update(valor)
            else:
                datos[clave] = valor
        return datos


def guardar(datos: dict[str, Any]) -> None:
    with _lock:
        RUTA.parent.mkdir(parents=True, exist_ok=True)
        temporal = RUTA.with_name(f".{RUTA.name}.tmp")
        temporal.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporal, RUTA)


def actualizar(seccion: str, cambios: dict[str, Any]) -> dict[str, Any]:
    datos = leer()
    datos.setdefault(seccion, {}).update(cambios)
    guardar(datos)
    return datos


def ruta_mapa_midi() -> Path:
    if not RUTA_MAPA_MIDI.exists():
        RUTA_MAPA_MIDI.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_EJEMPLO_MAPA, RUTA_MAPA_MIDI)
    return RUTA_MAPA_MIDI
