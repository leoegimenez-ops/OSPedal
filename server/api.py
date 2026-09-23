"""Puente HTTP/WebSocket entre el motor Guitarix y los clientes remotos (GUI PyQt6, PWA).

Guitarix habla JSON-RPC 2.0 sobre un socket TCP plano, no HTTP (ver
`docs/guitarix-integracion.md`) — este módulo es la capa que expone ese mismo control por HTTP
REST y WebSocket, hablando el socket directamente en vez de pasar por `websockify` como hace la
WebUI de referencia del propio Guitarix.

Arranque:

    uvicorn server.api:app --host 0.0.0.0 --port 8000

Variables de entorno: `GX_HOST` (default `127.0.0.1`), `GX_PORT` (default `7000`).

Esqueleto de Fase 5, verificado extremo a extremo (23/09/2026) contra un Guitarix 0.47.0 real
corriendo bajo WSL2: `/estado`, `/bancos`, `/bancos/{banco}/presets`, `/preset` (POST) y
`/parametros` (GET/POST) probados con curl contra un servidor `uvicorn` real, no solo con
`TestClient`. `/eventos` (WebSocket) probado con un cliente `websockets` real, confirmando que un
`preset_changed` disparado por `/preset` efectivamente llega por el socket.

Hallazgo de esta verificación que corrige la doc previa: `banks` **no** devuelve una lista de
nombres — devuelve objetos `{"name", "mutable", "type", "presets"}`, con los presets de cada
banco ya incluidos ahí mismo (ver `docs/guitarix-rpc-methods.md`).

`/mezclador/*` expone `engine/mixer.py` (ver ese módulo y `docs/mezclas-en-vivo.md`): la matriz de
ganancia+paneo fuente×bus que arma las mezclas de monitor independientes, cada bus mono o
estéreo según se configure. Variables de entorno `MIXER_FUENTES`/`MIXER_BUSES` (listas separadas
por coma) — default: cuatro líneas de instrumento (`guitarra1,guitarra2,bajo,voz`) y cinco buses
(`monitor1,monitor2,monitor3,monitor4,pa`), todos mono salvo que `MIXER_MODO_BUSES` diga lo
contrario (`"pa:estereo"`, por ejemplo). El mezclador es un cliente JACK real (necesita jackd
corriendo) — a diferencia de `_motor()`, si no hay servidor JACK esto da 503 recién en el primer
uso, no al arrancar la API.

`/eventos` corre `GuitarixRPC.eventos()` (generador sincrónico, bloqueante sobre un socket) en un
hilo aparte con `asyncio.to_thread`, y en paralelo escucha la desconexión del cliente con
`ws.receive()` — así que cerrar el cliente corta el loop enseguida, no hace falta esperar al
próximo evento. El hilo de lectura del socket en sí no se puede cancelar de verdad (Python no
interrumpe hilos a la fuerza): al cerrar, sigue vivo hasta que su propia llamada a
`GuitarixRPC.eventos(timeout=_TIMEOUT_EVENTOS)` expira sola, así que el proceso puede tardar hasta
`_TIMEOUT_EVENTOS` segundos de más en cerrar esa conexión de Guitarix al finalizar. Aceptable para
un primer esqueleto; si el volumen de conexiones lo justifica, la solución de fondo es un lector
de socket async dedicado en vez de reusar el cliente sincrónico.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from engine.mixer import ErrorDeMezclador, MezcladorJack
from engine.rpc_client import GuitarixError, GuitarixRPC

HOST_GUITARIX = os.environ.get("GX_HOST", "127.0.0.1")
PUERTO_GUITARIX = int(os.environ.get("GX_PORT", "7000"))
_TIMEOUT_EVENTOS = 5.0

FUENTES_MIXER = [f.strip() for f in os.environ.get(
    "MIXER_FUENTES", "guitarra1,guitarra2,bajo,voz").split(",") if f.strip()]
BUSES_MIXER = [b.strip() for b in os.environ.get(
    "MIXER_BUSES", "monitor1,monitor2,monitor3,monitor4,pa").split(",") if b.strip()]
# "bus:modo,bus:modo" -- solo hace falta listar los que no son "mono" (el default).
MODO_BUSES_MIXER = dict(
    par.split(":", 1) for par in os.environ.get("MIXER_MODO_BUSES", "").split(",") if ":" in par
)

_gx: GuitarixRPC | None = None
_mezclador: MezcladorJack | None = None


def _mixer() -> MezcladorJack:
    global _mezclador
    if _mezclador is None:
        try:
            m = MezcladorJack(FUENTES_MIXER, BUSES_MIXER, modo_buses=MODO_BUSES_MIXER)
            m.iniciar()
        except ErrorDeMezclador as exc:
            raise HTTPException(503, f"No se pudo iniciar el mezclador: {exc}")
        _mezclador = m
    return _mezclador


def _motor() -> GuitarixRPC:
    """Conexión RPC compartida por los endpoints REST (no por el WebSocket, ver más abajo)."""
    global _gx
    if _gx is None:
        _gx = GuitarixRPC(HOST_GUITARIX, PUERTO_GUITARIX)
    try:
        _gx.conectar()
    except OSError as exc:
        raise HTTPException(
            503, f"No se pudo conectar a Guitarix en {HOST_GUITARIX}:{PUERTO_GUITARIX}: {exc}"
        )
    return _gx


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    if _gx is not None:
        _gx.cerrar()
    if _mezclador is not None:
        _mezclador.detener()


app = FastAPI(title="PedalSistema", lifespan=lifespan)


class CambiarPreset(BaseModel):
    banco: str
    preset: str


class FijarParametros(BaseModel):
    pares: dict[str, Any]


class FijarGanancia(BaseModel):
    fuente: str
    bus: str
    valor: float


class FijarPaneo(BaseModel):
    fuente: str
    bus: str
    valor: float


@app.get("/salud")
def salud() -> dict:
    """No toca Guitarix — solo confirma que el proceso de la API está vivo."""
    return {"ok": True}


@app.get("/estado")
def estado() -> dict:
    gx = _motor()
    try:
        return {
            "version": gx.version(),
            "estado": gx.estado(),
            "carga_cpu": gx.carga_cpu(),
        }
    except GuitarixError as exc:
        raise HTTPException(502, str(exc))


@app.get("/bancos")
def bancos() -> Any:
    gx = _motor()
    try:
        return gx.bancos()
    except GuitarixError as exc:
        raise HTTPException(502, str(exc))


@app.get("/bancos/{banco}/presets")
def presets(banco: str) -> Any:
    gx = _motor()
    try:
        return gx.presets(banco)
    except GuitarixError as exc:
        raise HTTPException(502, str(exc))


@app.post("/preset")
def cambiar_preset(datos: CambiarPreset) -> dict:
    """Notificación pura hacia Guitarix (sin round-trip): ver `GuitarixRPC.set_preset`."""
    gx = _motor()
    gx.set_preset(datos.banco, datos.preset)
    return {"ok": True}


@app.get("/parametros")
def obtener_parametros(nombres: str) -> Any:
    """`nombres` separados por coma: `/parametros?nombres=amp.gain,eq.peak1`."""
    gx = _motor()
    lista = [n.strip() for n in nombres.split(",") if n.strip()]
    if not lista:
        raise HTTPException(400, "nombres vacío")
    try:
        return gx.obtener(*lista)
    except GuitarixError as exc:
        raise HTTPException(502, str(exc))


@app.post("/parametros")
def fijar_parametros(datos: FijarParametros) -> dict:
    gx = _motor()
    pares: list[Any] = []
    for nombre, valor in datos.pares.items():
        pares.extend((nombre, valor))
    try:
        gx.fijar(*pares)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.get("/mezclador/matriz")
def matriz_mezclador() -> dict:
    """Ganancia+paneo fuente×bus actual, más las fuentes/buses disponibles y el modo
    (mono/estéreo) de cada bus."""
    m = _mixer()
    return {"fuentes": m.fuentes, "buses": m.buses, "modo_bus": m.modo_bus, "matriz": m.matriz()}


@app.post("/mezclador/ganancia")
def fijar_ganancia_mezclador(datos: FijarGanancia) -> dict:
    m = _mixer()
    try:
        m.fijar_ganancia(datos.fuente, datos.bus, datos.valor)
    except ErrorDeMezclador as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.post("/mezclador/paneo")
def fijar_paneo_mezclador(datos: FijarPaneo) -> dict:
    """`valor`: -1 (izquierda) .. 0 (centro) .. 1 (derecha). Afecta tanto a buses estéreo (imagen
    real) como mono (balance/presencia en el fold-down) — ver `engine/mixer.py`."""
    m = _mixer()
    try:
        m.fijar_paneo(datos.fuente, datos.bus, datos.valor)
    except ErrorDeMezclador as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


def _proximo_evento(gx: GuitarixRPC) -> dict | None:
    for evento in gx.eventos(timeout=_TIMEOUT_EVENTOS):
        return evento
    return None


@app.websocket("/eventos")
async def eventos(ws: WebSocket) -> None:
    """Suscribe a todos los eventos del motor y los reenvía como JSON por el socket.

    Usa una conexión RPC propia, separada de la que usan los endpoints REST, para que un
    WebSocket lento o colgado no bloquee las llamadas HTTP normales. Corre `_proximo_evento` en
    un hilo aparte y en paralelo espera `ws.receive()`, así que una desconexión del cliente corta
    el loop de inmediato en vez de esperar al próximo evento — ver limitación en el docstring del
    módulo sobre por qué el hilo en sí puede tardar un poco más en terminar.
    """
    await ws.accept()
    gx = GuitarixRPC(HOST_GUITARIX, PUERTO_GUITARIX)
    try:
        gx.conectar()
    except OSError as exc:
        await ws.close(code=1011, reason=str(exc))
        return
    gx.suscribir("all")

    tarea_recibir = asyncio.ensure_future(ws.receive())
    tarea_evento = asyncio.ensure_future(asyncio.to_thread(_proximo_evento, gx))
    try:
        while True:
            listas, _ = await asyncio.wait(
                {tarea_recibir, tarea_evento}, return_when=asyncio.FIRST_COMPLETED
            )
            if tarea_recibir in listas:
                mensaje = tarea_recibir.result()
                if mensaje.get("type") == "websocket.disconnect":
                    break
                tarea_recibir = asyncio.ensure_future(ws.receive())
            if tarea_evento in listas:
                evento = tarea_evento.result()
                if evento is not None:
                    await ws.send_json(evento)
                tarea_evento = asyncio.ensure_future(asyncio.to_thread(_proximo_evento, gx))
    except WebSocketDisconnect:
        pass
    finally:
        tarea_recibir.cancel()
        tarea_evento.cancel()
        gx.cerrar()
