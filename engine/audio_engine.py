"""Enumeración de dispositivos de audio (ALSA) y puertos JACK.

Decisión de arquitectura (`docs/arquitectura.md`): el sistema no apunta a un modelo de interfaz
de audio específico. En vez de eso, expone lo que ALSA/JACK reportan y deja que el usuario elija
desde la GUI (Fase 4) qué dispositivo usar. Este módulo es la capa que hace esa enumeración.

Separación deliberada entre parsear y ejecutar: `parsear_aplay()`/`parsear_jack_lsp()` son
funciones puras que reciben texto y no tocan el sistema — así se pueden probar con salidas
grabadas, sin necesitar hardware de audio real ni JACK corriendo. `dispositivos_alsa()`/
`puertos_jack()` son las que efectivamente invocan los binarios.

Qué está verificado y qué no (23/09/2026, WSL2 + Debian 13):

- **Enumeración de puertos JACK** (`parsear_jack_lsp`, `puertos_jack`, `jack_activo`,
  `frecuencia_muestreo_jack`, `tamano_buffer_jack`): verificado contra un `jackd` real corriendo
  con backend dummy (WSL2 no tiene hardware de audio, así que no se pudo probar con backend ALSA
  real) y con Guitarix conectado — `jack_lsp -pt` mostró exactamente los puertos `system:*` del
  backend y `gx_head_amp:*`/`gx_head_fx:*` del motor, con el formato de 3 líneas por puerto que
  asume el parser (nombre, `properties:`, descripción de tipo).
- **Enumeración de tarjetas ALSA** (`parsear_aplay`, `dispositivos_alsa`): el formato de
  `aplay -l`/`arecord -l` que asume el parser es el documentado y estable de `alsa-utils` desde
  hace décadas, y se confirmó el caso sin hardware (`aplay -l` con rc=0, salida vacía en stdout,
  "no soundcards found..." en stderr). **No se pudo confirmar contra una tarjeta real** — WSL2 no
  permite cargar `snd-dummy` ni pasar hardware ALSA genérico, así que el caso con una o más
  tarjetas conectadas sigue sin probarse contra el formato real. Falta correrlo en la máquina de
  destino con una interfaz de audio conectada.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

_RE_TARJETA_ALSA = re.compile(
    r"^card (\d+): (.*?) \[(.*?)\], device (\d+): (.*?) \[(.*?)\]$"
)

TIPOS_DISPOSITIVO = frozenset({"reproduccion", "captura"})


@dataclass(frozen=True)
class DispositivoALSA:
    """Una tarjeta/dispositivo ALSA, tal como los reporta `aplay -l` / `arecord -l`."""

    tarjeta: int
    id_tarjeta: str
    nombre_tarjeta: str
    dispositivo: int
    nombre_dispositivo: str

    @property
    def hw(self) -> str:
        """Identificador listo para pasarle a `jackd -d alsa -d hw:X,Y`."""
        return f"hw:{self.tarjeta},{self.dispositivo}"


@dataclass(frozen=True)
class PuertoJack:
    """Un puerto JACK, tal como lo reporta `jack_lsp -pt`."""

    cliente: str
    puerto: str
    nombre_completo: str
    direccion: str   # "entrada" | "salida"
    tipo: str        # "audio" | "midi"
    fisico: bool
    terminal: bool


def parsear_aplay(texto: str) -> list[DispositivoALSA]:
    """Parsea la salida de `aplay -l` / `arecord -l`.

    Línea esperada por dispositivo:
        card 0: PCH [HDA Intel PCH], device 0: ALC3234 Analog [ALC3234 Analog]

    Sin tarjetas conectadas, `aplay -l`/`arecord -l` no imprimen nada en stdout (el mensaje
    "no soundcards found..." va a stderr) — en ese caso esta función devuelve una lista vacía,
    que es el resultado correcto, no un error.
    """
    dispositivos = []
    for linea in texto.splitlines():
        m = _RE_TARJETA_ALSA.match(linea.strip())
        if not m:
            continue
        tarjeta, id_tarjeta, nombre_tarjeta, dispositivo, _id_dispositivo, nombre_dispositivo = m.groups()
        dispositivos.append(DispositivoALSA(
            tarjeta=int(tarjeta),
            id_tarjeta=id_tarjeta,
            nombre_tarjeta=nombre_tarjeta,
            dispositivo=int(dispositivo),
            nombre_dispositivo=nombre_dispositivo,
        ))
    return dispositivos


def parsear_jack_lsp(texto: str) -> list[PuertoJack]:
    """Parsea la salida de `jack_lsp -pt`.

    Formato de 3 líneas por puerto:
        gx_head_amp:in_0
        \tproperties: input,
        \t32 bit float mono audio

    Cualquier línea con sangría pertenece al puerto anterior; una línea sin sangría abre uno
    nuevo. Ese invariante es lo único de lo que depende este parser — no asume cuántas líneas de
    propiedades hay ni su orden.
    """
    puertos: list[PuertoJack] = []
    nombre_completo = None
    propiedades = ""
    tipo_desc = ""

    def cerrar() -> None:
        if nombre_completo is None:
            return
        cliente, _, puerto = nombre_completo.partition(":")
        props = [p for p in propiedades.split(",") if p]
        puertos.append(PuertoJack(
            cliente=cliente,
            puerto=puerto,
            nombre_completo=nombre_completo,
            direccion="entrada" if "input" in props else "salida",
            tipo="midi" if "midi" in tipo_desc else "audio",
            fisico="physical" in props,
            terminal="terminal" in props,
        ))

    for linea in texto.splitlines():
        if not linea.strip():
            continue
        if linea[0] not in " \t":
            cerrar()
            nombre_completo = linea.strip()
            propiedades = ""
            tipo_desc = ""
        else:
            contenido = linea.strip()
            if contenido.startswith("properties:"):
                propiedades = contenido[len("properties:"):].strip()
            else:
                tipo_desc = contenido
    cerrar()
    return puertos


def dispositivos_alsa(tipo: str = "reproduccion") -> list[DispositivoALSA]:
    """Enumera tarjetas ALSA vía `aplay -l` (reproducción) o `arecord -l` (captura).

    Si el binario no está instalado o no hay tarjetas, devuelve una lista vacía en vez de
    lanzar — no tener una interfaz conectada es un estado normal del sistema, algo que la GUI
    tiene que poder mostrar, no un error de programa.
    """
    if tipo not in TIPOS_DISPOSITIVO:
        raise ValueError(f"tipo debe ser uno de {sorted(TIPOS_DISPOSITIVO)}, no {tipo!r}")
    comando = "aplay" if tipo == "reproduccion" else "arecord"
    try:
        resultado = subprocess.run(
            [comando, "-l"], capture_output=True, text=True, timeout=5
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    return parsear_aplay(resultado.stdout)


def puertos_jack() -> list[PuertoJack]:
    """Enumera los puertos del servidor JACK activo. Lista vacía si no hay servidor corriendo."""
    try:
        resultado = subprocess.run(
            ["jack_lsp", "-pt"], capture_output=True, text=True, timeout=5
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if resultado.returncode != 0:
        return []
    return parsear_jack_lsp(resultado.stdout)


def jack_activo() -> bool:
    """True si hay un servidor JACK corriendo y respondiendo."""
    try:
        resultado = subprocess.run(
            ["jack_samplerate"], capture_output=True, text=True, timeout=3
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return resultado.returncode == 0


def frecuencia_muestreo_jack() -> int | None:
    """Frecuencia de muestreo del servidor JACK activo, o None si no hay servidor."""
    try:
        resultado = subprocess.run(
            ["jack_samplerate"], capture_output=True, text=True, timeout=3
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if resultado.returncode != 0:
        return None
    return int(resultado.stdout.strip())


def tamano_buffer_jack() -> int | None:
    """Tamaño de buffer (en frames) del servidor JACK activo, o None si no hay servidor."""
    try:
        resultado = subprocess.run(
            ["jack_bufsize"], capture_output=True, text=True, timeout=3
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if resultado.returncode != 0:
        return None
    return int(resultado.stdout.strip())


def _diagnostico() -> int:
    """Chequeo rápido de lo que hay disponible en esta máquina.

        python -m engine.audio_engine
    """
    print(f"JACK activo: {jack_activo()}")
    if jack_activo():
        print(f"  frecuencia de muestreo: {frecuencia_muestreo_jack()} Hz")
        print(f"  tamaño de buffer: {tamano_buffer_jack()} frames")
        print("  puertos:")
        for p in puertos_jack():
            flags = []
            if p.fisico:
                flags.append("físico")
            if p.terminal:
                flags.append("terminal")
            sufijo = f" ({', '.join(flags)})" if flags else ""
            print(f"    {p.nombre_completo}  [{p.direccion}/{p.tipo}]{sufijo}")

    for tipo in sorted(TIPOS_DISPOSITIVO):
        dispositivos = dispositivos_alsa(tipo)
        print(f"Tarjetas ALSA ({tipo}): {len(dispositivos)}")
        for d in dispositivos:
            print(f"  {d.hw}  {d.nombre_tarjeta} / {d.nombre_dispositivo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_diagnostico())
