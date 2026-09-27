"""Red del equipo: Wi-Fi y Wi-Fi propio (hotspot). Pantalla del OS: SYSTEM > Network.

Usa `nmcli` (NetworkManager), que trae la imagen del OS. En la PC de desarrollo (WSL2) no existe:
la pantalla lo dice en vez de fallar. El parseo de la salida de nmcli está separado en funciones
puras y probado con salidas reales (server/test_red.py).

- Estado: interfaces, IPs, a qué Wi-Fi está conectado.
- Redes: las que se ven, con señal y si piden clave.
- Conectar: nombre + clave (escrita con el teclado en pantalla).
- Wi-Fi propio: el equipo crea su red para conectar la tablet donde no hay Wi-Fi (en un show).

Todo lo que cambia la red: solo desde la pantalla del equipo.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server.sistema import direcciones_ip, exigir_local

router = APIRouter(prefix="/red", tags=["red"])
NOMBRE_HOTSPOT = "PedalSistema"


def dividir_terso(linea: str) -> list[str]:
    """nmcli -t separa con ':' y escapa los ':' de adentro como '\\:' (p. ej. en un SSID)."""
    campos, actual, escape = [], "", False
    for c in linea:
        if escape:
            actual += c
            escape = False
        elif c == "\\":
            escape = True
        elif c == ":":
            campos.append(actual)
            actual = ""
        else:
            actual += c
    campos.append(actual)
    return campos


def parsear_redes(texto: str) -> list[dict[str, Any]]:
    """Salida de `nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY device wifi list`."""
    redes: dict[str, dict[str, Any]] = {}
    for linea in texto.splitlines():
        if not linea.strip():
            continue
        partes = dividir_terso(linea)
        if len(partes) < 4:
            continue
        en_uso, ssid, senal, seguridad = partes[0], partes[1], partes[2], ":".join(partes[3:])
        if not ssid:
            continue                       # redes ocultas
        red = {"ssid": ssid, "senal": int(senal) if senal.isdigit() else 0,
               "segura": bool(seguridad.strip()) and seguridad.strip() != "--",
               "conectada": en_uso.strip() == "*"}
        previa = redes.get(ssid)           # la misma red en varios canales: queda la mejor
        if not previa or red["senal"] > previa["senal"] or red["conectada"]:
            redes[ssid] = red
    return sorted(redes.values(), key=lambda r: (not r["conectada"], -r["senal"]))


def parsear_dispositivos(texto: str) -> list[dict[str, str]]:
    """Salida de `nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device`."""
    salida = []
    for linea in texto.splitlines():
        partes = dividir_terso(linea)
        if len(partes) >= 4 and partes[1] in ("wifi", "ethernet"):
            salida.append({"dispositivo": partes[0], "tipo": partes[1], "estado": partes[2],
                           "conexion": partes[3] if partes[3] != "--" else ""})
    return salida


def _nmcli(*args: str, timeout: float = 20) -> str:
    if not shutil.which("nmcli"):
        raise HTTPException(503, "Network manager not available on this machine")
    r = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise HTTPException(400, (r.stderr or r.stdout).strip() or "nmcli error")
    return r.stdout


@router.get("/estado")
def estado() -> dict[str, Any]:
    disponible = bool(shutil.which("nmcli"))
    dispositivos = parsear_dispositivos(_nmcli("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device")) if disponible else []
    return {"disponible": disponible, "ips": direcciones_ip(), "dispositivos": dispositivos,
            "hotspot": NOMBRE_HOTSPOT}


@router.get("/wifi")
def redes_wifi(request: Request) -> dict[str, Any]:
    exigir_local(request)
    texto = _nmcli("-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes")
    return {"redes": parsear_redes(texto)}


class Conectar(BaseModel):
    ssid: str
    clave: str | None = None


@router.post("/wifi/conectar")
def conectar(datos: Conectar, request: Request) -> dict:
    exigir_local(request)
    args = ["device", "wifi", "connect", datos.ssid]
    if datos.clave:
        args += ["password", datos.clave]
    _nmcli(*args, timeout=45)
    return {"ok": True, "ips": direcciones_ip()}


class Hotspot(BaseModel):
    activo: bool
    clave: str | None = None     # 8 a 63 caracteres (WPA2)


@router.post("/hotspot")
def hotspot(datos: Hotspot, request: Request) -> dict:
    """Wi-Fi propio del equipo: la tablet se conecta directo, sin router (shows sin Wi-Fi)."""
    exigir_local(request)
    if not datos.activo:
        _nmcli("connection", "down", "Hotspot")
        return {"ok": True}
    if not datos.clave or not 8 <= len(datos.clave) <= 63:
        raise HTTPException(400, "The Wi-Fi password must have 8 to 63 characters")
    _nmcli("device", "wifi", "hotspot", "ssid", NOMBRE_HOTSPOT, "password", datos.clave, timeout=45)
    return {"ok": True, "ssid": NOMBRE_HOTSPOT, "ips": direcciones_ip()}
