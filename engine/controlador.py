"""Estado de performance: traduce acciones en cambios sobre el motor.

Es la capa que une los tres módulos: recibe una `Accion` (venga del MIDI, de la GUI o de la
PWA), la aplica sobre la setlist cargada en RAM y empuja el resultado a Guitarix por RPC.

Mantiene el estado que no vive ni en la setlist ni en el motor: qué banco se está mirando, qué
preset suena, en qué modo está y qué stomps se pisaron desde que se cargó el preset.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from engine.categorias import fijos
from engine.midi_engine import Accion
from presets.preset_manager import (
    CADENAS, MAX_ESCENAS, MAX_PRESETS, PRESETS_POR_BANCO, Escena, Preset, Setlist, valor_rpc,
)


class Modo(str, Enum):
    PRESET = "preset"
    STOMP = "stomp"
    SCENE = "scene"


# Tap tempo: más de este tiempo entre pisadas y se asume que es una serie nueva, no un tempo
# lentísimo. 2 segundos son 30 BPM, por debajo del mínimo musical útil.
CORTE_TAP_SEGUNDOS = 2.0
TAPS_PROMEDIADOS = 4


@dataclass
class ControladorEscenario:
    setlist: Setlist
    rpc: Any
    reloj: Callable[[], float] = time.monotonic

    banco_visible: int = 0
    banco_activo: int = 0
    posicion_activa: int = 0
    modo: Modo = Modo.PRESET
    escena_activa: str | None = None
    tempo_bpm: float | None = None

    # Estado de los stomps del preset cargado. Arranca como lo define el preset y cambia a
    # medida que el músico pisa; no se persiste, se reinicia al cambiar de preset.
    _stomps: dict[str, bool] = field(default_factory=dict, repr=False)
    _taps: list[float] = field(default_factory=list, repr=False)
    # Ids de bloques fijos del motor; se piden una sola vez (la lista de plugins no cambia).
    _fijas: frozenset[str] | None = field(default=None, repr=False)
    # Problema no fatal del último preset aplicado (p.ej. preset base inexistente en el motor).
    advertencia: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.setlist.total_presets:
            self.cargar(self.banco_activo, self.posicion_activa, aplicar_al_motor=False)

    # -- Estado -----------------------------------------------------------------------

    @property
    def preset(self) -> Preset:
        return self.setlist.preset(self.banco_activo, self.posicion_activa)

    @property
    def indice_activo(self) -> int:
        return self.setlist.indice_de(self.banco_activo, self.posicion_activa)

    def stomp_activo(self, numero: int) -> bool:
        stomps = self.preset.stomps
        if not 0 <= numero < len(stomps):
            raise IndexError(f"El preset no tiene el stomp {numero}")
        return self._stomps.get(stomps[numero].unidad, stomps[numero].activo)

    # -- Carga de preset --------------------------------------------------------------

    def cargar(self, banco: int, posicion: int, aplicar_al_motor: bool = True) -> Preset:
        preset = self.setlist.preset(banco, posicion)
        self.banco_activo = banco
        self.posicion_activa = posicion
        self.banco_visible = banco
        self.escena_activa = None
        self._stomps = {s.unidad: s.activo for s in preset.stomps}
        if preset.tempo_bpm is not None:
            self.tempo_bpm = preset.tempo_bpm
        if aplicar_al_motor:
            self._aplicar(preset)
        return preset

    def cargar_indice(self, indice: int) -> Preset:
        return self.cargar(indice // PRESETS_POR_BANCO, indice % PRESETS_POR_BANCO)

    def _aplicar(self, preset: Preset, incluir_base: bool = True) -> None:
        """Empuja el preset al motor: preset base (opcional) y un único `set` con todo lo demás.

        `incluir_base=False` es para cambio de escena: el preset base ya está cargado en el
        motor, así que reenviar `setpreset` sería un recargado completo innecesario -- y
        potencialmente un corte de audio -- para lo que tiene que ser un ajuste liviano de
        parámetros. Confirmado en vivo que sin este parámetro, `_cambiar_escena()` reenviaba
        `setpreset` en cada pisada de escena (ver `engine/test_integracion.py`).
        """
        self.advertencia = None
        if incluir_base and preset.guitarix_banco and preset.guitarix_preset:
            try:
                self.rpc.set_preset(preset.guitarix_banco, preset.guitarix_preset)
            except ValueError as exc:
                # Preset base inexistente en el motor: se sigue con la cadena y los valores del
                # preset en vez de cortar el cambio a mitad de camino (ver GuitarixRPC.set_preset).
                self.advertencia = str(exc)
        if incluir_base and preset.cadena:
            self._sincronizar_cadena(preset.cadena)
        pares = preset.pares_rpc(self.escena_activa)
        # Los stomps pisados en runtime ganan sobre lo que dice el preset.
        valores = dict(zip(pares[::2], pares[1::2]))
        for unidad, activo in self._stomps.items():
            valores[f"{unidad}.on_off"] = valor_rpc(activo)
        if valores:
            planos: list[Any] = []
            for nombre, valor in valores.items():
                planos += [nombre, valor]
            self.rpc.fijar(*planos)

    def _sincronizar_cadena(self, cadena: dict[str, list[str]]) -> None:
        """Deja el rack con exactamente los bloques guardados en el preset, en ese orden.

        Si el orden actual ya coincide no se toca nada (cambiar de preset entre dos que usan la
        misma cadena no tiene por qué sacar y volver a meter bloques). Si difiere, se vacía la
        cadena y se reinsertan en orden: más simple y más fácil de verificar que calcular
        movimientos mínimos, y los valores de cada bloque (incluido su on/off) se reaplican igual
        en el `set` que viene justo después.

        Los bloques fijos (`ampstack` y compañía, ver `engine/categorias.py`) NUNCA se quitan ni
        se insertan: Guitarix hace segfault. Quedan donde están y los demás se insertan delante
        del fijo que les sigue en el orden guardado (`insert_rack_unit(unidad, antes_de, ...)`).
        """
        fijas = self._unidades_fijas()
        for clave, estereo in CADENAS.items():
            if clave not in cadena:
                continue
            objetivo = cadena[clave]
            actual = list(self.rpc.orden_rack(estereo))
            if actual == objetivo:
                continue
            for unidad in actual:
                if unidad not in fijas:
                    self.rpc.quitar_unidad(unidad, bool(estereo))
            presentes_fijas = [u for u in actual if u in fijas]
            for i, unidad in enumerate(objetivo):
                if unidad in fijas:
                    continue
                antes_de = next((u for u in objetivo[i + 1:] if u in presentes_fijas), "")
                self.rpc.insertar_unidad(unidad, antes_de, bool(estereo))

    def _unidades_fijas(self) -> frozenset[str]:
        if self._fijas is None:
            self._fijas = fijos(self.rpc.plugins())
        return self._fijas

    # -- Captura del estado actual (botón guardar y "+ New scene" del GIG) ------------

    def capturar(self) -> tuple[dict[str, list[str]], dict[str, Any]]:
        """Lee del motor la cadena actual y el valor de cada parámetro controlable de cada
        bloque. Solo `float` y `bool`: lo mismo que la interfaz deja tocar (ver
        `server/api.py`, `_parametros_unidad`) -- guardar selectores internos como
        `<unidad>.position` metería en el preset coordenadas de la GUI de escritorio."""
        cadena = {clave: list(self.rpc.orden_rack(est)) for clave, est in CADENAS.items()}
        parametros: dict[str, Any] = {}
        for unidades in cadena.values():
            for unidad in unidades:
                for nombre, meta in self.rpc.consultar_unidad(unidad).items():
                    tipo = meta.get("type")
                    if tipo not in ("float", "bool"):
                        continue
                    valor = meta.get("value", {}).get(nombre)
                    if valor is None:
                        continue
                    parametros[nombre] = bool(valor) if tipo == "bool" else valor
        return cadena, parametros

    def guardar_en_preset(self) -> Preset:
        """Guarda el estado real del motor en el preset activo (cadena + parámetros). Los
        stomps pisados pasan a ser el estado guardado: lo que suena es lo que queda."""
        preset = self.preset
        cadena, parametros = self.capturar()
        preset.cadena = cadena
        preset.parametros = parametros
        for stomp in preset.stomps:
            stomp.activo = bool(parametros.get(stomp.parametro, stomp.activo))
        self._stomps = {s.unidad: s.activo for s in preset.stomps}
        return preset

    def nueva_escena(self) -> str:
        """Crea una escena nueva con el estado actual y la deja activa. Nombre automático
        ("Scene C", ...) -- el nombre se edita desde el sistema, no desde la app remota."""
        preset = self.preset
        if len(preset.escenas) >= MAX_ESCENAS:
            raise ValueError(f"El preset ya tiene {MAX_ESCENAS} escenas (A-H)")
        letra = chr(ord("A") + len(preset.escenas))
        _, parametros = self.capturar()
        preset.escenas.append(Escena(f"Scene {letra}", parametros))
        self.escena_activa = f"Scene {letra}"
        return self.escena_activa

    # -- Ejecución de acciones --------------------------------------------------------

    def ejecutar(self, accion: Accion, parametro: int | None = None) -> str:
        """Aplica una acción y devuelve una descripción corta de lo que pasó.

        La descripción va al display del equipo y al log; que las acciones sean nombrables
        facilita depurar una pedalera en vivo.
        """
        if accion is Accion.CAMBIAR_PRESET:
            if parametro is None:
                raise ValueError("cambiar_preset necesita un índice")
            if not 0 <= parametro < MAX_PRESETS:
                return f"Preset {parametro} fuera de rango"
            try:
                preset = self.cargar_indice(parametro)
            except ValueError:
                return f"Preset {parametro} vacío"
            return f"Preset {parametro}: {preset.nombre}"

        if accion is Accion.PRESET_EN_BANCO:
            if parametro is None:
                raise ValueError("preset_en_banco necesita una posición")
            try:
                preset = self.cargar(self.banco_visible, parametro)
            except ValueError:
                return f"Posición {parametro} vacía en el banco"
            return f"{preset.nombre}"

        if accion in (Accion.PRESET_SIGUIENTE, Accion.PRESET_ANTERIOR):
            paso = 1 if accion is Accion.PRESET_SIGUIENTE else -1
            return self._mover_preset(paso)

        if accion in (Accion.BANCO_SIGUIENTE, Accion.BANCO_ANTERIOR):
            paso = 1 if accion is Accion.BANCO_SIGUIENTE else -1
            return self._mover_banco(paso)

        if accion is Accion.TOGGLE_STOMP:
            if parametro is None:
                raise ValueError("toggle_stomp necesita un número de stomp")
            return self._toggle_stomp(parametro)

        if accion is Accion.ESCENA:
            if parametro is None:
                raise ValueError("escena necesita un índice")
            return self._cambiar_escena(parametro)

        if accion is Accion.MODO:
            modos = list(Modo)
            if parametro is None or not 0 <= parametro < len(modos):
                return "Modo inválido"
            self.modo = modos[parametro]
            return f"Modo {self.modo.value}"

        if accion is Accion.AFINADOR:
            self.rpc.notificar("switch_tuner", 1)
            return "Afinador"

        if accion is Accion.TAP_TEMPO:
            return self._tap_tempo()

        return f"Acción no implementada: {accion.value}"

    # -- Navegación -------------------------------------------------------------------

    def _mover_preset(self, paso: int) -> str:
        """Avanza al siguiente preset que exista, saltando posiciones vacías.

        Los bancos incompletos dejan huecos en la numeración; al navegar de a uno hay que
        saltearlos o el músico se encuentra con un pedal que "no hace nada".
        """
        indices = [i for i, _, _ in self.setlist]
        if not indices:
            return "Setlist vacía"
        actual = self.indice_activo
        posicion = indices.index(actual) if actual in indices else 0
        nueva = (posicion + paso) % len(indices)
        preset = self.cargar_indice(indices[nueva])
        return f"{preset.nombre}"

    def _mover_banco(self, paso: int) -> str:
        """Cambia el banco que se está mirando, sin tocar el sonido.

        En un equipo de piso, subir de banco es navegar: recién suena cuando se elige un preset
        del banco nuevo. Cambiar el sonido al navegar sería un accidente en pleno tema.
        """
        total = len(self.setlist.bancos)
        if not total:
            return "Setlist vacía"
        self.banco_visible = (self.banco_visible + paso) % total
        return f"Banco {self.banco_visible + 1}: {self.setlist.bancos[self.banco_visible].nombre}"

    # -- Stomps y escenas -------------------------------------------------------------

    def _toggle_stomp(self, numero: int) -> str:
        stomps = self.preset.stomps
        if not 0 <= numero < len(stomps):
            return f"Sin stomp {numero + 1}"
        stomp = stomps[numero]
        nuevo = not self.stomp_activo(numero)
        self._stomps[stomp.unidad] = nuevo
        # Un solo parámetro: es el camino más corto posible al motor.
        self.rpc.fijar(stomp.parametro, valor_rpc(nuevo))
        return f"{stomp.etiqueta} {'ON' if nuevo else 'OFF'}"

    def _cambiar_escena(self, indice: int) -> str:
        escenas = self.preset.escenas
        if not 0 <= indice < len(escenas):
            return f"Sin escena {indice + 1}"
        self.escena_activa = escenas[indice].nombre
        self._aplicar(self.preset, incluir_base=False)
        return f"Escena: {self.escena_activa}"

    # -- Tap tempo --------------------------------------------------------------------

    def _tap_tempo(self) -> str:
        ahora = self.reloj()
        if self._taps and ahora - self._taps[-1] > CORTE_TAP_SEGUNDOS:
            self._taps.clear()
        self._taps.append(ahora)
        if len(self._taps) < 2:
            return "Tap..."
        recientes = self._taps[-(TAPS_PROMEDIADOS + 1):]
        intervalos = [b - a for a, b in zip(recientes, recientes[1:])]
        promedio = sum(intervalos) / len(intervalos)
        if promedio <= 0:
            return "Tap..."
        self.tempo_bpm = round(60.0 / promedio, 1)
        return f"{self.tempo_bpm} BPM"
