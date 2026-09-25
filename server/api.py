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

`/app/` sirve la PWA de control remoto (`mobile/`) desde esta misma app, vía `StaticFiles`.

`/lineas/*` conecta `engine/controlador.py` (`ControladorEscenario`) a la API -- hasta acá
`/preset`/`/parametros` solo hablaban con el Guitarix crudo, sin pasar por nuestra propia setlist
(bancos/presets/escenas/stomps/tempo). Una línea = una instancia de Guitarix (su propio puerto) +
su propia setlist, configurable con `LINEAS` (default: reusa `MIXER_FUENTES` con puertos
secuenciales desde `GX_PORT` y la setlist de ejemplo del repo). `GET /lineas/{linea}/estado` y
`POST /lineas/{linea}/accion` (con el valor de texto de cualquier `Accion` del enum).

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
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.categorias import CATEGORIAS, categoria, fijos, insertables, nombres
from engine.controlador import ControladorEscenario
from engine.midi_engine import Accion
from engine.mixer import ErrorDeMezclador, MezcladorJack
from engine.rpc_client import GuitarixError, GuitarixRPC
from presets.preset_manager import ErrorDeSetlist, Setlist

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

_RUTA_SETLIST_EJEMPLO = Path(__file__).resolve().parent.parent / "presets" / "ejemplo-setlist.json"
# Setlists de trabajo, una por línea. El botón de guardar del GRID escribe acá -- nunca sobre la
# setlist de ejemplo del repo. Si la de una línea no existe todavía, se crea copiando el ejemplo.
DIR_SETLISTS = Path(os.environ.get(
    "SETLISTS_DIR", Path(__file__).resolve().parent.parent / "presets" / "setlists"))


def _config_lineas() -> dict[str, dict[str, Any]]:
    """Una línea de instrumento = una instancia de Guitarix (su propio puerto) + su propia
    setlist. `LINEAS`: `"nombre:puerto:ruta_setlist,..."` (puerto y ruta opcionales). Sin la
    variable, reusa `FUENTES_MIXER` con puertos secuenciales desde `GX_PORT`, y cada línea usa
    `SETLISTS_DIR/<nombre>.json` (arranca como copia de la setlist de ejemplo del repo)."""
    crudo = os.environ.get("LINEAS")
    config: dict[str, dict[str, Any]] = {}
    if crudo:
        for parte in crudo.split(","):
            if not parte.strip():
                continue
            campos = parte.split(":")
            nombre = campos[0].strip()
            puerto = int(campos[1]) if len(campos) > 1 and campos[1].strip() else PUERTO_GUITARIX
            ruta = (Path(campos[2]) if len(campos) > 2 and campos[2].strip()
                    else DIR_SETLISTS / f"{nombre}.json")
            config[nombre] = {"puerto": puerto, "setlist": ruta}
    else:
        for i, nombre in enumerate(FUENTES_MIXER):
            config[nombre] = {"puerto": PUERTO_GUITARIX + i, "setlist": DIR_SETLISTS / f"{nombre}.json"}
    return config


LINEAS = _config_lineas()

_gx: GuitarixRPC | None = None
_mezclador: MezcladorJack | None = None
_controladores: dict[str, ControladorEscenario] = {}
_cache_plugins: dict[str, list[dict[str, Any]]] = {}


def _linea(nombre: str) -> ControladorEscenario:
    """`ControladorEscenario` de una línea, conectando y cargando su setlist recién en el
    primer uso -- misma idea que `_motor()`/`_mixer()`."""
    if nombre not in LINEAS:
        raise HTTPException(404, f"línea desconocida: {nombre!r}. Válidas: {list(LINEAS)}")
    if nombre not in _controladores:
        cfg = LINEAS[nombre]
        gx = GuitarixRPC(HOST_GUITARIX, cfg["puerto"])
        try:
            gx.conectar()
        except OSError as exc:
            raise HTTPException(
                503, f"No se pudo conectar la línea {nombre!r} en el puerto {cfg['puerto']}: {exc}"
            )
        ruta = Path(cfg["setlist"])
        if not ruta.exists():
            ruta.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(_RUTA_SETLIST_EJEMPLO, ruta)
        try:
            setlist = Setlist.cargar(ruta)
        except ErrorDeSetlist as exc:
            gx.cerrar()
            raise HTTPException(500, f"Setlist inválida para la línea {nombre!r}: {exc}")
        _controladores[nombre] = ControladorEscenario(setlist, gx)
    return _controladores[nombre]


def _plugins(nombre: str) -> list[dict[str, Any]]:
    """`pluginlist` de la línea, cacheado: no cambia mientras el motor corre (son los plugins
    compilados en esa versión de Guitarix)."""
    if nombre not in _cache_plugins:
        _cache_plugins[nombre] = _linea(nombre).rpc.plugins()
    return _cache_plugins[nombre]


def _guardar_setlist(nombre: str) -> None:
    _linea(nombre).setlist.guardar(LINEAS[nombre]["setlist"])


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
    for ctrl in _controladores.values():
        ctrl.rpc.cerrar()


app = FastAPI(title="PedalSistema", lifespan=lifespan)


@app.exception_handler(GuitarixError)
async def _manejar_error_guitarix(_request: Request, exc: GuitarixError) -> JSONResponse:
    """El motor respondió, pero con un error RPC -- distinto de perder la conexión."""
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(ConnectionError)
async def _manejar_desconexion(_request: Request, exc: ConnectionError) -> JSONResponse:
    """Se cae la conexión a mitad de un pedido (Guitarix crasheó, se mató el proceso, etc.).

    Antes esto no lo atrapaba nada y daba 500 -- confirmado en vivo (24-25/09/2026): un Guitarix
    caído de noche dejó la API respondiendo 500 sin fin hasta reiniciar el proceso entero. Ahora
    `GuitarixRPC._enviar()`/`_leer_linea()` cierran el socket muerto al detectar el corte, así que
    el *próximo* pedido reconecta solo -- éste todavía da un error, pero uno limpio (503), y el
    de después ya puede andar de nuevo sin que nadie reinicie nada a mano.
    """
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(TimeoutError)
async def _manejar_timeout(_request: Request, _exc: TimeoutError) -> JSONResponse:
    """El motor no contestó a tiempo (colgado o muy cargado). El socket sigue vivo, así que no
    se cierra -- pero es un 504 con mensaje, no un 500 mudo."""
    return JSONResponse(status_code=504, content={"detail": "Guitarix no respondió a tiempo"})


# La PWA de control remoto (mobile/) se sirve desde esta misma app, montada bajo /app -- así una
# ruta relativa como fetch("/estado") funciona igual en local que atrás de un túnel público, sin
# tener que hardcodear ningún host. El prefijo /app no choca con ninguna ruta de la API (todas
# son rutas propias tipo /estado, /mezclador/*, nunca bajo /app).
_DIR_MOBILE = Path(__file__).resolve().parent.parent / "mobile"
if _DIR_MOBILE.is_dir():
    app.mount("/app", StaticFiles(directory=_DIR_MOBILE, html=True), name="mobile")


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


# Deliberadamente NO se usa `Field(allow_inf_nan=False)` acá para rechazar NaN/Infinity a nivel
# Pydantic. Se probó (23/09/2026) y causa un 500 en vez de un 422: cuando Pydantic rechaza el
# valor, Starlette arma la respuesta de error incluyendo el valor original que llegó, y el
# `json.dumps` estándar de Python no puede codificar un NaN/Infinity crudo (aunque sí los acepta
# al decodificar -- asimetría real de la librería). El rechazo real pasa un nivel más adentro:
# `MezcladorJack.fijar_ganancia()`/`fijar_paneo()` cortan los valores no finitos y devuelven un
# mensaje de texto (no el float crudo), así que ese 400 sí se serializa bien. Ver `engine/mixer.py`.


@app.get("/salud")
def salud() -> dict:
    """No toca Guitarix — solo confirma que el proceso de la API está vivo."""
    return {"ok": True}


@app.get("/estado")
def estado() -> dict:
    gx = _motor()
    return {
        "version": gx.version(),
        "estado": gx.estado(),
        "carga_cpu": gx.carga_cpu(),
    }


@app.get("/bancos")
def bancos() -> Any:
    return _motor().bancos()


@app.get("/bancos/{banco}/presets")
def presets(banco: str) -> Any:
    return _motor().presets(banco)


@app.post("/preset")
def cambiar_preset(datos: CambiarPreset) -> dict:
    """Ver `GuitarixRPC.set_preset`: un preset inexistente da 404 en vez de tumbar al motor."""
    try:
        _motor().set_preset(datos.banco, datos.preset)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"ok": True}


@app.get("/parametros")
def obtener_parametros(nombres: str) -> Any:
    """`nombres` separados por coma: `/parametros?nombres=amp.gain,eq.peak1`."""
    lista = [n.strip() for n in nombres.split(",") if n.strip()]
    if not lista:
        raise HTTPException(400, "nombres vacío")
    return _motor().obtener(*lista)


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


class EjecutarAccion(BaseModel):
    accion: str
    parametro: int | None = None


def _categorias_gx(linea: str) -> dict[str, str | None]:
    """id -> categoría cruda del motor, o {} si el motor no responde (la categoría de interfaz
    igual se resuelve por los overrides de engine/categorias.py)."""
    try:
        return {p["id"]: p.get("category") for p in _plugins(linea) if p.get("id")}
    except ConnectionError:
        return {}


def _cadena_actual(ctrl: ControladorEscenario) -> set[str] | None:
    try:
        return set(ctrl.rpc.orden_rack(0)) | set(ctrl.rpc.orden_rack(1))
    except ConnectionError:
        return None


def _estado_linea(ctrl: ControladorEscenario, linea: str | None = None) -> dict:
    preset = ctrl.preset
    setlist = ctrl.setlist
    cats_gx = _categorias_gx(linea) if linea else {}
    en_rack = _cadena_actual(ctrl) if linea else None
    banco_vis = setlist.bancos[ctrl.banco_visible]
    return {
        "preset": preset.nombre,
        "indice_activo": ctrl.indice_activo,
        "banco_activo": ctrl.banco_activo,
        "banco_visible": ctrl.banco_visible,
        "posicion_activa": ctrl.posicion_activa,
        "total_bancos": len(setlist.bancos),
        "banco_activo_nombre": setlist.bancos[ctrl.banco_activo].nombre,
        "banco_visible_nombre": banco_vis.nombre,
        "presets_banco_visible": [p.nombre for p in banco_vis.presets],
        "modo": ctrl.modo.value,
        "escena_activa": ctrl.escena_activa,
        "tempo_bpm": ctrl.tempo_bpm,
        "stomps": [
            {
                "etiqueta": s.etiqueta,
                "unidad": s.unidad,
                "activo": ctrl.stomp_activo(i),
                "categoria": categoria(s.unidad, cats_gx.get(s.unidad)),
                "en_cadena": None if en_rack is None else s.unidad in en_rack,
            }
            for i, s in enumerate(preset.stomps)
        ],
        "escenas": [e.nombre for e in preset.escenas],
        "advertencia": ctrl.advertencia,
    }


@app.get("/lineas")
def listar_lineas() -> list[str]:
    """Nombres de línea configurados (`LINEAS`, o por default los mismos que `MIXER_FUENTES`)."""
    return list(LINEAS)


@app.get("/lineas/{linea}/estado")
def estado_linea(linea: str) -> dict:
    """Preset activo, banco visible, modo, escena, tempo y estado de cada stomp -- la parte de
    control de performance que `/preset`/`/parametros` (Guitarix crudo) no cubren."""
    return _estado_linea(_linea(linea), linea)


@app.post("/lineas/{linea}/accion")
def ejecutar_accion(linea: str, datos: EjecutarAccion) -> dict:
    """Dispara cualquier `Accion` de `engine/controlador.py` sobre una línea: cambiar de preset,
    navegar bancos, pisar un stomp, cambiar de escena, tocar el afinador, tap tempo, etc.
    `accion` es el valor de texto del enum (`"toggle_stomp"`, `"escena"`, ...); `parametro` es lo
    que esa acción necesite (número de stomp, índice de escena/preset) o `null` si no necesita.
    """
    ctrl = _linea(linea)
    try:
        accion = Accion(datos.accion)
    except ValueError:
        raise HTTPException(
            400, f"acción desconocida: {datos.accion!r}. Válidas: {[a.value for a in Accion]}"
        )
    try:
        mensaje = ctrl.ejecutar(accion, datos.parametro)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"mensaje": mensaje, **_estado_linea(ctrl, linea)}


@app.post("/lineas/{linea}/guardar")
def guardar_preset_linea(linea: str) -> dict:
    """Botón 💾: guarda el estado real del motor (cadena del rack + valores) en el preset activo
    y escribe la setlist de esa línea a disco."""
    ctrl = _linea(linea)
    ctrl.guardar_en_preset()
    _guardar_setlist(linea)
    return {"mensaje": f"Guardado: {ctrl.preset.nombre}", **_estado_linea(ctrl, linea)}


@app.post("/lineas/{linea}/escenas")
def nueva_escena_linea(linea: str) -> dict:
    """Tile "+" del modo SCENE: crea una escena con el estado actual (nombre automático por
    letra; se renombra desde el sistema, no desde la app) y la guarda en la setlist."""
    ctrl = _linea(linea)
    try:
        nombre = ctrl.nueva_escena()
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _guardar_setlist(linea)
    return {"mensaje": f"Escena creada: {nombre}", **_estado_linea(ctrl, linea)}


def _grid(linea: str) -> dict:
    """Las dos cadenas reales del rack (mono -> estéreo, en serie), cada bloque con nombre,
    categoría de interfaz y si está encendido -- todo lo que dibuja el GRID en un solo pedido."""
    ctrl = _linea(linea)
    todos = _plugins(linea)
    nombre_de = nombres(todos)
    cat_gx = {p["id"]: p.get("category") for p in todos if p.get("id")}
    no_quitables = fijos(todos)
    filas = []
    for clave, estereo in (("mono", 0), ("estereo", 1)):
        ids = list(ctrl.rpc.orden_rack(estereo))
        encendido = ctrl.rpc.obtener(*[f"{u}.on_off" for u in ids]) if ids else {}
        filas.append({
            "cadena": clave,
            "estereo": bool(estereo),
            "unidades": [
                {
                    "id": u,
                    "nombre": nombre_de.get(u, u),
                    "categoria": categoria(u, cat_gx.get(u)),
                    "encendido": bool(encendido.get(f"{u}.on_off")),
                    "fijo": u in no_quitables,
                }
                for u in ids
            ],
        })
    return {"filas": filas}


@app.get("/lineas/{linea}/grid")
def grid_linea(linea: str) -> dict:
    return _grid(linea)


@app.get("/lineas/{linea}/plugins")
def plugins_linea(linea: str) -> dict:
    """Bloques que se pueden agregar desde el "+", agrupados por categoría de interfaz en el
    orden de la leyenda. Solo aparecen las categorías que tienen al menos un modelo real."""
    lista = insertables(_plugins(linea))
    en_rack = _cadena_actual(_linea(linea)) or set()
    for p in lista:
        p["en_cadena"] = p["id"] in en_rack
    categorias = [
        {"id": clave, "nombre": nombre, "plugins": [p for p in lista if p["categoria"] == clave]}
        for clave, nombre in CATEGORIAS
    ]
    return {"categorias": [c for c in categorias if c["plugins"]]}


class CambiarBloque(BaseModel):
    unidad: str
    estereo: bool = False


def _validar_insertable(linea: str, datos: CambiarBloque) -> None:
    validos = {p["id"]: p for p in insertables(_plugins(linea))}
    if datos.unidad not in validos:
        raise HTTPException(404, f"bloque desconocido: {datos.unidad!r}")
    if validos[datos.unidad]["estereo"] != datos.estereo:
        fila = "estéreo" if datos.estereo else "mono"
        raise HTTPException(400, f"{datos.unidad!r} no va en la fila {fila}")


@app.post("/lineas/{linea}/grid/insertar")
def insertar_bloque(linea: str, datos: CambiarBloque) -> dict:
    """Agrega un bloque al final de su fila y lo deja encendido. Cada unidad existe una sola
    vez en el motor: si ya está en el rack, 409."""
    _validar_insertable(linea, datos)
    ctrl = _linea(linea)
    if datos.unidad in (_cadena_actual(ctrl) or set()):
        raise HTTPException(409, f"{datos.unidad!r} ya está en el rack")
    ctrl.rpc.insertar_unidad(datos.unidad, "", datos.estereo)
    ctrl.rpc.fijar(f"{datos.unidad}.on_off", 1)
    return _grid(linea)


@app.post("/lineas/{linea}/grid/quitar")
def quitar_bloque(linea: str, datos: CambiarBloque) -> dict:
    """Los bloques fijos (ampstack y compañía) se rechazan con 400: quitarlos hace segfault en
    Guitarix -- confirmado el 25/09/2026, tumbó el motor desde la PWA. Ver engine/categorias.py."""
    if datos.unidad in fijos(_plugins(linea)):
        raise HTTPException(400, f"{datos.unidad!r} es un bloque fijo del motor: no se puede quitar")
    ctrl = _linea(linea)
    if datos.unidad not in ctrl.rpc.orden_rack(int(datos.estereo)):
        raise HTTPException(404, f"{datos.unidad!r} no está en esa fila")
    ctrl.rpc.quitar_unidad(datos.unidad, datos.estereo)
    return _grid(linea)


@app.get("/lineas/{linea}/parametros")
def obtener_parametros_linea(linea: str, nombres: str) -> Any:
    """Como `/parametros`, pero contra el Guitarix de esta línea en particular -- necesario
    porque con varias líneas ya no hay un único motor "el" Guitarix."""
    lista = [n.strip() for n in nombres.split(",") if n.strip()]
    if not lista:
        raise HTTPException(400, "nombres vacío")
    return _linea(linea).rpc.obtener(*lista)


@app.post("/lineas/{linea}/parametros")
def fijar_parametros_linea(linea: str, datos: FijarParametros) -> dict:
    ctrl = _linea(linea)
    pares: list[Any] = []
    for nombre, valor in datos.pares.items():
        pares.extend((nombre, valor))
    try:
        ctrl.rpc.fijar(*pares)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


_TIPOS_RENDERIZABLES = frozenset({"float", "bool"})


def _parametros_unidad(crudo: dict[str, Any]) -> list[dict[str, Any]]:
    """Reordena la respuesta de `queryunit` a una lista simple de controles para el editor de
    nodos. Solo `float` (sliders) y `bool` (toggles) -- filtra a propósito cosas como
    `<unidad>.position` (coordenadas de la GUI de escritorio de Guitarix, no un parámetro de
    audio) o `<unidad>.pp`/`.s_h` (selectores pre/post y sample&hold: son `int` pero su valor
    real es un string como `"pre"`, no un número -- necesitan un control propio, no un slider;
    confirmado en vivo el 25/09/2026, queda para una iteración futura, no v1)."""
    parametros = []
    for nombre, meta in crudo.items():
        if meta.get("type") not in _TIPOS_RENDERIZABLES:
            continue
        parametros.append({
            "nombre": nombre,
            "etiqueta": meta.get("name") or nombre.rsplit(".", 1)[-1],
            "tipo": meta["type"],
            "min": meta.get("lower_bound"),
            "max": meta.get("upper_bound"),
            "paso": meta.get("step"),
            "valor": meta.get("value", {}).get(nombre),
        })
    return parametros


@app.get("/lineas/{linea}/cadena")
def cadena_linea(linea: str) -> list[str]:
    """Ids de unidad en el orden real del rack (cadena mono -- la única que usan las líneas de
    instrumento hoy) -- arma la fila de bloques del editor de nodos."""
    return _linea(linea).rpc.orden_rack(0)


@app.get("/lineas/{linea}/unidad/{unidad}")
def unidad_linea(linea: str, unidad: str) -> dict:
    """Parámetros controlables de una unidad del rack (`queryunit`, reordenado) -- arma los
    knobs cuando se toca un bloque en el editor de nodos."""
    crudo = _linea(linea).rpc.consultar_unidad(unidad)
    if not crudo:
        raise HTTPException(404, f"unidad desconocida o sin parámetros: {unidad!r}")
    return {"unidad": unidad, "parametros": _parametros_unidad(crudo)}


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
