"""Estado de performance: traduce acciones en cambios sobre el motor.

Es la capa que une los tres módulos: recibe una `Accion` (venga del MIDI, de la GUI o de la
PWA), la aplica sobre la setlist cargada en RAM y empuja el resultado a Guitarix por RPC.

Mantiene el estado que no vive ni en la setlist ni en el motor: qué banco se está mirando, qué
preset suena, en qué modo está y qué stomps se pisaron desde que se cargó el preset.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from engine.categorias import fijos, nombres_de_archivo, pares_tempo
from engine.midi_engine import Accion
from presets.preset_manager import (
    CADENAS, MAX_ESCENAS, MAX_PRESETS, PRESETS_POR_BANCO, Escena, Preset, Setlist, valor_rpc,
)


def _mismo_valor(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= 1e-4 * max(1.0, abs(float(b)))
    return a == b


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
    # Líneas paralelas (engine/disposicion.GestorLineas). None = un solo motor, como antes: la
    # API lo arma con el MotorLinea real; las pruebas de un solo motor falso lo dejan en None.
    lineas: Any = field(default=None, repr=False)

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
        """`numero` es el pie de la pedalera (0..7 = A..H), no la posición en la lista."""
        stomp = self.preset.stomp_en_pie(numero)
        if stomp is None:
            raise IndexError(f"El preset no tiene stomp en el pie {numero}")
        return self._stomps.get(stomp.unidad, stomp.activo)

    def asignar_stomp(self, unidad: str, pie: int | None, etiqueta: str) -> None:
        """Mantener apretado un bloque del GRID → "Assign to stomp A-H". Arranca con el estado
        on/off que tiene ahora el bloque, así asignar no cambia el sonido."""
        encendido = bool(self.rpc.obtener(f"{unidad}.on_off").get(f"{unidad}.on_off"))
        self.preset.asignar_stomp(unidad, pie, etiqueta, encendido)
        if pie is None:
            self._stomps.pop(unidad, None)
        else:
            self._stomps[unidad] = encendido

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
        if incluir_base and self.lineas is not None:
            # Líneas paralelas guardadas (o deshacerlas si este preset no tiene): antes del `set`,
            # así los parámetros calificados ("a/...", "merge.*") encuentran sus bloques.
            self.lineas.cargar(preset.paralelo)
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
            self.reencender_convolvers(valores)
        if incluir_base and self.tempo_bpm:
            self._aplicar_tempo()

    def reencender_convolvers(self, valores: dict[str, Any], demora: float = 0.4) -> None:
        """Guitarix no deja prender un convolucionador (jconv / jconv_mono) mientras no tiene
        IR, y el IR se carga en segundo plano: un `on_off=1` que llega pegado al IR se pierde y
        el bloque queda en bypass. Verificado en vivo el 26/09/2026. Se vuelve a mandar un rato
        después, en otro hilo, para no demorar el cambio de preset (el cliente RPC tiene lock)."""
        encender = []
        for nombre, valor in valores.items():
            if nombre.endswith(".convolver") and isinstance(valor, dict) and valor.get("jconv.IRFile"):
                unidad = nombre[: -len(".convolver")]
                if valores.get(f"{unidad}.on_off", True) not in (False, 0):
                    encender += [f"{unidad}.on_off", 1]
        if encender:
            hilo = threading.Timer(demora, self._fijar_seguro, args=encender)
            hilo.daemon = True
            hilo.start()

    def _fijar_seguro(self, *pares: Any) -> None:
        try:
            self.rpc.fijar(*pares)
        except Exception:  # noqa: BLE001 -- hilo aparte: un motor caído no debe romper nada
            pass

    # -- Tempo --------------------------------------------------------------------------

    def fijar_tempo(self, bpm: float) -> None:
        """BPM elegido a mano (ventana Tempo): queda como tempo del preset activo -- se guarda
        en disco con el botón 💾, como en la referencia ("cada preset tiene su BPM") -- y lleva
        los delays del rack a ese tempo."""
        if not 24 <= bpm <= 360:
            raise ValueError(f"Tempo fuera de rango (24-360 BPM): {bpm}")
        self.tempo_bpm = round(float(bpm), 1)
        self.preset.tempo_bpm = self.tempo_bpm
        self._aplicar_tempo()

    def _aplicar_tempo(self) -> None:
        if self.lineas is not None:
            # Los delays de todas las líneas siguen el tempo (nombres calificados por tramo).
            pares: list[Any] = []
            for tramo in self.lineas.tramos_activos():
                prefijo = "" if tramo == "pre" else f"{tramo}/"
                locales = pares_tempo(self.lineas.unidades(tramo), self.tempo_bpm)
                for nombre, valor in zip(locales[::2], locales[1::2]):
                    pares += [prefijo + nombre, valor]
        else:
            unidades = [u for est in CADENAS.values() for u in self.rpc.orden_rack(est)]
            pares = pares_tempo(unidades, self.tempo_bpm)
        if pares:
            self.rpc.fijar(*pares)

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
            self._colocar(estereo, objetivo, [u for u in actual if u in fijas])

    def _colocar(self, estereo: int, objetivo: list[str], presentes_fijas: list[str]) -> None:
        """Inserta (o mueve: `insert_rack_unit` sobre una unidad ya presente la mueve,
        `GxSettings::insert_rack_unit`) cada bloque no fijo, en orden, delante del próximo fijo
        que le sigue en `objetivo`. Procesarlos en orden deja cada tramo entre fijos ordenado.
        Después renumera: sin eso el audio no sigue el nuevo orden (ver GuitarixRPC.renumerar).
        Un fijo guardado en el preset pero ausente del rack se descarta: insertarlo tumba al motor.
        """
        fijas = self._unidades_fijas()
        objetivo = [u for u in objetivo if u not in fijas or u in presentes_fijas]
        for i, unidad in enumerate(objetivo):
            if unidad in presentes_fijas:
                continue
            antes_de = next((u for u in objetivo[i + 1:] if u in presentes_fijas), "")
            self.rpc.insertar_unidad(unidad, antes_de, bool(estereo))
        self.rpc.renumerar(estereo)

    def reordenar(self, estereo: int, orden: list[str]) -> None:
        """Arrastrar un bloque en el GRID: deja la fila con exactamente `orden`, en el rack Y en
        el audio. Los bloques fijos (el Amp) no se mueven -- tumba al motor -- pero sí se puede
        pedir un orden donde el Amp quede en otro lugar: se logra moviendo los demás alrededor.
        """
        actual = list(self.rpc.orden_rack(estereo))
        if sorted(orden) != sorted(actual):
            raise ValueError("El orden pedido no coincide con los bloques de la fila")
        fijas = self._unidades_fijas()
        presentes_fijas = [u for u in actual if u in fijas]
        if [u for u in orden if u in fijas] != presentes_fijas:
            raise ValueError("Los bloques fijos del motor no pueden cambiar de orden entre sí")
        if orden != actual:
            self._colocar(estereo, orden, presentes_fijas)

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
            archivos = [n for u in unidades for n in nombres_de_archivo(u)]
            if archivos:
                # IR y capturas NAM/AIDA-X: el preset recuerda qué archivo usa cada bloque.
                parametros.update({n: v for n, v in self.rpc.obtener(*archivos).items()
                                   if v not in (None, "", {})})
        if self.lineas is not None:
            parametros.update(self.lineas.capturar_extra())   # líneas A/B/post y SPLIT/MERGE
        return cadena, parametros

    def guardar_en_preset(self) -> Preset:
        """Guarda el estado real del motor en el preset activo (cadena + parámetros). Los
        stomps pisados pasan a ser el estado guardado: lo que suena es lo que queda."""
        preset = self.preset
        cadena, parametros = self.capturar()
        escena = self._escena_actual()
        if escena is not None:
            # Guardando DENTRO de una escena: lo que es propio de la escena queda en la escena
            # y la base del preset conserva su valor -- si no, 💾 en la escena B pisaba el
            # preset con los valores de B y las demás escenas los heredaban.
            for nombre in escena.parametros:
                if nombre in parametros:
                    escena.parametros[nombre] = parametros[nombre]
                if nombre in preset.parametros:
                    parametros[nombre] = preset.parametros[nombre]
        preset.cadena = cadena
        preset.parametros = parametros
        if self.lineas is not None:
            preset.paralelo = self.lineas.exportar()
        for stomp in preset.stomps:
            stomp.activo = bool(parametros.get(stomp.parametro, stomp.activo))
        self._stomps = {s.unidad: s.activo for s in preset.stomps}
        return preset

    # -- Escenas como Cortex -------------------------------------------------------------
    #
    # Estando en una escena, mover una perilla (o prender/apagar un bloque) la vuelve propia de
    # ESA escena: se guarda en `escena.parametros` y las demás escenas no cambian. En la app la
    # perilla se marca con el color de la escena y se puede "volver al valor del preset".

    def _escena_actual(self) -> Escena | None:
        return self.preset.escena(self.escena_activa) if self.escena_activa else None

    def fijar_parametros(self, pares: dict[str, Any]) -> None:
        planos: list[Any] = []
        for nombre, valor in pares.items():
            planos += [nombre, valor]
        if planos:
            self.rpc.fijar(*planos)
        escena = self._escena_actual()
        if escena is not None:
            escena.parametros.update(pares)

    def propios_de_escena(self) -> set[str]:
        """Parámetros cuyo valor en la escena activa difiere del preset: los que la app marca."""
        escena = self._escena_actual()
        if escena is None:
            return set()
        base = self.preset.parametros
        return {n for n, v in escena.parametros.items() if n not in base or not _mismo_valor(v, base[n])}

    def restaurar_de_preset(self, nombre: str) -> Any:
        """"Volver al valor del preset": la perilla deja de ser propia de la escena."""
        escena = self._escena_actual()
        if escena is None:
            raise ValueError("No hay una escena activa")
        if nombre not in self.preset.parametros:
            raise ValueError("El preset no tiene guardado ese parámetro: guardalo con 💾 primero")
        valor = self.preset.parametros[nombre]
        escena.parametros.pop(nombre, None)
        self.rpc.fijar(nombre, valor_rpc(valor))
        return valor

    # -- Nombres y presets nuevos (solo desde la pantalla del OS, ver server/api.py) ------------

    def renombrar_escena(self, indice: int, nombre: str) -> None:
        """Las escenas se buscan por nombre (escena_activa, escenas de la pedalera): no puede
        haber dos iguales en el mismo preset, y si se renombra la activa, sigue activa."""
        escenas = self.preset.escenas
        if not 0 <= indice < len(escenas):
            raise ValueError(f"El preset no tiene la escena {indice + 1}")
        if any(e.nombre == nombre for i, e in enumerate(escenas) if i != indice):
            raise ValueError(f"Ya hay una escena llamada {nombre!r} en este preset")
        viejo = escenas[indice].nombre
        escenas[indice].nombre = nombre
        if self.escena_activa == viejo:
            self.escena_activa = nombre

    def nuevo_preset(self, banco: int, nombre: str) -> Preset:
        """"Save current sound here": un preset nuevo con lo que suena ahora (cadena, valores,
        líneas paralelas y tempo) en el próximo lugar libre del banco, y queda activo."""
        if not 0 <= banco < len(self.setlist.bancos):
            raise ValueError(f"No existe el banco {banco + 1}")
        presets = self.setlist.bancos[banco].presets
        if len(presets) >= PRESETS_POR_BANCO:
            raise ValueError(f"El banco {banco + 1} está lleno ({PRESETS_POR_BANCO} presets)")
        cadena, parametros = self.capturar()
        nuevo = Preset(nombre=nombre, cadena=cadena, parametros=parametros, tempo_bpm=self.tempo_bpm,
                       paralelo=self.lineas.exportar() if self.lineas is not None else None)
        presets.append(nuevo)
        # Queda activo sin volver a aplicarlo: lo que suena ES ese preset.
        self.banco_activo = self.banco_visible = banco
        self.posicion_activa = len(presets) - 1
        self.escena_activa = None
        self._stomps = {}
        return nuevo

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
        stomp = self.preset.stomp_en_pie(numero)
        if stomp is None:
            return f"Sin stomp {numero + 1}"
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
        bpm = round(60.0 / promedio, 1)
        if not 24 <= bpm <= 360:
            return "Tap..."
        self.fijar_tempo(bpm)
        return f"{self.tempo_bpm} BPM"
