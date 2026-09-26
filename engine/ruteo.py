"""Parámetros del SPLIT y del MERGE (líneas paralelas), sin dependencias pesadas.

Separado de engine/paralelo.py (que usa numpy y JACK) para que el controlador y la API puedan
nombrar estos parámetros -- guardarlos en un preset, mostrarlos en el panel -- sin importar el
audio. Nombres "split.*" / "merge.*": así viajan en los mismos pares nombre/valor que los
parámetros de Guitarix (ver engine/motor_linea.py).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AjustesSplit:
    # -1 = todo a la línea A, 0 = las dos a nivel completo (split en "Y"), +1 = todo a la B.
    balance: float = 0.0


@dataclass
class AjustesMerge:
    nivel_a: float = 1.0
    nivel_b: float = 1.0
    pan_a: float = 0.0
    pan_b: float = 0.0
    fase_b: bool = False       # invertir la polaridad de la línea B (cancelaciones entre amps)


PARAMETROS = {
    # nombre: (objeto, atributo, mínimo, máximo, tipo) -- lo que el panel muestra al tocar el
    # bloque SPLIT o MERGE, con el mismo formato que los parámetros de un plugin.
    "split.balance": ("split", "balance", -1.0, 1.0, "float"),
    "merge.nivel_a": ("merge", "nivel_a", 0.0, 2.0, "float"),
    "merge.nivel_b": ("merge", "nivel_b", 0.0, 2.0, "float"),
    "merge.pan_a": ("merge", "pan_a", -1.0, 1.0, "float"),
    "merge.pan_b": ("merge", "pan_b", -1.0, 1.0, "float"),
    "merge.fase_b": ("merge", "fase_b", 0, 1, "bool"),
}
ETIQUETAS = {
    "split.balance": "A / B",
    "merge.nivel_a": "Level A", "merge.nivel_b": "Level B",
    "merge.pan_a": "Pan A", "merge.pan_b": "Pan B",
    "merge.fase_b": "Phase B",
}
