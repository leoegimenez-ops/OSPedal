"""Un instrumento visto como UN motor, aunque por dentro sean hasta cuatro (líneas paralelas).

El controlador y la API hablan con `MotorLinea` exactamente como con un `GuitarixRPC`. La
diferencia está en los nombres:

    "ts9sim.drive"       → motor del tramo "pre" (como siempre: todo lo anterior sigue igual)
    "a/ts9sim.drive"     → motor de la línea A      ("b/...", "post/..." igual)
    "split.balance"      → el SPLIT   (engine/paralelo.py)
    "merge.nivel_b"      → el MERGE

Así un preset, una escena o un stomp guardan nombres de parámetro calificados y todo lo demás
(pares_rpc, escenas Cortex, stomps, tempo) funciona sin saber que hay varios motores.
"""

from __future__ import annotations

from typing import Any, Callable

from engine.ruteo import PARAMETROS as PARAMETROS_RUTEO

TRAMOS_EXTRA = ("a", "b", "post")


def separar(nombre: str) -> tuple[str, str]:
    """"a/ts9sim.drive" -> ("a", "ts9sim.drive"); "ts9sim.drive" -> ("pre", ...);
    "merge.nivel_a" -> ("ruteo", "merge.nivel_a")."""
    if nombre in PARAMETROS_RUTEO:
        return "ruteo", nombre
    if "/" in nombre:
        tramo, resto = nombre.split("/", 1)
        if tramo in TRAMOS_EXTRA:
            return tramo, resto
    return "pre", nombre


def calificar(tramo: str, nombre: str) -> str:
    return nombre if tramo in ("pre", "ruteo") else f"{tramo}/{nombre}"


class MotorLinea:
    def __init__(
        self,
        pre: Any,
        abrir_tramo: Callable[[str], Any] | None = None,
        fijar_ruteo: Callable[[str, Any], None] | None = None,
        leer_ruteo: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        """`abrir_tramo(tramo)` devuelve un cliente RPC conectado al motor de ese tramo
        (arrancándolo si hace falta). `fijar_ruteo`/`leer_ruteo` hablan con el SPLIT/MERGE."""
        self.pre = pre
        self._abrir_tramo = abrir_tramo
        self._fijar_ruteo = fijar_ruteo
        self._leer_ruteo = leer_ruteo
        self._motores: dict[str, Any] = {"pre": pre}

    def motor(self, tramo: str) -> Any:
        if tramo not in self._motores:
            if self._abrir_tramo is None:
                raise ConnectionError(f"no hay motor para el tramo {tramo!r}")
            self._motores[tramo] = self._abrir_tramo(tramo)
        return self._motores[tramo]

    def tiene(self, tramo: str) -> bool:
        return tramo in self._motores

    # -- Parámetros: se reparten por tramo --------------------------------------------------

    def fijar(self, *pares: Any) -> None:
        if len(pares) % 2:
            raise ValueError("fijar() requiere pares nombre/valor: la cantidad debe ser par.")
        grupos: dict[str, list[Any]] = {}
        for nombre, valor in zip(pares[::2], pares[1::2]):
            tramo, local = separar(nombre)
            if tramo == "ruteo":
                if self._fijar_ruteo is None:
                    raise ConnectionError("el SPLIT/MERGE no está disponible")
                self._fijar_ruteo(local, valor)
                continue
            grupos.setdefault(tramo, []).extend((local, valor))
        for tramo, planos in grupos.items():
            self.motor(tramo).fijar(*planos)

    def obtener(self, *nombres: str) -> dict[str, Any]:
        grupos: dict[str, list[str]] = {}
        salida: dict[str, Any] = {}
        for nombre in nombres:
            tramo, local = separar(nombre)
            if tramo == "ruteo":
                salida[nombre] = (self._leer_ruteo() if self._leer_ruteo else {}).get(nombre)
                continue
            grupos.setdefault(tramo, []).append(local)
        for tramo, locales in grupos.items():
            for k, v in (self.motor(tramo).obtener(*locales) or {}).items():
                salida[calificar(tramo, k)] = v
        return salida

    def consultar_unidad(self, unidad: str) -> dict[str, Any]:
        tramo, local = separar(unidad)
        crudo = self.motor(tramo).consultar_unidad(local) or {}
        if tramo == "pre":
            return crudo
        return {
            calificar(tramo, k): {**meta, "value": {calificar(tramo, vk): vv
                                                    for vk, vv in (meta.get("value") or {}).items()}}
            for k, meta in crudo.items()
        }

    # -- Rack: `orden_rack`/`renumerar` sin tramo son del "pre" (compatibilidad) -------------

    def orden_rack(self, cadena: int = 0) -> list[str]:
        return list(self.pre.orden_rack(cadena))

    def orden_tramo(self, tramo: str, cadena: int) -> list[str]:
        return list(self.motor(tramo).orden_rack(cadena))

    def renumerar(self, cadena: int = 0) -> None:
        self.pre.renumerar(cadena)

    def renumerar_tramo(self, tramo: str, cadena: int) -> None:
        self.motor(tramo).renumerar(cadena)

    def insertar_unidad(self, unidad: str, antes_de: str = "", estereo: bool = False) -> None:
        tramo, local = separar(unidad)
        _, antes_local = separar(antes_de) if antes_de else ("pre", "")
        self.motor(tramo).insertar_unidad(local, antes_local, estereo)

    def quitar_unidad(self, unidad: str, estereo: bool = False) -> None:
        tramo, local = separar(unidad)
        self.motor(tramo).quitar_unidad(local, estereo)

    # -- Todo lo demás es del motor "pre" (el que recibe el instrumento) ---------------------

    def __getattr__(self, nombre: str) -> Any:
        # plugins, bancos, presets, set_preset, existe_preset, version, estado, carga_cpu,
        # afinador, frecuencia_afinador, notificar, llamar, cargar_nam...
        return getattr(self.pre, nombre)

    def cerrar(self) -> None:
        for m in self._motores.values():
            try:
                m.cerrar()
            except Exception:  # noqa: BLE001
                pass
