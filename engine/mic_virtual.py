"""Micrófono virtual: posición + distancia + tipo, como aproximación de EQ.

Guitarix no modela esto — verificado en el código fuente del motor
(`gx_convolver.h`, `gx_jconv_settings.h`): el convolver es un motor de convolución
de IR estática con herramientas para *recortar* el archivo (delay, offset,
length, corrección de ganancia), sin ningún concepto de posición, distancia ni
tipo de micrófono. Cortex Control sí lo tiene (bloque Cab, no el IR Loader):
perillas POSITION/DISTANCE arrastrables sobre un gráfico del parlante, más un
selector de modelo de micrófono. Ver `docs/mic-virtual.md`.

Este módulo **no** es una simulación acústica 3D (eso requeriría modelar el
patrón de radiación real del parlante y el patrón polar del micrófono, un
proyecto de DSP mucho más grande). Es una aproximación por EQ, apoyada en tres
hechos físicos documentados y citados en `docs/mic-virtual.md`:

1. Mover el mic del centro del cono (dust cap) al borde apaga los agudos
   progresivamente — consistente entre múltiples fuentes de audio profesional.
2. El "proximity effect" agrega graves cerca de la fuente: hasta ~16dB en
   cardioide/cinta, casi nulo en omnidireccional, y cae rápido con la
   distancia (no es lineal).
3. Ley del inverso del cuadrado: -6dB por cada duplicación de distancia en
   campo lejano.

**Importante**: el nivel general (nº 3) queda afuera a propósito. Un knob de
"distancia" que además baja el volumen es una mala idea de interfaz — el
usuario ya tiene LEVEL para eso. Acá DISTANCIA solo cambia el carácter
tonal (menos graves de proximidad, un poco más de sala), nunca el volumen.

Esto es un punto de partida matemáticamente razonable, **no un resultado
afinado por oído**. Los valores están pensados para ser plausibles, no para
sonar "correctos" — eso solo se puede juzgar escuchando contra una captura
real, y todavía no hay un Guitarix corriendo para hacer esa prueba.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Tau de la caída del proximity effect: a distancia=0.25 el boost ya cayó a
# 1/e (~37%) de su máximo. El proximity effect es un fenómeno de cercanía
# extrema (pulgadas), así que tiene que apagarse rápido, no linealmente.
_TAU_PROXIMIDAD = 0.25

# Tope del "más sala" sugerido al alejarse. Deliberadamente chico (15%): es
# una sugerencia de carácter, no algo que deba dominar la mezcla.
_TOPE_REVERB_SUGERIDO = 0.15

# Frecuencia fija del shelf de graves del proximity effect. Los mics reales
# muestran el boost sobre todo por debajo de 100-150Hz.
_FREQ_SHELF_GRAVES = 150


@dataclass(frozen=True)
class TipoMic:
    """Caracterización de un tipo de micrófono para el modelo.

    `brillo_base_hz` / `oscurecimiento_hz`: frecuencia de corte de un
    pasabajos en posicion=0 (centro, más brillante) y posicion=1 (borde, más
    oscuro). `proximidad_db_max`: boost de graves a distancia=0.
    """

    nombre: str
    brillo_base_hz: float
    oscurecimiento_hz: float
    proximidad_db_max: float


# Los tres tipos y sus números están anclados en lo que documenta la
# investigación (docs/mic-virtual.md): ribbon = proximity effect más fuerte de
# los tres pero más oscuro en general; omnidireccional = casi sin proximity
# effect pero el más brillante/extendido en agudos; dinámico cardioide en el
# medio de ambos ejes — es el "SM57" de referencia de toda la industria.
TIPOS_MIC = {
    "dinamico": TipoMic("Dinámico (cardioide)", brillo_base_hz=9000, oscurecimiento_hz=5500, proximidad_db_max=10.0),
    "cinta": TipoMic("Cinta (figura de 8)", brillo_base_hz=7000, oscurecimiento_hz=4500, proximidad_db_max=16.0),
    "condensador": TipoMic("Condensador (omni)", brillo_base_hz=12000, oscurecimiento_hz=4000, proximidad_db_max=3.0),
}


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def calcular(posicion: float, distancia: float, tipo: str = "dinamico") -> dict:
    """Calcula los parámetros de EQ para una posición/distancia/tipo dados.

    `posicion` y `distancia` van de 0.0 a 1.0 (se recortan si vienen afuera
    de ese rango). Devuelve un diccionario con los valores ya calculados,
    independiente de cómo se apliquen después al motor — así el modelo se
    puede probar sin ninguna conexión RPC.
    """
    if tipo not in TIPOS_MIC:
        raise ValueError(f"Tipo de mic desconocido: {tipo!r}. Válidos: {', '.join(TIPOS_MIC)}")
    mic = TIPOS_MIC[tipo]
    posicion = _clamp01(posicion)
    distancia = _clamp01(distancia)

    pasabajos_hz = mic.brillo_base_hz + (mic.oscurecimiento_hz - mic.brillo_base_hz) * posicion
    graves_shelf_db = mic.proximidad_db_max * math.exp(-distancia / _TAU_PROXIMIDAD)
    reverb_wet_sugerido = _TOPE_REVERB_SUGERIDO * distancia

    return {
        "tipo_mic": mic.nombre,
        "pasabajos_hz": round(pasabajos_hz),
        "graves_shelf_hz": _FREQ_SHELF_GRAVES,
        "graves_shelf_db": round(graves_shelf_db, 1),
        "reverb_wet_sugerido": round(reverb_wet_sugerido, 3),
    }


def aplicar(rpc, posicion: float, distancia: float, tipo: str = "dinamico", unidad_eq: str = "eq") -> dict:
    """Empuja el modelo calculado al bloque EQ del motor, vía RPC.

    ADVERTENCIA — sin verificar: los ids `<unidad>.band1.*` / `<unidad>.band3.*`
    son una suposición (Cortex Control mostraba "Parametric-3", lo que sugiere
    3 bandas disponibles; no es evidencia de que Guitarix nombre sus bandas
    igual). Además puede hacer falta fijar el *tipo* de cada banda (shelf vs.
    peak) con un parámetro aparte antes de que freq/gain tengan efecto — no
    confirmado. Sirve para probar la lógica de conexión, no para dar por
    buena la asignación de parámetros hasta correrlo contra un Guitarix real.
    """
    datos = calcular(posicion, distancia, tipo)
    rpc.fijar(
        f"{unidad_eq}.band1.freq", datos["graves_shelf_hz"],
        f"{unidad_eq}.band1.gain", datos["graves_shelf_db"],
        f"{unidad_eq}.band3.freq", datos["pasabajos_hz"],
    )
    return datos
