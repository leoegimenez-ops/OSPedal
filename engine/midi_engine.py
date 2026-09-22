"""Parseo de MIDI y mapeo a acciones del sistema.

Este módulo es deliberadamente **puro**: no toca ALSA, ni sockets, ni archivos. Recibe bytes y
devuelve acciones. La lectura del puerto MIDI real se implementa aparte (backend ALSA), y así
toda la lógica difícil —que es ésta— se puede probar sin hardware.

Soporta cualquier controlador MIDI class-compliant: no hay nada específico de un modelo de
pedalera. El usuario asocia sus propios controles con `MapaMidi.aprender()` (MIDI learn) o
editando el JSON del mapa. Ver `docs/midi.md`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

VERSION_FORMATO = 1

# Mensajes de tiempo real: pueden aparecer en cualquier momento, incluso partiendo al medio
# otro mensaje, y no alteran el running status.
REALTIME_MIN = 0xF8
CLOCK = 0xF8
START = 0xFA
CONTINUE = 0xFB
STOP = 0xFC

SYSEX_INICIO = 0xF0
SYSEX_FIN = 0xF7


class TipoMensaje(str, Enum):
    NOTE_OFF = "note_off"
    NOTE_ON = "note_on"
    AFTERTOUCH = "aftertouch"
    CONTROL_CHANGE = "control_change"
    PROGRAM_CHANGE = "program_change"
    PRESION_CANAL = "presion_canal"
    PITCH_BEND = "pitch_bend"
    REALTIME = "realtime"


# Cantidad de bytes de datos por tipo de mensaje de canal. Program Change y Presión de Canal
# llevan uno solo; confundirlo desincroniza el parser y es el error clásico de estos parsers.
_BYTES_DATOS = {
    0x80: 2,  # note off
    0x90: 2,  # note on
    0xA0: 2,  # aftertouch
    0xB0: 2,  # control change
    0xC0: 1,  # program change
    0xD0: 1,  # presión de canal
    0xE0: 2,  # pitch bend
}

_TIPO_POR_ESTADO = {
    0x80: TipoMensaje.NOTE_OFF,
    0x90: TipoMensaje.NOTE_ON,
    0xA0: TipoMensaje.AFTERTOUCH,
    0xB0: TipoMensaje.CONTROL_CHANGE,
    0xC0: TipoMensaje.PROGRAM_CHANGE,
    0xD0: TipoMensaje.PRESION_CANAL,
    0xE0: TipoMensaje.PITCH_BEND,
}


@dataclass(frozen=True)
class MensajeMidi:
    """Un mensaje MIDI ya parseado.

    `canal` va de 1 a 16, como lo numeran los músicos y las pedaleras, no de 0 a 15 como viaja
    por el cable. La conversión se hace acá, una sola vez.
    """

    tipo: TipoMensaje
    canal: int = 0          # 0 para mensajes sin canal (tiempo real)
    numero: int = 0         # nota, número de CC, o número de programa
    valor: int = 0          # velocity, valor del CC

    @property
    def es_pulsacion(self) -> bool:
        """Si el mensaje representa apretar un pedal, en oposición a soltarlo.

        Un Note On con velocity 0 es, por convención del estándar, un Note Off. Las pedaleras lo
        usan todo el tiempo.
        """
        if self.tipo is TipoMensaje.NOTE_ON:
            return self.valor > 0
        if self.tipo is TipoMensaje.NOTE_OFF:
            return False
        return True


class ParserMidi:
    """Parser incremental de un flujo de bytes MIDI.

    Maneja las tres cosas que rompen los parsers ingenuos:

    - **Running status**: un mensaje puede omitir el byte de estado y reusar el anterior. Las
      pedaleras lo usan para ahorrar ancho de banda.
    - **Mensajes de tiempo real intercalados**: un MIDI Clock puede caer justo en el medio de un
      Control Change sin invalidarlo.
    - **Mensajes partidos entre lecturas**: el flujo llega por bloques arbitrarios, así que un
      mensaje puede quedar a mitad entre dos llamadas.
    """

    def __init__(self) -> None:
        self._estado = 0          # running status
        self._datos: list[int] = []
        self._en_sysex = False

    def alimentar(self, datos: Iterable[int]) -> list[MensajeMidi]:
        """Procesa bytes y devuelve los mensajes completos que se hayan formado."""
        mensajes: list[MensajeMidi] = []

        for byte in datos:
            byte &= 0xFF

            # Tiempo real: se resuelve al instante y no toca ningún estado.
            if byte >= REALTIME_MIN:
                mensajes.append(MensajeMidi(TipoMensaje.REALTIME, numero=byte))
                continue

            if self._en_sysex:
                if byte == SYSEX_FIN:
                    self._en_sysex = False
                continue

            if byte & 0x80:                      # byte de estado
                if byte == SYSEX_INICIO:
                    self._en_sysex = True
                    self._estado = 0             # SysEx cancela el running status
                    self._datos.clear()
                    continue
                if byte > SYSEX_INICIO:          # system common: también lo cancela
                    self._estado = 0
                    self._datos.clear()
                    continue
                self._estado = byte
                self._datos.clear()
                continue

            # byte de datos
            if not self._estado:
                continue                         # datos sin estado previo: se descartan

            self._datos.append(byte)
            esperados = _BYTES_DATOS[self._estado & 0xF0]
            if len(self._datos) == esperados:
                mensaje = self._construir()
                if mensaje is not None:
                    mensajes.append(mensaje)
                self._datos.clear()              # el running status se mantiene

        return mensajes

    def _construir(self) -> MensajeMidi | None:
        alto = self._estado & 0xF0
        canal = (self._estado & 0x0F) + 1
        tipo = _TIPO_POR_ESTADO[alto]

        if alto in (0xC0, 0xD0):
            return MensajeMidi(tipo, canal, numero=self._datos[0])
        if alto == 0xE0:
            # El pitch bend es un valor de 14 bits partido en dos bytes.
            valor = (self._datos[1] << 7) | self._datos[0]
            return MensajeMidi(tipo, canal, valor=valor)

        numero, valor = self._datos[0], self._datos[1]
        if alto == 0x90 and valor == 0:
            return MensajeMidi(TipoMensaje.NOTE_OFF, canal, numero, 0)
        return MensajeMidi(tipo, canal, numero, valor)


class Accion(str, Enum):
    """Lo que puede hacer el sistema en respuesta a un mensaje MIDI."""

    CAMBIAR_PRESET = "cambiar_preset"        # parámetro: índice absoluto 0..255
    PRESET_EN_BANCO = "preset_en_banco"      # parámetro: posición 0..7 en el banco actual
    PRESET_SIGUIENTE = "preset_siguiente"
    PRESET_ANTERIOR = "preset_anterior"
    BANCO_SIGUIENTE = "banco_siguiente"
    BANCO_ANTERIOR = "banco_anterior"
    TOGGLE_STOMP = "toggle_stomp"            # parámetro: número de stomp 0..7
    ESCENA = "escena"                        # parámetro: índice de escena
    MODO = "modo"                            # parámetro: 0=preset 1=stomp 2=scene
    AFINADOR = "afinador"
    TAP_TEMPO = "tap_tempo"


@dataclass(frozen=True)
class Disparador:
    """Lo que tiene que llegar por MIDI para activar una acción."""

    tipo: TipoMensaje
    numero: int
    canal: int = 0            # 0 = cualquier canal (omni)

    def coincide(self, mensaje: MensajeMidi) -> bool:
        if self.canal and mensaje.canal != self.canal:
            return False
        if self.tipo is not mensaje.tipo:
            return False
        return self.numero == mensaje.numero


@dataclass
class Asignacion:
    disparador: Disparador
    accion: Accion
    parametro: int | None = None
    # Un footswitch momentáneo manda 127 al apretar y 0 al soltar. Sin este umbral, cada
    # pisada dispararía la acción dos veces.
    valor_minimo: int = 1

    def coincide(self, mensaje: MensajeMidi) -> bool:
        if not self.disparador.coincide(mensaje):
            return False
        if not mensaje.es_pulsacion:
            return False
        if mensaje.tipo is TipoMensaje.CONTROL_CHANGE and mensaje.valor < self.valor_minimo:
            return False
        return True

    def a_dict(self) -> dict[str, Any]:
        salida: dict[str, Any] = {
            "tipo": self.disparador.tipo.value,
            "numero": self.disparador.numero,
            "accion": self.accion.value,
        }
        if self.disparador.canal:
            salida["canal"] = self.disparador.canal
        if self.parametro is not None:
            salida["parametro"] = self.parametro
        if self.valor_minimo != 1:
            salida["valor_minimo"] = self.valor_minimo
        return salida

    @classmethod
    def desde_dict(cls, datos: dict[str, Any], ruta: str) -> Asignacion:
        if not isinstance(datos, dict):
            raise ErrorDeMapa(f"{ruta}: debe ser un objeto")
        try:
            tipo = TipoMensaje(datos["tipo"])
        except KeyError:
            raise ErrorDeMapa(f"{ruta}.tipo: falta") from None
        except ValueError:
            raise ErrorDeMapa(
                f"{ruta}.tipo: desconocido {datos['tipo']!r}. "
                f"Válidos: {', '.join(t.value for t in TipoMensaje)}"
            ) from None
        try:
            accion = Accion(datos["accion"])
        except KeyError:
            raise ErrorDeMapa(f"{ruta}.accion: falta") from None
        except ValueError:
            raise ErrorDeMapa(
                f"{ruta}.accion: desconocida {datos['accion']!r}. "
                f"Válidas: {', '.join(a.value for a in Accion)}"
            ) from None

        canal = datos.get("canal", 0)
        if not isinstance(canal, int) or not 0 <= canal <= 16:
            raise ErrorDeMapa(f"{ruta}.canal: debe estar entre 1 y 16, o 0 para omni")

        numero = datos.get("numero")
        if not isinstance(numero, int) or not 0 <= numero <= 127:
            raise ErrorDeMapa(f"{ruta}.numero: debe estar entre 0 y 127")

        return cls(
            disparador=Disparador(tipo, numero, canal),
            accion=accion,
            parametro=datos.get("parametro"),
            valor_minimo=datos.get("valor_minimo", 1),
        )


class ErrorDeMapa(ValueError):
    """El mapa MIDI no es válido."""


@dataclass
class MapaMidi:
    """Asociación entre mensajes MIDI y acciones, configurable por el usuario."""

    nombre: str = "Mapa sin nombre"
    canal: int = 0
    # Muchas pedaleras mandan Program Change para elegir preset. Con esto activado, cualquier
    # PC selecciona el preset de ese índice sin necesidad de declarar 128 asignaciones.
    programa_directo: bool = True
    asignaciones: list[Asignacion] = field(default_factory=list)
    version: int = VERSION_FORMATO

    def resolver(self, mensaje: MensajeMidi) -> tuple[Accion, int | None] | None:
        """Traduce un mensaje MIDI a una acción, o None si no está mapeado."""
        if self.canal and mensaje.canal and mensaje.canal != self.canal:
            return None
        for asignacion in self.asignaciones:
            if asignacion.coincide(mensaje):
                return asignacion.accion, asignacion.parametro
        if self.programa_directo and mensaje.tipo is TipoMensaje.PROGRAM_CHANGE:
            return Accion.CAMBIAR_PRESET, mensaje.numero
        return None

    def aprender(
        self,
        mensaje: MensajeMidi,
        accion: Accion,
        parametro: int | None = None,
        omni: bool = False,
    ) -> Asignacion:
        """MIDI learn: asocia el control que acaba de llegar con una acción.

        Es lo que permite soportar cualquier pedalera sin conocer su modelo: el usuario elige la
        acción, pisa el pedal, y queda asociado. Si ya había una asignación para ese mismo
        control, se reemplaza.
        """
        if mensaje.tipo is TipoMensaje.REALTIME:
            raise ErrorDeMapa("Un mensaje de tiempo real no sirve como disparador")
        tipo = TipoMensaje.NOTE_ON if mensaje.tipo is TipoMensaje.NOTE_OFF else mensaje.tipo
        disparador = Disparador(tipo, mensaje.numero, 0 if omni else mensaje.canal)
        self.asignaciones = [a for a in self.asignaciones if a.disparador != disparador]
        asignacion = Asignacion(disparador, accion, parametro)
        self.asignaciones.append(asignacion)
        return asignacion

    def olvidar(self, disparador: Disparador) -> bool:
        antes = len(self.asignaciones)
        self.asignaciones = [a for a in self.asignaciones if a.disparador != disparador]
        return len(self.asignaciones) < antes

    # -- Persistencia -----------------------------------------------------------------

    def a_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "nombre": self.nombre,
            "canal": self.canal,
            "programa_directo": self.programa_directo,
            "asignaciones": [a.a_dict() for a in self.asignaciones],
        }

    @classmethod
    def desde_dict(cls, datos: dict[str, Any]) -> MapaMidi:
        if not isinstance(datos, dict):
            raise ErrorDeMapa("mapa: debe ser un objeto")
        version = datos.get("version")
        if version != VERSION_FORMATO:
            raise ErrorDeMapa(f"mapa.version: se esperaba {VERSION_FORMATO}, llegó {version!r}")
        canal = datos.get("canal", 0)
        if not isinstance(canal, int) or not 0 <= canal <= 16:
            raise ErrorDeMapa("mapa.canal: debe estar entre 1 y 16, o 0 para omni")
        crudo = datos.get("asignaciones", [])
        if not isinstance(crudo, list):
            raise ErrorDeMapa("mapa.asignaciones: debe ser una lista")
        return cls(
            nombre=datos.get("nombre", "Mapa sin nombre"),
            canal=canal,
            programa_directo=datos.get("programa_directo", True),
            asignaciones=[Asignacion.desde_dict(a, f"mapa.asignaciones[{i}]")
                          for i, a in enumerate(crudo)],
            version=version,
        )

    @classmethod
    def cargar(cls, ruta: str | Path) -> MapaMidi:
        ruta = Path(ruta)
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ErrorDeMapa(f"{ruta}: JSON inválido: {exc}") from exc
        return cls.desde_dict(datos)

    def guardar(self, ruta: str | Path) -> None:
        """Guardado atómico, por el mismo motivo que las setlists: un corte de luz a mitad de
        escritura no debe dejar al usuario sin su configuración de pedalera."""
        ruta = Path(ruta)
        temporal = ruta.with_suffix(ruta.suffix + ".tmp")
        temporal.write_text(
            json.dumps(self.a_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        temporal.replace(ruta)
