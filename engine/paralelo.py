"""Líneas paralelas por instrumento (como Cortex): SPLIT y MERGE.

Guitarix procesa UNA cadena en serie por instancia (mono → estéreo), así que dos líneas en
paralelo se arman con varias instancias -- un motor por tramo -- unidas por JACK:

    entrada ─► [pre] ─► SPLIT ─┬─► [línea A] ─┬─► MERGE ─► [post] ─► mezclador
                               └─► [línea B] ─┘

Este módulo es el SPLIT y el MERGE: dos clientes JACK propios (`ps_split`, `ps_merge`) con
puertos por instrumento. Son dos clientes separados, no uno, a propósito: con uno solo el grafo
de JACK tendría un ciclo a nivel cliente (split → motores A/B → merge, todos en el mismo
cliente) y JACK lo resolvería agregando un período de latencia. Separados, el orden es lineal y
todo pasa en el mismo ciclo: cero latencia agregada.

Límite del motor, aceptado por el usuario (25/09/2026): un Guitarix solo RECIBE mono (el cliente
`<nombre>_fx` tiene una única entrada). Por eso el MERGE ofrece también una salida `mono`: cuando
hay bloques después del MERGE, las líneas se juntan en mono antes de entrar al motor "post"
(el paneo por línea no aplica ahí); con el MERGE al final, todo sale en estéreo con paneo.

`dividir()` / `unir()` son funciones puras, probadas sin JACK (ver engine/test_paralelo.py).
Ley de balance/paneo: la misma del mezclador (`mixer.ganancias_pan`), centro a ganancia unidad.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from engine.mixer import ganancias_pan
from engine.ruteo import ETIQUETAS, PARAMETROS, AjustesMerge, AjustesSplit  # noqa: F401

try:
    import jack
except ImportError:  # pragma: no cover
    jack = None


def dividir(entrada: np.ndarray, ajustes: AjustesSplit) -> tuple[np.ndarray, np.ndarray]:
    ga, gb = ganancias_pan(1.0, ajustes.balance)
    return entrada * np.float32(ga), entrada * np.float32(gb)


def unir(
    a_l: np.ndarray, a_r: np.ndarray, b_l: np.ndarray, b_r: np.ndarray, ajustes: AjustesMerge,
) -> tuple[np.ndarray, np.ndarray]:
    gal, gar = ganancias_pan(ajustes.nivel_a, ajustes.pan_a)
    gbl, gbr = ganancias_pan(ajustes.nivel_b, ajustes.pan_b)
    signo = -1.0 if ajustes.fase_b else 1.0
    izq = a_l * np.float32(gal) + b_l * np.float32(gbl * signo)
    der = a_r * np.float32(gar) + b_r * np.float32(gbr * signo)
    return izq, der


class ErrorParalelo(Exception):
    pass


@dataclass
class _EstadoLinea:
    split: AjustesSplit = field(default_factory=AjustesSplit)
    merge: AjustesMerge = field(default_factory=AjustesMerge)
    activo: bool = False       # sin split, sus puertos quedan en silencio y no gastan CPU


class RuteadorParalelo:
    """Los dos clientes JACK (SPLIT y MERGE) para todas las líneas de instrumento."""

    def __init__(self, lineas: list[str], prefijo: str = "ps") -> None:
        if jack is None:
            raise ErrorParalelo("Falta el paquete 'jack' (JACK-Client) en el venv del proyecto")
        self.lineas = list(lineas)
        self.estado = {l: _EstadoLinea() for l in lineas}
        self._split = jack.Client(f"{prefijo}_split")
        self._merge = jack.Client(f"{prefijo}_merge")
        self.nombre_split = self._split.name
        self.nombre_merge = self._merge.name
        self._p_split = {}
        self._p_merge = {}
        for l in lineas:
            self._p_split[l] = {
                "in": self._split.inports.register(f"{l}_in"),
                "a": self._split.outports.register(f"{l}_a"),
                "b": self._split.outports.register(f"{l}_b"),
            }
            self._p_merge[l] = {n: self._merge.inports.register(f"{l}_{n}")
                                for n in ("a_L", "a_R", "b_L", "b_R")}
            self._p_merge[l].update({n: self._merge.outports.register(f"{l}_{n}")
                                     for n in ("L", "R", "mono")})
        self._split.set_process_callback(self._procesar_split)
        self._merge.set_process_callback(self._procesar_merge)
        self._activo = False

    # -- Audio (tiempo real) --------------------------------------------------------------

    def _procesar_split(self, frames: int) -> None:
        for l, p in self._p_split.items():
            est = self.estado[l]
            if not est.activo:
                p["a"].get_array().fill(0)
                p["b"].get_array().fill(0)
                continue
            a, b = dividir(p["in"].get_array(), est.split)
            p["a"].get_array()[:] = a
            p["b"].get_array()[:] = b

    def _procesar_merge(self, frames: int) -> None:
        for l, p in self._p_merge.items():
            est = self.estado[l]
            if not est.activo:
                for n in ("L", "R", "mono"):
                    p[n].get_array().fill(0)
                continue
            izq, der = unir(p["a_L"].get_array(), p["a_R"].get_array(),
                            p["b_L"].get_array(), p["b_R"].get_array(), est.merge)
            p["L"].get_array()[:] = izq
            p["R"].get_array()[:] = der
            p["mono"].get_array()[:] = (izq + der) * np.float32(0.5)

    # -- Ciclo de vida -----------------------------------------------------------------

    def iniciar(self) -> None:
        if not self._activo:
            self._split.activate()
            self._merge.activate()
            self._activo = True

    def detener(self) -> None:
        if self._activo:
            self._split.deactivate()
            self._merge.deactivate()
            self._activo = False
        self._split.close()
        self._merge.close()

    # -- Control ----------------------------------------------------------------------

    def activar(self, linea: str, activo: bool) -> None:
        self._estado(linea).activo = activo

    def fijar(self, linea: str, nombre: str, valor: float | bool) -> None:
        """`nombre`: una clave de PARAMETROS ("split.balance", "merge.nivel_a", ...)."""
        est = self._estado(linea)
        if nombre not in PARAMETROS:
            raise ErrorParalelo(f"parámetro desconocido: {nombre!r}")
        objeto, atributo, minimo, maximo, tipo = PARAMETROS[nombre]
        destino = est.split if objeto == "split" else est.merge
        if tipo == "bool":
            setattr(destino, atributo, bool(valor))
            return
        valor = float(valor)
        if not math.isfinite(valor):
            raise ErrorParalelo(f"{nombre} debe ser un número finito, no {valor!r}")
        setattr(destino, atributo, max(minimo, min(maximo, valor)))

    def valores(self, linea: str) -> dict[str, float | bool]:
        est = self._estado(linea)
        salida: dict[str, float | bool] = {}
        for nombre, (objeto, atributo, *_resto) in PARAMETROS.items():
            salida[nombre] = getattr(est.split if objeto == "split" else est.merge, atributo)
        return salida

    def _estado(self, linea: str) -> _EstadoLinea:
        if linea not in self.estado:
            raise ErrorParalelo(f"línea desconocida: {linea!r}")
        return self.estado[linea]

    # -- Puertos (para el cableado, ver engine/motores.py) ---------------------------------

    @property
    def cliente(self) -> "jack.Client":
        """Un cliente JACK activo con el que conectar puertos ajenos (cualquiera puede)."""
        return self._split

    def puerto_split(self, linea: str, cual: str) -> str:
        return f"{self.nombre_split}:{linea}_{cual}"          # in | a | b

    def puerto_merge(self, linea: str, cual: str) -> str:
        return f"{self.nombre_merge}:{linea}_{cual}"          # a_L a_R b_L b_R | L R mono
