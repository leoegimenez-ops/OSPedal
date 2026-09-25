"""Categorías de efecto para la interfaz (GRID, selector "+", GIG).

Mapea los ids de unidad de Guitarix a las categorías de la leyenda de referencia que eligió el
usuario (estilo Cortex Control): Amp, Neural Capture, Cab, IR Loader, Overdrive, Compressor, EQ,
Filter, Wah, Pitch, Modulation, Delay, Reverb, Looper, Utility.

Fuente real: `pluginlist` del motor (verificado 25/09/2026 contra Guitarix 0.47.0) trae un campo
`category` propio (Distortion, Fuzz, Echo / Delay, Reverb, Modulation, Neural, Tone Control,
Guitar Effects, Misc...). Se usa como base y se corrige con overrides explícitos donde la
categoría del motor es demasiado general ("Tone Control" mezcla gabinetes, EQs y filtros;
"Guitar Effects" mezcla wahs y compresores).

Qué plugins son insertables en el rack: los que tienen `PGN_GUI` (0x8) y NO `PGN_ALTERNATIVE`
(0x20) -- los alternativos son las variantes internas de un grupo (las válvulas 12AX7, 6V6, etc.
que se eligen *dentro* de `ampstack`, no bloques propios) -- y que NO son fijos (ver abajo).
Mono vs estéreo: `PGN_STEREO` (0x1) -- el motor tiene una cadena mono y una estéreo, y cada
plugin entra solo en la que corresponde (`gx_plugin.h:174-187`).

Bloques fijos: `PGN_PRE` (0x2), `PGN_POST` (0x4) o `PGN_FIXED_GUI` (0x800). Son módulos de
posición fija del motor (`ampstack`, `amp`, `amp.clip`, `amp.bass_boost`, `con`, `noise_gate`,
`shaper`), no bloques del rack: no tienen el parámetro de visibilidad que `insert_rack_unit` /
`remove_rack_unit` tocan, y Guitarix 0.47.0 hace SEGFAULT al insertarlos o quitarlos
(`jsonrpc.cpp:848/864`, `get_param()[id_box_visible()]` sobre un parámetro inexistente).
Verificado el 25/09/2026 insertando y quitando los 122 candidatos uno por uno contra un motor
real aislado: exactamente estos 7 lo tumban, los otros 115 no. Ninguno de los que funcionan
tiene alguno de esos tres flags.
"""

from __future__ import annotations

from typing import Any

PGN_STEREO = 0x1
PGN_PRE = 0x2
PGN_POST = 0x4
PGN_GUI = 0x8
PGN_ALTERNATIVE = 0x20
PGN_FIXED_GUI = 0x800
_FLAGS_FIJO = PGN_PRE | PGN_POST | PGN_FIXED_GUI

# Orden en que se muestran en el selector "+" (el mismo de la leyenda de referencia).
CATEGORIAS: list[tuple[str, str]] = [
    ("amp", "Amp"),
    ("neural", "Neural Capture"),
    ("cab", "Cab"),
    ("ir", "IR Loader"),
    ("overdrive", "Overdrive"),
    ("compressor", "Compressor"),
    ("eq", "EQ"),
    ("filter", "Filter"),
    ("wah", "Wah"),
    ("pitch", "Pitch"),
    ("modulation", "Modulation"),
    ("delay", "Delay"),
    ("reverb", "Reverb"),
    ("looper", "Looper"),
    ("utility", "Utility"),
]
CLAVES = frozenset(c for c, _ in CATEGORIAS)

_OVERRIDES: dict[str, str] = {
    "ampstack": "amp", "amp": "amp", "poweramp": "amp",
    "nam": "neural", "snam": "neural", "mnam": "neural",
    "rtneural": "neural", "srtneural": "neural", "mrtneural": "neural",
    "cab": "cab", "cab_st": "cab", "pre": "cab", "pre_st": "cab",
    "IR": "ir", "jconv": "ir", "jconv_mono": "ir", "con": "ir",
    "compressor": "compressor", "mbc": "compressor", "mbcs": "compressor",
    "expander": "compressor",
    "GCB_95": "wah", "crybaby": "wah", "rolandwah": "wah",
    "low_highpass": "filter", "moog": "filter", "hfb": "filter", "biquad": "filter",
    "smbPitchShift": "pitch",
    "dubber": "looper", "recorder": "looper", "st_recorder": "looper",
    "lpbboost": "overdrive", "rangem": "overdrive", "highbooster": "overdrive",
    "hogsfoot": "overdrive", "mole": "overdrive",
}

_POR_CATEGORIA_GX: dict[str, str] = {
    "Distortion": "overdrive",
    "Fuzz": "overdrive",
    "Echo / Delay": "delay",
    "Reverb": "reverb",
    "Modulation": "modulation",
    "Neural": "neural",
    "Tone Control": "eq",
}


def categoria(unidad: str, categoria_gx: str | None = None) -> str:
    """Categoría de interfaz para un id de unidad del motor. Nunca falla: lo desconocido cae
    en "utility"."""
    if unidad in _OVERRIDES:
        return _OVERRIDES[unidad]
    if "wah" in unidad:
        return "wah"
    return _POR_CATEGORIA_GX.get(categoria_gx or "", "utility")


def es_fijo(plugin: dict[str, Any]) -> bool:
    """Módulo de posición fija: nunca se inserta ni se quita del rack (tumba al motor)."""
    return bool(plugin.get("flags", 0) & _FLAGS_FIJO)


def fijos(pluginlist: list[dict[str, Any]]) -> frozenset[str]:
    return frozenset(p["id"] for p in pluginlist if p.get("id") and es_fijo(p))


def insertables(pluginlist: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Plugins que se pueden agregar como bloque, ya categorizados y ordenados por nombre.

    `pluginlist` es la respuesta cruda de `GuitarixRPC.plugins()`.
    """
    salida = []
    for p in pluginlist:
        uid = p.get("id")
        flags = p.get("flags", 0)
        if not flags & PGN_GUI or flags & PGN_ALTERNATIVE or es_fijo(p):
            continue
        salida.append({
            "id": uid,
            "nombre": _nombre(p),
            "categoria": categoria(uid, p.get("category")),
            "estereo": bool(flags & PGN_STEREO),
        })
    salida.sort(key=lambda x: x["nombre"].lower())
    return salida


# Tempo: qué parámetro de cada delay sigue al BPM del preset (la ventana Tempo / TAP).
# Relevado con queryunit el 25/09/2026: la mayoría tiene un parámetro BPM nativo [24..360]; los
# que van en ms reciben la negra (60000 / bpm) dentro de su rango. Los multibanda (mbdel, mbe)
# no se tocan: cada banda tiene su tiempo a propósito. "lfobpm" tampoco: es la modulación.
SINCRONIZABLES: dict[str, list[tuple[str, str, float, float]]] = {
    # unidad: [(parámetro, "bpm" | "ms", mínimo, máximo)]
    "delay": [("delay.bpm", "bpm", 24, 360)],
    "echo": [("echo.bpm", "bpm", 24, 360)],
    "dide": [("dide.bpm", "bpm", 24, 360)],
    "didest": [("didest.bpm", "bpm", 24, 360)],
    "stereodelay": [("stereodelay.lbpm", "bpm", 24, 360), ("stereodelay.rbpm", "bpm", 24, 360)],
    "stereoecho": [("stereoecho.lbpm", "bpm", 24, 360), ("stereoecho.rbpm", "bpm", 24, 360)],
    "duckDelay": [("duckDelay.time", "ms", 1, 2000)],
    "duckDelaySt": [("duckDelaySt.time", "ms", 1, 2000)],
    "reversedelay": [("reversedelay.time", "ms", 200, 2000)],
}


def pares_tempo(unidades: list[str], bpm: float) -> list[Any]:
    """Pares `set` para llevar los delays presentes al tempo dado."""
    pares: list[Any] = []
    for unidad in unidades:
        for nombre, tipo, minimo, maximo in SINCRONIZABLES.get(unidad, []):
            valor = bpm if tipo == "bpm" else 60000.0 / bpm
            pares += [nombre, round(min(maximo, max(minimo, valor)), 2)]
    return pares


# El motor tiene slots duplicados con el mismo nombre (segunda instancia de NAM/RTNeural): sin
# esto el selector "+" mostraría dos "Neural Amp Modeler" indistinguibles.
_NOMBRES_OVERRIDE = {
    "snam": "Neural Amp Modeler 2",
    "srtneural": "RTNeural Network Engine 2",
}


def _nombre(p: dict[str, Any]) -> str:
    return _NOMBRES_OVERRIDE.get(p["id"]) or p.get("name") or p["id"]


def nombres(pluginlist: list[dict[str, Any]]) -> dict[str, str]:
    """id -> nombre legible, para todos los plugins (insertables o no)."""
    return {p["id"]: _nombre(p) for p in pluginlist if p.get("id")}
