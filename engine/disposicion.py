"""Disposición de los bloques de un instrumento en líneas (como Cortex).

Lo que ve el usuario (una fila por línea):

    fila principal:  [pre ...] ◆SPLIT [línea A ...] ◆MERGE [post ...]
    fila paralela:             [línea B ...]

Lo que hay por dentro: un Guitarix por tramo (pre, a, b, post), cada uno con su cadena mono y su
cadena estéreo (ver engine/motores.py). Este módulo traduce una cosa en la otra: mueve bloques
entre motores conservando sus ajustes, ordena cada motor, y aplica las reglas del motor:

1. Dentro de un tramo, los bloques mono van antes que los estéreo (Guitarix procesa su cadena
   mono y después la estéreo). Si el usuario arrastra un estéreo antes de un mono, se reordena
   solo y se avisa.
2. Con líneas paralelas, antes del SPLIT solo van efectos mono (un motor solo recibe mono).
3. El mismo modelo va una vez por tramo (cada unidad existe una vez por motor).

El Amp ("ampstack") es especial: está siempre dentro de cada motor y quitarlo lo tumba (ver
engine/categorias.py). "Quitarlo" o "moverlo" de tramo es ocultarlo (y bypasearlo) en un motor
y mostrarlo en otro con los mismos ajustes. Los tramos nuevos arrancan con el Amp oculto.

Ids hacia afuera: los del tramo "pre" sin prefijo (compatibilidad total con lo anterior), los
demás "a/ts9sim", "b/...", "post/..." -- ver engine/motor_linea.py.
"""

from __future__ import annotations

from typing import Any, Callable

from engine.categorias import PGN_STEREO
from engine.motor_linea import calificar, separar
from presets.preset_manager import valor_rpc

AMP = "ampstack"
SPLIT, MERGE = "@split", "@merge"
TRAMOS = ("pre", "a", "b", "post")


class ErrorDisposicion(ValueError):
    pass


class GestorLineas:
    def __init__(
        self,
        rpc: Any,
        al_cambiar_ruta: Callable[[bool, bool], None] | None = None,
    ) -> None:
        """`rpc` es un MotorLinea (o algo con su interfaz). `al_cambiar_ruta(split, con_post)` se
        llama cuando cambia la forma de la señal, para re-cablear JACK y prender el SPLIT/MERGE."""
        self.rpc = rpc
        self.split = False
        self.amp_visible = {"pre": True, "a": False, "b": False, "post": False}
        self._al_cambiar_ruta = al_cambiar_ruta
        self._estereo: dict[str, bool] | None = None

    # -- Consultas ----------------------------------------------------------------------

    def es_estereo(self, base: str) -> bool:
        if self._estereo is None:
            self._estereo = {p["id"]: bool(p.get("flags", 0) & PGN_STEREO)
                             for p in (self.rpc.plugins() or []) if p.get("id")}
        return self._estereo.get(base, False)

    def tramos_activos(self) -> tuple[str, ...]:
        return TRAMOS if self.split else ("pre",)

    def unidades(self, tramo: str) -> list[str]:
        """Ids base del tramo en orden visual: cadena mono y después la estéreo, Amp solo si
        está visible en ese tramo."""
        motor = self.rpc.motor(tramo)
        salida = []
        for cadena in (0, 1):
            for u in motor.orden_rack(cadena):
                if u == AMP and not self.amp_visible[tramo]:
                    continue
                salida.append(u)
        return salida

    def disposicion(self) -> dict[str, Any]:
        tramos = {t: [calificar(t, u) for u in self.unidades(t)] for t in self.tramos_activos()}
        if self.split:
            principal = tramos["pre"] + [SPLIT] + tramos["a"] + [MERGE] + tramos["post"]
            paralela = tramos["b"]
        else:
            principal, paralela = tramos["pre"], []
        return {"split": self.split, "tramos": tramos, "principal": principal, "paralela": paralela}

    def con_post(self) -> bool:
        return self.split and bool(self.unidades("post"))

    # -- Reorganizar (arrastrar bloques, crear/mover SPLIT y MERGE) ------------------------------

    def disponer(self, principal: list[str], paralela: list[str]) -> list[str]:
        """Deja los bloques exactamente como pide la interfaz. Devuelve avisos (p. ej. si hubo
        que reordenar mono/estéreo). Solo reubica: agregar o quitar bloques va por otro lado."""
        objetivo = self._parsear(principal, paralela)
        actuales = [q for t in self.tramos_activos() for q in (calificar(t, u) for u in self.unidades(t))]
        pedidos = [q for t in TRAMOS for q, _ in objetivo.get(t, [])]
        if sorted(pedidos) != sorted(actuales):
            raise ErrorDisposicion("The requested layout doesn't match the blocks in the GRID (reload)")

        avisos: list[str] = []
        nuevo_split = SPLIT in principal
        if nuevo_split:
            antes = [b for _q, b in objetivo["pre"]]
            if any(self.es_estereo(b) for b in antes):
                raise ErrorDisposicion(
                    "Before the split only mono effects can go (the engine only receives mono)")
        for t, items in objetivo.items():
            bases = [b for _q, b in items]
            if len(bases) != len(set(bases)):
                raise ErrorDisposicion("The same model can only be once in each segment")
            ordenado = sorted(items, key=lambda it: self.es_estereo(it[1]))   # estable
            if ordenado != items:
                objetivo[t] = ordenado
                avisos.append("Stereo effects were placed after the mono ones (engine rule)")

        if nuevo_split and not self.split:
            for t in ("a", "b", "post"):
                self._vaciar(t)
        self.split = nuevo_split

        # 1. Mover entre motores los bloques que cambian de tramo (conservando ajustes).
        for destino, items in objetivo.items():
            for q, base in items:
                origen, _ = separar(q)
                if origen != destino:
                    self._mover(base, origen, destino)
        # 2. Ordenar cada motor y renumerar (el audio sigue al orden).
        for t in self.tramos_activos():
            self._ordenar(t, [b for _q, b in objetivo.get(t, [])])
        self._avisar_ruta()
        return sorted(set(avisos))

    def _parsear(self, principal: list[str], paralela: list[str]) -> dict[str, list[tuple[str, str]]]:
        if principal.count(SPLIT) != principal.count(MERGE) or principal.count(SPLIT) > 1:
            raise ErrorDisposicion("SPLIT and MERGE go together, once per row")
        objetivo: dict[str, list[tuple[str, str]]] = {"pre": []}
        if SPLIT in principal:
            i, j = principal.index(SPLIT), principal.index(MERGE)
            if j < i:
                raise ErrorDisposicion("The MERGE must be after the SPLIT")
            partes = {"pre": principal[:i], "a": principal[i + 1:j], "post": principal[j + 1:], "b": paralela}
        else:
            if paralela:
                raise ErrorDisposicion("There is no parallel line: create it with the split first")
            partes = {"pre": principal}
        for t, ids in partes.items():
            objetivo[t] = [(q, separar(q)[1]) for q in ids]
        return objetivo

    # -- Agregar / quitar bloques --------------------------------------------------------------

    def insertar(self, base: str, tramo: str) -> str:
        """Agrega un bloque al final de su tramo. Devuelve el id calificado."""
        if tramo not in self.tramos_activos():
            raise ErrorDisposicion(f"The segment {tramo!r} does not exist (create the parallel line first)")
        estereo = self.es_estereo(base)
        if self.split and tramo == "pre" and estereo:
            raise ErrorDisposicion("Before the split only mono effects can go (the engine only receives mono)")
        if base in self.unidades(tramo):
            raise ErrorDisposicion("That model is already in this segment")
        motor = self.rpc.motor(tramo)
        if base == AMP:
            self.amp_visible[tramo] = True
            motor.fijar(f"{AMP}.on_off", 1)
        else:
            motor.insertar_unidad(base, "", estereo)
            motor.fijar(f"{base}.on_off", 1)
        motor.renumerar(1 if estereo else 0)
        self._avisar_ruta()
        return calificar(tramo, base)

    def quitar(self, q: str) -> None:
        tramo, base = separar(q)
        if base not in self.unidades(tramo):
            raise ErrorDisposicion(f"{q!r} is not in the GRID")
        motor = self.rpc.motor(tramo)
        if base == AMP:
            self.amp_visible[tramo] = False
            motor.fijar(f"{AMP}.on_off", 0)
        else:
            estereo = self.es_estereo(base)
            motor.quitar_unidad(base, estereo)
            motor.renumerar(1 if estereo else 0)
        self._avisar_ruta()

    def quitar_linea(self) -> None:
        """Deshace el paralelo: A y lo de después del MERGE vuelven al tramo principal (con sus
        ajustes); lo de la línea B se quita."""
        if not self.split:
            return
        destino = [b for b in self.unidades("pre")]
        for t in ("a", "post"):
            for base in self.unidades(t):
                if base in destino:
                    continue            # mismo modelo ya presente en el principal: se descarta
                self._mover(base, t, "pre")
                destino.append(base)
        for t in ("a", "b", "post"):
            self._vaciar(t)
        self.split = False
        self._ordenar("pre", destino)
        self._avisar_ruta()

    # -- Guardar / cargar con el preset ---------------------------------------------------------

    def exportar(self) -> dict[str, Any] | None:
        """Lo que va al preset además de su `cadena` del tramo pre. None = disposición por
        defecto (sin paralelo y con el Amp visible), así los presets simples no cambian."""
        if not self.split and self.amp_visible["pre"]:
            return None
        datos: dict[str, Any] = {"split": self.split, "amp": {"pre": self.amp_visible["pre"]}}
        if self.split:
            datos["tramos"] = {t: self.unidades(t) for t in ("a", "b", "post")}
            datos["amp"].update({t: self.amp_visible[t] for t in ("a", "b", "post")})
        return datos

    def cargar(self, datos: dict[str, Any] | None) -> None:
        """Al cargar un preset (después de armar el tramo pre). Los valores de los parámetros
        llegan justo después, en el `set` normal del preset (nombres calificados)."""
        datos = datos or {}
        amp = datos.get("amp", {})
        self.amp_visible["pre"] = bool(amp.get("pre", True))
        if not self.amp_visible["pre"]:
            self.rpc.motor("pre").fijar(f"{AMP}.on_off", 0)
        if datos.get("split"):
            for t in ("a", "b", "post"):
                self._vaciar(t)
                motor = self.rpc.motor(t)
                for base in datos.get("tramos", {}).get(t, []):
                    if base == AMP:
                        self.amp_visible[t] = True
                        motor.fijar(f"{AMP}.on_off", 1)
                    else:
                        motor.insertar_unidad(base, "", self.es_estereo(base))
                self._ordenar(t, list(datos.get("tramos", {}).get(t, [])))
            self.split = True
        elif self.split:
            for t in ("a", "b", "post"):
                self._vaciar(t)
            self.split = False
        self._avisar_ruta()

    def capturar_extra(self) -> dict[str, Any]:
        """Parámetros de los tramos a/b/post y del SPLIT/MERGE, con nombres calificados."""
        if not self.split:
            return {}
        parametros: dict[str, Any] = {}
        for t in ("a", "b", "post"):
            for base in self.unidades(t):
                q = calificar(t, base)
                for nombre, meta in self.rpc.consultar_unidad(q).items():
                    tipo = meta.get("type")
                    valor = (meta.get("value") or {}).get(nombre)
                    if tipo in ("float", "bool") and valor is not None:
                        parametros[nombre] = bool(valor) if tipo == "bool" else valor
        from engine.ruteo import PARAMETROS as RUTEO   # noqa: PLC0415
        parametros.update({n: v for n, v in self.rpc.obtener(*RUTEO).items() if v is not None})
        return parametros

    # -- Internos -------------------------------------------------------------------------

    def _avisar_ruta(self) -> None:
        if self._al_cambiar_ruta:
            self._al_cambiar_ruta(self.split, self.con_post())

    def _vaciar(self, tramo: str) -> None:
        motor = self.rpc.motor(tramo)
        for cadena in (0, 1):
            for u in list(motor.orden_rack(cadena)):
                if u != AMP:
                    motor.quitar_unidad(u, bool(cadena))
        motor.fijar(f"{AMP}.on_off", 0)
        self.amp_visible[tramo] = False

    def _mover(self, base: str, origen: str, destino: str) -> None:
        src, dst = self.rpc.motor(origen), self.rpc.motor(destino)
        valores = {}
        for nombre, meta in (src.consultar_unidad(base) or {}).items():
            if nombre.endswith((".position", ".pp")) or meta.get("type") not in ("float", "bool", "int"):
                continue
            v = (meta.get("value") or {}).get(nombre)
            if isinstance(v, (int, float, bool)):
                valores[nombre] = valor_rpc(v)
        if base == AMP:
            self.amp_visible[origen] = False
            src.fijar(f"{AMP}.on_off", 0)
            self.amp_visible[destino] = True
        else:
            estereo = self.es_estereo(base)
            dst.insertar_unidad(base, "", estereo)
            src.quitar_unidad(base, estereo)
        planos = [x for par in valores.items() for x in par]
        if planos:
            dst.fijar(*planos)

    def _ordenar(self, tramo: str, bases: list[str]) -> None:
        """Deja el motor del tramo con `bases` en ese orden (mono y estéreo por separado) y
        renumera. El Amp oculto queda al final de la cadena mono, bypaseado."""
        motor = self.rpc.motor(tramo)
        for cadena in (0, 1):
            objetivo = [b for b in bases if (self.es_estereo(b) if b != AMP else False) == bool(cadena)]
            if cadena == 0 and AMP not in objetivo and AMP in motor.orden_rack(0):
                objetivo.append(AMP)
            actual = list(motor.orden_rack(cadena))
            if sorted(actual) != sorted(objetivo):
                raise ErrorDisposicion(f"internal: segment {tramo} has {actual}, expected {objetivo}")
            if actual != objetivo:
                fijas = [u for u in actual if u == AMP]
                for i, u in enumerate(objetivo):
                    if u == AMP:
                        continue
                    antes = next((f for f in objetivo[i + 1:] if f in fijas), "")
                    motor.insertar_unidad(u, antes, bool(cadena))
            motor.renumerar(cadena)
