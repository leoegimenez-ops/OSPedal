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
import os
import shutil
import socket
import subprocess
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


@router.get("/local")
def soy_local(request: Request) -> dict:
    """La app pregunta esto para saber si mostrar la pestaña SYSTEM."""
    return {"local": es_local(request)}


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
