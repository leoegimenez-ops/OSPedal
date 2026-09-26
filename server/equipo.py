"""Configuración de audio y MIDI del equipo (pantalla del OS: SYSTEM > Audio / MIDI).

Audio:
- Qué entrada física alimenta a cada instrumento y a qué salidas físicas va cada mezcla. Se
  aplica al instante (cables JACK) y queda guardado: al arrancar se vuelve a aplicar.
- Interfaz, frecuencia y buffer del servidor de audio: se guardan y se aplican al reiniciar el
  audio (en el OS, el servicio de jackd los lee de config/equipo.json).

MIDI:
- Qué pedalera usar y qué instrumento controla. Un hilo lee la pedalera (engine/midi_entrada.py)
  y ejecuta la acción del mapa en el controlador de ese instrumento; las pantallas se enteran
  por /sync como con cualquier otro cambio.
- "Learn": el usuario elige una acción, pisa un botón, y queda asignado (MapaMidi.aprender).
- Monitor: el último mensaje recibido, para ver que la pedalera llega.

Cambiar la configuración: solo desde la pantalla del equipo. Leerla: cualquiera (la app remota
no muestra estas pantallas, pero no hay nada secreto en qué entrada es la guitarra).
"""

from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from engine import audio_engine
from engine.midi_engine import Accion, Disparador, MapaMidi, MensajeMidi, TipoMensaje
from engine.midi_entrada import LectorMidi, listar_dispositivos
from server import config_equipo
from server.sistema import SISTEMA_REAL, exigir_local

router = APIRouter(tags=["equipo"])
LETRAS = "ABCDEFGH"


# -- Audio ------------------------------------------------------------------------------------

def _puertos_fisicos() -> dict[str, list[str]]:
    entradas, salidas = [], []
    for p in audio_engine.puertos_jack():
        if p.tipo != "audio" or not p.fisico:
            continue
        # Visto desde JACK: una entrada física (micrófono/guitarra) es un puerto de SALIDA
        # (produce audio hacia el sistema); una salida física es un puerto de ENTRADA.
        (entradas if p.direccion == "salida" else salidas).append(p.nombre_completo)
    return {"entradas": entradas, "salidas": salidas}


def _cliente_jack():
    from server import api   # noqa: PLC0415
    return api._ruteo().cliente


def _reconectar(cliente, destino_o_origen: str, nuevos: list[tuple[str, str]], es_destino: bool) -> None:
    """Deja a `destino_o_origen` conectado SOLO a lo que dicen `nuevos` (entre los físicos)."""
    fisicos = set(sum(_puertos_fisicos().values(), []))
    try:
        actuales = cliente.get_all_connections(destino_o_origen)
    except Exception:  # noqa: BLE001 -- el puerto todavía no existe (motor arrancando)
        return
    for otro in actuales:
        if otro.name in fisicos:
            par = (otro.name, destino_o_origen) if es_destino else (destino_o_origen, otro.name)
            try:
                cliente.disconnect(*par)
            except Exception:  # noqa: BLE001
                pass
    for origen, destino in nuevos:
        try:
            cliente.connect(origen, destino)
        except Exception:  # noqa: BLE001
            pass


def aplicar_entrada(linea: str) -> None:
    puerto = config_equipo.leer()["entradas"].get(linea)
    try:
        cliente = _cliente_jack()
    except HTTPException:
        return
    destino = f"ps_{linea}_pre_amp:in_0"
    _reconectar(cliente, destino, [(puerto, destino)] if puerto else [], es_destino=True)


def _puertos_bus(bus: str) -> dict[str, str]:
    from server import api   # noqa: PLC0415
    m = api._mixer()
    if m.modo_bus.get(bus) == "estereo":
        return {"L": f"pedalsistema_mixer:{bus}_L", "R": f"pedalsistema_mixer:{bus}_R"}
    return {"mono": f"pedalsistema_mixer:{bus}"}


def aplicar_salidas(bus: str) -> None:
    elegidos = config_equipo.leer()["salidas"].get(bus) or {}
    try:
        cliente = _cliente_jack()
        propios = _puertos_bus(bus)
    except HTTPException:
        return
    for canal, origen in propios.items():
        destino = elegidos.get(canal)
        _reconectar(cliente, origen, [(origen, destino)] if destino else [], es_destino=False)


@router.get("/audio/estado")
def estado_audio() -> dict[str, Any]:
    from server import api   # noqa: PLC0415
    frecuencia = audio_engine.frecuencia_muestreo_jack()
    buffer_ = audio_engine.tamano_buffer_jack()
    try:
        modos = api._mixer().modo_bus
    except HTTPException:
        modos = {}
    return {
        "jack": {"activo": audio_engine.jack_activo(), "frecuencia": frecuencia, "buffer": buffer_,
                 "latencia_ms": round(buffer_ / frecuencia * 1000, 2) if frecuencia and buffer_ else None},
        "interfaces": [{"id": d.hw, "nombre": f"{d.nombre_tarjeta} · {d.nombre_dispositivo}"}
                       for d in audio_engine.dispositivos_alsa("captura")],
        "fisicos": _puertos_fisicos(),
        "lineas": list(api.LINEAS),
        "buses": [{"id": b, "modo": modos.get(b, "mono")} for b in api.BUSES_MIXER],
        "config": config_equipo.leer(),
        "real": SISTEMA_REAL,
    }


class ElegirEntrada(BaseModel):
    linea: str
    puerto: str | None


@router.post("/audio/entradas")
def elegir_entrada(datos: ElegirEntrada, request: Request) -> dict:
    exigir_local(request)
    from server import api   # noqa: PLC0415
    if datos.linea not in api.LINEAS:
        raise HTTPException(404, f"línea desconocida: {datos.linea!r}")
    if datos.puerto and datos.puerto not in _puertos_fisicos()["entradas"]:
        raise HTTPException(400, f"No such input: {datos.puerto!r}")
    config_equipo.actualizar("entradas", {datos.linea: datos.puerto or None})
    aplicar_entrada(datos.linea)
    return {"ok": True}


class ElegirSalidas(BaseModel):
    bus: str
    puertos: dict[str, str | None]      # {"L": ..., "R": ...} o {"mono": ...}


@router.post("/audio/salidas")
def elegir_salidas(datos: ElegirSalidas, request: Request) -> dict:
    exigir_local(request)
    from server import api   # noqa: PLC0415
    if datos.bus not in api.BUSES_MIXER:
        raise HTTPException(404, f"mezcla desconocida: {datos.bus!r}")
    validas = _puertos_fisicos()["salidas"]
    for canal, puerto in datos.puertos.items():
        if canal not in ("L", "R", "mono"):
            raise HTTPException(400, "canal: L, R o mono")
        if puerto and puerto not in validas:
            raise HTTPException(400, f"No such output: {puerto!r}")
    config_equipo.actualizar("salidas", {datos.bus: {c: p for c, p in datos.puertos.items() if p}})
    aplicar_salidas(datos.bus)
    return {"ok": True}


class ServidorAudio(BaseModel):
    dispositivo: str | None = None
    frecuencia: int = 48000
    buffer: int = 256


@router.post("/audio/servidor")
def servidor_audio(datos: ServidorAudio, request: Request) -> dict:
    """Interfaz, frecuencia y buffer. Cambiar esto reinicia el audio (unos segundos en silencio),
    por eso se guarda y se aplica recién con "Restart audio" o al próximo arranque."""
    exigir_local(request)
    if datos.frecuencia not in (44100, 48000, 88200, 96000):
        raise HTTPException(400, "Sample rate: 44100, 48000, 88200 or 96000")
    if datos.buffer not in (32, 64, 128, 256, 512, 1024, 2048):
        raise HTTPException(400, "Buffer: 32 to 2048 (powers of two)")
    config_equipo.actualizar("audio", datos.model_dump())
    return {"ok": True, "latencia_ms": round(datos.buffer / datos.frecuencia * 1000, 2),
            "aplicar": "Restart audio to apply" if SISTEMA_REAL else
            "Saved. On the real system it applies when the audio restarts (development machine)"}


# -- MIDI -------------------------------------------------------------------------------------

class _EstadoMidi:
    def __init__(self) -> None:
        self.lector: LectorMidi | None = None
        self.mapa: MapaMidi | None = None
        self.ultimo: dict[str, Any] | None = None
        self.aprendiendo: dict[str, Any] | None = None
        self.lock = threading.Lock()


_midi = _EstadoMidi()


def _mapa() -> MapaMidi:
    if _midi.mapa is None:
        _midi.mapa = MapaMidi.cargar(config_equipo.ruta_mapa_midi())
    return _midi.mapa


def texto_accion(accion: str, parametro: int | None) -> str:
    textos = {
        "preset_en_banco": lambda p: f"Preset {LETRAS[p] if p is not None and p < 8 else p}",
        "cambiar_preset": lambda p: f"Preset #{(p or 0) + 1}",
        "preset_siguiente": lambda p: "Next preset", "preset_anterior": lambda p: "Previous preset",
        "banco_siguiente": lambda p: "Next bank", "banco_anterior": lambda p: "Previous bank",
        "toggle_stomp": lambda p: f"Stomp {LETRAS[p] if p is not None and p < 8 else p}",
        "escena": lambda p: f"Scene {LETRAS[p] if p is not None and p < 8 else p}",
        "modo": lambda p: f"Mode {p}", "afinador": lambda p: "Tuner", "tap_tempo": lambda p: "Tap tempo",
    }
    return textos.get(accion, lambda p: accion)(parametro)


def texto_disparador(d: Disparador) -> str:
    tipo = {"control_change": "CC", "note_on": "Note", "program_change": "PC"}.get(d.tipo.value, d.tipo.value)
    return f"{tipo} {d.numero}" + (f" · ch {d.canal}" if d.canal else "")


ACCIONES_ASIGNABLES = (
    [("preset_en_banco", i) for i in range(8)] + [("toggle_stomp", i) for i in range(8)]
    + [("escena", i) for i in range(8)]
    + [("preset_anterior", None), ("preset_siguiente", None), ("banco_anterior", None),
       ("banco_siguiente", None), ("afinador", None), ("tap_tempo", None)]
)


def _al_recibir(msg: MensajeMidi) -> None:
    """Hilo de la pedalera: aprender, o ejecutar la acción del mapa."""
    if msg.tipo is TipoMensaje.REALTIME:
        return
    _midi.ultimo = {"tipo": msg.tipo.value, "canal": msg.canal, "numero": msg.numero,
                    "valor": msg.valor, "cuando": time.time()}
    with _midi.lock:
        apr = _midi.aprendiendo
        if apr and time.time() < apr["hasta"] and msg.es_pulsacion:
            _mapa().aprender(msg, Accion(apr["accion"]), apr["parametro"])
            _mapa().guardar(config_equipo.ruta_mapa_midi())
            _midi.aprendiendo = None
            apr["hecho"] = True
            return
    resuelto = _mapa().resolver(msg)
    if not resuelto:
        return
    accion, parametro = resuelto
    linea = config_equipo.leer()["midi"].get("linea")
    from server import api   # noqa: PLC0415
    linea = linea if linea in api.LINEAS else next(iter(api.LINEAS))
    try:
        api._linea(linea).ejecutar(accion, parametro)
    except (HTTPException, ValueError, ConnectionError):
        return
    api.publicar_desde_hilo({"tipo": "linea", "linea": linea, "origen": "midi"})


def iniciar_midi() -> None:
    """Arranca (o re-arranca) el lector con la pedalera configurada."""
    if _midi.lector is not None:
        _midi.lector.detener()
        _midi.lector = None
    ruta = config_equipo.leer()["midi"].get("dispositivo")
    if ruta:
        _midi.lector = LectorMidi(ruta, _al_recibir)
        _midi.lector.iniciar()


def detener_midi() -> None:
    if _midi.lector is not None:
        _midi.lector.detener()
        _midi.lector = None


@router.get("/midi/estado")
def estado_midi() -> dict[str, Any]:
    from server import api   # noqa: PLC0415
    lector = _midi.lector
    apr = _midi.aprendiendo
    if apr and time.time() > apr["hasta"]:
        _midi.aprendiendo = apr = None
    return {
        "dispositivos": listar_dispositivos(),
        "config": config_equipo.leer()["midi"],
        "lineas": list(api.LINEAS),
        "conectado": bool(lector and lector.conectado),
        "error": lector.error if lector else None,
        "ultimo": _midi.ultimo,
        "aprendiendo": ({"accion": apr["accion"], "parametro": apr["parametro"],
                         "texto": texto_accion(apr["accion"], apr["parametro"]),
                         "segundos": max(0, round(apr["hasta"] - time.time()))} if apr else None),
        "asignaciones": [
            {"tipo": a.disparador.tipo.value, "numero": a.disparador.numero, "canal": a.disparador.canal,
             "disparador": texto_disparador(a.disparador), "accion": a.accion.value,
             "parametro": a.parametro, "texto": texto_accion(a.accion.value, a.parametro)}
            for a in _mapa().asignaciones
        ],
        "acciones": [{"accion": a, "parametro": p, "texto": texto_accion(a, p)} for a, p in ACCIONES_ASIGNABLES],
    }


class ConfigMidi(BaseModel):
    dispositivo: str | None = None
    linea: str | None = None


@router.post("/midi/config")
def config_midi(datos: ConfigMidi, request: Request) -> dict:
    exigir_local(request)
    from server import api   # noqa: PLC0415
    if datos.linea and datos.linea not in api.LINEAS:
        raise HTTPException(404, f"línea desconocida: {datos.linea!r}")
    config_equipo.actualizar("midi", {"dispositivo": datos.dispositivo, "linea": datos.linea})
    iniciar_midi()
    return {"ok": True}


class Aprender(BaseModel):
    accion: str
    parametro: int | None = None


@router.post("/midi/aprender")
def aprender(datos: Aprender, request: Request) -> dict:
    exigir_local(request)
    try:
        Accion(datos.accion)
    except ValueError:
        raise HTTPException(400, f"acción desconocida: {datos.accion!r}")
    _midi.aprendiendo = {"accion": datos.accion, "parametro": datos.parametro, "hasta": time.time() + 15}
    return {"ok": True, "segundos": 15}


@router.post("/midi/cancelar")
def cancelar(request: Request) -> dict:
    exigir_local(request)
    _midi.aprendiendo = None
    return {"ok": True}


class Olvidar(BaseModel):
    tipo: str
    numero: int
    canal: int = 0


@router.post("/midi/olvidar")
def olvidar(datos: Olvidar, request: Request) -> dict:
    exigir_local(request)
    try:
        disparador = Disparador(TipoMensaje(datos.tipo), datos.numero, datos.canal)
    except ValueError:
        raise HTTPException(400, "tipo de mensaje desconocido")
    if not _mapa().olvidar(disparador):
        raise HTTPException(404, "No such assignment")
    _mapa().guardar(config_equipo.ruta_mapa_midi())
    return {"ok": True}
