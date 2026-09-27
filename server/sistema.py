"""Funciones del sistema operativo: solo desde la pantalla del propio equipo.

La pantalla del OS es la MISMA app que el celular (pedido del usuario, 25/09/2026), pero con una
pestaña SYSTEM extra: conectar dispositivos (QR), estado del equipo, apagar/reiniciar, y en los
pasos siguientes audio/MIDI, archivos, nombres, red y actualizaciones.

Seguridad: todo lo de acá que cambia el equipo exige que el pedido venga de la pantalla local --
127.0.0.1 y SIN los encabezados que agrega un túnel/proxy (cloudflared pone Cf-Connecting-Ip).
Así apagar el equipo no es posible desde internet ni desde otro dispositivo de la red, aunque
conozcan la dirección. La app muestra la pestaña SYSTEM solo si /sistema/local dice que sí.

Apagar/reiniciar el equipo de verdad solo con PS_SISTEMA_REAL=1 (lo pone la imagen del OS). Sin
esa variable se simula: en desarrollo (WSL2) `systemctl poweroff` apagaría la máquina virtual
entera con todo lo que corre adentro.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

router = APIRouter(prefix="/sistema", tags=["sistema"])

SISTEMA_REAL = os.environ.get("PS_SISTEMA_REAL") == "1"
PUERTO_APP = int(os.environ.get("PS_PUERTO", "8000"))
LOG_TUNEL = Path(os.environ.get("PS_TUNEL_LOG", "/tmp/cloudflared.log"))
_ENCABEZADOS_PROXY = ("cf-connecting-ip", "x-forwarded-for", "x-real-ip", "forwarded")


def es_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        return False
    return not any(h in request.headers for h in _ENCABEZADOS_PROXY)


def exigir_local(request: Request) -> None:
    if not es_local(request):
        raise HTTPException(403, "Only from the system's own screen")


def guarda_cambios() -> bool:
    """¿Sobrevive lo que se guarda a un apagado? Instalado en disco, sí. Arrancado desde la imagen
    USB (live), solo si el pendrive tiene la partición "persistence" (la crea Rufus): sin ella
    todo vive en la RAM y al apagar se pierden presets, setlists y configuración."""
    try:
        cmdline = Path(os.environ.get("PS_PROC_CMDLINE", "/proc/cmdline")).read_text().split()
    except OSError:
        return True
    if "boot=live" not in cmdline:
        return True
    try:
        montajes = Path(os.environ.get("PS_PROC_MOUNTS", "/proc/mounts")).read_text().splitlines()
    except OSError:
        return False
    # live-boot monta cada partición de persistencia en /run/live/persistence/<dispositivo>.
    return any(len(m.split()) > 1 and m.split()[1].startswith("/run/live/persistence/") for m in montajes)


@router.get("/local")
def soy_local(request: Request) -> dict:
    """La app pregunta esto al arrancar: si mostrar la pestaña SYSTEM, y (en todas las pantallas,
    también la tablet) si avisar que lo que se guarde se va a perder al apagar."""
    return {"local": es_local(request), "guarda_cambios": guarda_cambios()}


# -- Estado del equipo ---------------------------------------------------------------------

def _leer(ruta: str) -> str | None:
    try:
        return Path(ruta).read_text(encoding="utf-8")
    except OSError:
        return None


def _memoria() -> dict[str, int] | None:
    texto = _leer("/proc/meminfo")
    if not texto:
        return None
    campos = {}
    for linea in texto.splitlines():
        nombre, _, resto = linea.partition(":")
        partes = resto.split()
        if partes:
            campos[nombre] = int(partes[0]) // 1024      # kB -> MB
    return {"total_mb": campos.get("MemTotal", 0), "disponible_mb": campos.get("MemAvailable", 0)}


def _temperatura() -> float | None:
    maximo = None
    for zona in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        crudo = _leer(str(zona))
        if crudo and crudo.strip().lstrip("-").isdigit():
            grados = int(crudo) / 1000
            maximo = grados if maximo is None else max(maximo, grados)
    return maximo


def _uptime() -> int | None:
    texto = _leer("/proc/uptime")
    return int(float(texto.split()[0])) if texto else None


def direcciones_ip() -> list[dict[str, str]]:
    """IPv4 de la red local (sin loopback): con cada una se arma la URL/QR para conectarse."""
    salida = []
    try:
        texto = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True,
                               text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        texto = ""
    for linea in texto.splitlines():
        partes = linea.split()
        if len(partes) >= 4 and partes[2] == "inet":
            interfaz, ip = partes[1], partes[3].split("/")[0]
            if not ip.startswith("127."):
                salida.append({"interfaz": interfaz, "ip": ip})
    return salida


def url_tunel() -> str | None:
    texto = _leer(str(LOG_TUNEL))
    if not texto:
        return None
    # El log acumula un link por cada vez que el túnel arrancó: vale el ÚLTIMO (los anteriores
    # ya no funcionan -- se vio en la primera prueba, mostraba uno viejo).
    ultimo = None
    for palabra in texto.split():
        if palabra.startswith("https://") and palabra.rstrip("|").endswith(".trycloudflare.com"):
            ultimo = palabra.rstrip("|")
    return ultimo


@router.get("/info")
def info() -> dict[str, Any]:
    from engine import audio_engine    # noqa: PLC0415 -- evita cargar esto en cada import

    carga = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    disco = shutil.disk_usage(Path(__file__).resolve().parent.parent)
    frecuencia = audio_engine.frecuencia_muestreo_jack()
    buffer_ = audio_engine.tamano_buffer_jack()
    return {
        "equipo": socket.gethostname(),
        "encendido_seg": _uptime(),
        "nucleos": os.cpu_count(),
        "carga": [round(c, 2) for c in carga],
        "memoria": _memoria(),
        "temperatura_c": _temperatura(),
        "disco": {"total_gb": round(disco.total / 1e9, 1), "libre_gb": round(disco.free / 1e9, 1)},
        "audio": {
            "jack": audio_engine.jack_activo(),
            "frecuencia": frecuencia,
            "buffer": buffer_,
            # Latencia de un período; ida y vuelta real ≈ el doble más la interfaz.
            "latencia_ms": round(buffer_ / frecuencia * 1000, 2) if frecuencia and buffer_ else None,
        },
        "red": direcciones_ip(),
        "tunel": url_tunel(),
        "puerto": PUERTO_APP,
        "real": SISTEMA_REAL,
    }


@router.get("/qr")
def qr(texto: str) -> Response:
    """QR en SVG para conectar la tablet/celular apuntando la cámara a la pantalla del equipo."""
    import segno   # noqa: PLC0415

    if len(texto) > 300:
        raise HTTPException(400, "texto demasiado largo para un QR")
    buf = io.BytesIO()
    segno.make(texto, error="m").save(buf, kind="svg", scale=8, border=2, dark="#000", light="#fff")
    return Response(buf.getvalue(), media_type="image/svg+xml")


# -- Versión y actualizaciones -------------------------------------------------------------
#
# El equipo tiene el programa como repo de git. Dos canales:
#   - "estable" (por defecto): solo versiones marcadas como probadas, tags "v1.2.0". Nunca ofrece
#     una versión más vieja que la instalada.
#   - "desarrollo": lo último de main (para probar antes de marcar una versión).
# Actualizar NO lo hace el servidor (se reinicia en el medio): escribe el pedido y lanza el
# servicio pedalsistema-actualizar (os/bin/actualizar), que reinstala lo necesario, reinicia,
# comprueba que la versión nueva arranca y, si no, vuelve sola a la anterior.
# Sin internet: el mismo proceso con un paquete de actualización traído en un pendrive
# (os/bin/crear-paquete-usb lo arma).

RAIZ = Path(os.environ.get("PS_RAIZ_REPO", Path(__file__).resolve().parent.parent))
ESTADO_ACTUALIZACION = Path(os.environ.get("PS_ESTADO_ACTUALIZACION",
                                           RAIZ / "config" / "actualizacion.json"))
MAX_PAQUETE = 300 * 1024 * 1024


def _git(*args: str, timeout: float = 30) -> str:
    r = subprocess.run(["git", "-C", str(RAIZ), *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise HTTPException(502, (r.stderr or r.stdout).strip() or "git error")
    return r.stdout.strip()


def _clave_version(tag: str) -> tuple[int, ...] | None:
    m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
    return tuple(int(x) for x in m.groups()) if m else None


def _versiones_estables() -> list[str]:
    tags = [t for t in _git("tag", "-l", "v*").splitlines() if _clave_version(t)]
    return sorted(tags, key=_clave_version)


def _es_ancestro(a: str, b: str) -> bool:
    """¿`a` ya está contenido en `b`? (b es igual o más nuevo que a)"""
    r = subprocess.run(["git", "-C", str(RAIZ), "merge-base", "--is-ancestor", a, b],
                       capture_output=True, timeout=30)
    return r.returncode == 0


def _canal() -> str:
    from server import config_equipo   # noqa: PLC0415
    return config_equipo.leer()["actualizaciones"].get("canal", "estable")


def _destino_disponible(canal: str) -> str | None:
    """La versión a la que actualizar, o None si ya está en la última de su canal."""
    if canal == "desarrollo":
        destino = "origin/main"
        try:
            _git("rev-parse", "--verify", "--quiet", destino)
        except HTTPException:
            return None
    else:
        estables = _versiones_estables()
        if not estables:
            return None
        destino = estables[-1]
    # Si lo instalado ya contiene al destino (igual o más nuevo), no hay nada que hacer: así nunca
    # se ofrece bajar de versión (p. ej. al pasar de "desarrollo" a "estable").
    return None if _es_ancestro(destino, "HEAD") else destino


def _info_destino(destino: str | None) -> dict[str, Any]:
    if not destino:
        return {"hay": False, "destino": None, "cantidad": 0, "novedades": []}
    lista = [l for l in _git("log", "--format=%s", f"HEAD..{destino}").splitlines() if l.strip()]
    return {"hay": True, "destino": destino, "cantidad": len(lista), "novedades": lista[:12]}


@router.get("/version")
def version() -> dict[str, Any]:
    try:
        return {"commit": _git("rev-parse", "--short", "HEAD"),
                "version": _git("describe", "--tags", "--always"),
                "fecha": _git("log", "-1", "--format=%cd", "--date=format:%Y-%m-%d %H:%M"),
                "descripcion": _git("log", "-1", "--format=%s"),
                "canal": _canal()}
    except (HTTPException, OSError, subprocess.TimeoutExpired):
        return {"commit": None, "version": None, "fecha": None, "descripcion": "Unknown version",
                "canal": _canal()}


class Canal(BaseModel):
    canal: str


@router.post("/canal")
def elegir_canal(datos: Canal, request: Request) -> dict:
    exigir_local(request)
    if datos.canal not in ("estable", "desarrollo"):
        raise HTTPException(400, "canal: estable | desarrollo")
    from server import config_equipo   # noqa: PLC0415
    config_equipo.actualizar("actualizaciones", {"canal": datos.canal})
    return {"ok": True, "canal": datos.canal}


@router.post("/buscar_actualizacion")
def buscar_actualizacion(request: Request) -> dict[str, Any]:
    exigir_local(request)
    canal = _canal()
    try:
        _git("fetch", "--quiet", "--tags", "--force", "origin", timeout=60)
        if canal == "desarrollo":
            _git("fetch", "--quiet", "origin", "main", timeout=60)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "No internet connection (or the server is too slow)")
    except HTTPException as exc:
        raise HTTPException(502, f"Can't reach the update server: {exc.detail}")
    return {"canal": canal, **_info_destino(_destino_disponible(canal))}


@router.post("/actualizacion_usb")
async def actualizacion_usb(request: Request) -> dict[str, Any]:
    """Paquete de actualización traído en un pendrive (sin internet). Se verifica que sea un
    paquete de git válido y se toman sus versiones estables; después se actualiza igual que
    por internet (con vuelta atrás)."""
    exigir_local(request)
    datos = bytearray()
    async for trozo in request.stream():
        datos.extend(trozo)
        if len(datos) > MAX_PAQUETE:
            raise HTTPException(413, "Update package too big")
    if not datos.startswith(b"# v2 git bundle") and not datos.startswith(b"# v3 git bundle"):
        raise HTTPException(400, "That file is not a PedalSistema update package")
    ruta = Path(tempfile.gettempdir()) / "pedalsistema-actualizacion.bundle"
    ruta.write_bytes(bytes(datos))
    try:
        _git("bundle", "verify", str(ruta), timeout=120)
        _git("fetch", "--quiet", "--force", str(ruta), "refs/tags/v*:refs/tags/v*", timeout=300)
    except HTTPException as exc:
        raise HTTPException(400, f"Invalid update package: {exc.detail}")
    finally:
        ruta.unlink(missing_ok=True)
    return {"canal": "estable", **_info_destino(_destino_disponible("estable"))}


class Actualizar(BaseModel):
    destino: str


@router.post("/actualizar")
def actualizar(datos: Actualizar, request: Request) -> dict[str, Any]:
    exigir_local(request)
    if datos.destino != "origin/main" and datos.destino not in _versiones_estables():
        raise HTTPException(400, f"Unknown version: {datos.destino!r}")
    from server import api    # noqa: PLC0415
    api.guardar_todo()
    ESTADO_ACTUALIZACION.parent.mkdir(parents=True, exist_ok=True)
    ESTADO_ACTUALIZACION.write_text(json.dumps(
        {"estado": "pedido", "destino": datos.destino, "pedido": round(time.time())}), encoding="utf-8")
    if not SISTEMA_REAL:
        return {"ok": True, "simulado": True, "destino": datos.destino,
                "mensaje": "Simulated (development machine): the real system updates, checks and restarts itself"}
    # El actualizador corre aparte (esta app se va a reiniciar en el medio).
    subprocess.Popen(["systemctl", "start", "--no-block", "pedalsistema-actualizar.service"],
                     start_new_session=True)
    return {"ok": True, "simulado": False, "destino": datos.destino}


@router.get("/actualizacion")
def estado_actualizacion() -> dict[str, Any]:
    """Resultado de la última actualización (ok / revertida y por qué / en curso)."""
    try:
        return json.loads(ESTADO_ACTUALIZACION.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"estado": None}


# -- Energía ------------------------------------------------------------------------------

class AccionEnergia(BaseModel):
    accion: str        # apagar | reiniciar | reiniciar_audio


_ultima_energia: dict[str, Any] = {}


@router.post("/energia")
def energia(datos: AccionEnergia, request: Request) -> dict:
    exigir_local(request)
    if datos.accion == "reiniciar_audio":
        from server import api    # noqa: PLC0415 -- import circular: api incluye este router
        return api.reiniciar_motores()
    comandos = {"apagar": ["systemctl", "poweroff"], "reiniciar": ["systemctl", "reboot"]}
    if datos.accion not in comandos:
        raise HTTPException(400, "acción: apagar | reiniciar | reiniciar_audio")
    _ultima_energia.update({"accion": datos.accion, "cuando": time.time(), "simulado": not SISTEMA_REAL})
    if not SISTEMA_REAL:
        return {"ok": True, "simulado": True,
                "mensaje": "Simulated (development machine): the real OS image sets PS_SISTEMA_REAL=1"}
    # Guardar antes de apagar: ningún dato se pierde (pedido explícito del usuario).
    from server import api    # noqa: PLC0415
    api.guardar_todo()
    subprocess.Popen(comandos[datos.accion], start_new_session=True)
    return {"ok": True, "simulado": False}
