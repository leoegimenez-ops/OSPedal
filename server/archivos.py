"""Biblioteca de archivos del equipo: respuestas de impulso (IR) y capturas NAM / AIDA-X.

- Subir y borrar: SOLO desde la pantalla del equipo (server/sistema.py, `exigir_local`). Ahí el
  selector de archivos también ve los pendrives conectados.
- Elegir qué archivo usa un bloque: desde cualquier pantalla (es un ajuste de sonido como una
  perilla) -- ver `archivo_de_bloque` en server/api.py.

Subida sin multipart (el server no tiene python-multipart): el cuerpo del POST ES el archivo y el
nombre va en la URL. Se escribe a un temporal y se renombra al final: un corte a mitad de camino
no deja un archivo roto con el nombre bueno.

Cómo los carga el motor (verificado contra Guitarix 0.47.0 el 26/09/2026):
- IR: bloques "jconv" (estéreo) y "jconv_mono": parámetro `<bloque>.convolver` con un objeto
  {"jconv.IRFile", "jconv.IRDir", "jconv.Length", ...}. La carga es asíncrona (el convolucionador
  se reinicia en segundo plano, ~1 s). Medido con audio: IR impulso deja pasar la señal, IR vacío
  da silencio.
- NAM ("nam", "snam", "mnam") y RTNeural/AIDA-X ("rtneural", "srtneural", "mrtneural"):
  `<bloque>.loadpath` = una carpeta, `<bloque>.flist` = índice. Como el orden de la carpeta no
  está garantizado, cada carga apunta a una carpeta propia con UN solo enlace al archivo (flist=1),
  y la carpeta es distinta cada vez: si el valor de loadpath no cambia, el motor no re-escanea.
"""

from __future__ import annotations

import hashlib
import os
import re
import wave
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server.sistema import exigir_local

router = APIRouter(prefix="/archivos", tags=["archivos"])

RAIZ_MODELOS = Path(os.environ.get("PS_MODELOS", Path(__file__).resolve().parent.parent / "models"))
TIPOS = {
    # tipo: (carpeta, extensiones aceptadas, bloques que lo usan)
    "ir": ("irs", (".wav", ".flac", ".aif", ".aiff"), ("jconv", "jconv_mono")),
    "nam": ("nam", (".nam",), ("nam", "snam", "mnam")),
    "aidax": ("aidax", (".json", ".aidax"), ("rtneural", "srtneural", "mrtneural")),
}
MAX_BYTES = 80 * 1024 * 1024
DIR_CARGADOS = RAIZ_MODELOS / ".cargados"      # carpetas-enlace de NAM/AIDA-X en uso (no borrar)


def tipo_de_bloque(base: str) -> str | None:
    for tipo, (_c, _e, bloques) in TIPOS.items():
        if base in bloques:
            return tipo
    return None


def carpeta(tipo: str) -> Path:
    if tipo not in TIPOS:
        raise HTTPException(404, f"tipo desconocido: {tipo!r} (ir, nam, aidax)")
    ruta = RAIZ_MODELOS / TIPOS[tipo][0]
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def nombre_seguro(nombre: str, tipo: str) -> str:
    nombre = Path(nombre).name.strip()
    nombre = re.sub(r"[^\w\-. ()áéíóúñÁÉÍÓÚÑ]", "_", nombre)
    if not nombre or nombre.startswith("."):
        raise HTTPException(400, "Invalid file name")
    if not nombre.lower().endswith(TIPOS[tipo][1]):
        raise HTTPException(400, f"A {tipo.upper()} file must end in {' / '.join(TIPOS[tipo][1])}")
    return nombre[:120]


def ruta_archivo(tipo: str, nombre: str) -> Path:
    ruta = carpeta(tipo) / nombre_seguro(nombre, tipo)
    if not ruta.is_file():
        raise HTTPException(404, f"No such file: {nombre!r}")
    return ruta


def _validar_contenido(tipo: str, datos: bytes) -> None:
    if tipo == "ir":
        if not (datos[:4] in (b"RIFF", b"fLaC", b"FORM")):
            raise HTTPException(400, "That doesn't look like an audio file (WAV/FLAC/AIFF)")
    else:
        texto = datos[:2048].lstrip()
        if not texto.startswith((b"{", b"[")):
            raise HTTPException(400, "That doesn't look like a model file (JSON)")


@router.get("")
def listar() -> dict[str, list[dict[str, Any]]]:
    salida: dict[str, list[dict[str, Any]]] = {}
    for tipo, (_c, exts, _b) in TIPOS.items():
        archivos = []
        for p in sorted(carpeta(tipo).iterdir(), key=lambda x: x.name.lower()):
            if p.is_file() and p.name.lower().endswith(exts):
                archivos.append({"nombre": p.name, "kb": round(p.stat().st_size / 1024, 1)})
        salida[tipo] = archivos
    return salida


@router.post("/{tipo}")
async def subir(tipo: str, nombre: str, request: Request) -> dict:
    exigir_local(request)
    destino = carpeta(tipo) / nombre_seguro(nombre, tipo)
    datos = bytearray()
    async for trozo in request.stream():
        datos.extend(trozo)
        if len(datos) > MAX_BYTES:
            raise HTTPException(413, f"File too big (max {MAX_BYTES // (1024 * 1024)} MB)")
    if not datos:
        raise HTTPException(400, "Empty file")
    _validar_contenido(tipo, bytes(datos))
    temporal = destino.with_name(f".subiendo-{destino.name}")
    temporal.write_bytes(bytes(datos))
    os.replace(temporal, destino)
    return {"ok": True, "nombre": destino.name, "kb": round(len(datos) / 1024, 1)}


class Borrar(BaseModel):
    nombre: str


@router.post("/{tipo}/borrar")
def borrar(tipo: str, datos: Borrar, request: Request) -> dict:
    exigir_local(request)
    ruta_archivo(tipo, datos.nombre).unlink()
    return {"ok": True}


# -- Cargar un archivo en un bloque (lo usa server/api.py) --------------------------------------

def pares_para_bloque(q: str, base: str, tipo: str, nombre: str, actual_conv: dict | None) -> list[Any]:
    """Pares nombre/valor para que el bloque `q` (id calificado) use el archivo."""
    ruta = ruta_archivo(tipo, nombre)
    if tipo == "ir":
        valor = dict(actual_conv) if isinstance(actual_conv, dict) else {}
        largo = 0
        try:
            with wave.open(str(ruta), "rb") as w:
                largo = w.getnframes()
        except (wave.Error, EOFError, OSError):
            pass                     # FLAC/AIFF: el motor usa el archivo entero con Length 0
        valor.update({"jconv.IRFile": ruta.name, "jconv.IRDir": str(ruta.parent),
                      "jconv.Offset": 0, "jconv.Delay": 0, "jconv.Length": largo})
        return [f"{q}.convolver", valor]
    # NAM / AIDA-X: carpeta propia con un solo enlace, distinta por archivo (ver docstring).
    huella = hashlib.sha1(f"{ruta}:{ruta.stat().st_mtime_ns}".encode()).hexdigest()[:10]
    dir_carga = DIR_CARGADOS / f"{tipo}-{huella}"
    dir_carga.mkdir(parents=True, exist_ok=True)
    enlace = dir_carga / ruta.name
    if not enlace.exists():
        try:
            enlace.symlink_to(ruta)
        except OSError:
            enlace.write_bytes(ruta.read_bytes())      # sistemas de archivos sin enlaces
    return [f"{q}.loadpath", str(dir_carga), f"{q}.flist", 1]


def archivo_actual(tipo: str, valores: dict[str, Any], q: str) -> str | None:
    """Qué archivo tiene cargado el bloque, a partir de sus parámetros."""
    if tipo == "ir":
        conv = valores.get(f"{q}.convolver") or {}
        return conv.get("jconv.IRFile") or None
    carpeta_carga = valores.get(f"{q}.loadpath")
    if not carpeta_carga:
        return None
    try:
        hijos = [p.name for p in Path(carpeta_carga).iterdir() if not p.name.startswith(".")]
    except OSError:
        return None
    return hijos[0] if len(hijos) == 1 else None
