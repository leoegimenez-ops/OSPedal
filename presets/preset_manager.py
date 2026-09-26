"""Modelo de datos y gestión de setlists.

Jerarquía: Setlist › Banco (32) › Preset (8) = 256 presets por setlist.

La setlist es la fuente de verdad de la *estructura de la performance* (qué presets hay, en qué
orden, qué pedal hace qué, tempo por tema). Guitarix es la fuente de verdad del *estado de DSP*.
Un preset de acá lleva un snapshot de parámetros que se empuja al motor; opcionalmente parte de
un preset de Guitarix como base. Ver `docs/presets.md`.

La setlist entera se carga en RAM al arrancar: son pocos KB y así el cambio de preset no toca
disco, que es lo que permite cambiar sin gap de audio.

El esquema formal está en `presets/schema.json`. La validación de acá es equivalente pero no
depende de librerías externas, para que el sistema en escenario no falle por una dependencia
faltante y para poder dar errores con la ruta exacta del campo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VERSION_FORMATO = 1
MAX_BANCOS = 32
PRESETS_POR_BANCO = 8
MAX_PRESETS = MAX_BANCOS * PRESETS_POR_BANCO  # 256
MAX_ESCENAS = 8  # A-H, una por switch de la pedalera -- mismo tope que schema.json
PIES_STOMP = 8   # A-H: pies de la pedalera asignables a un stomp
TRAMOS_LINEA = ("pre", "a", "b", "post")   # tramos de un instrumento con líneas paralelas

# Valores aceptados como parámetro por el motor (jsonrpc.cpp:1008-1031).
TIPOS_VALOR = (int, float, bool, str)

# Las dos cadenas del rack de Guitarix, con el flag "estéreo" que espera insert/remove_rack_unit
# y get_rack_unit_order (0 = mono, 1 = estéreo).
CADENAS = {"mono": 0, "estereo": 1}


class ErrorDeSetlist(ValueError):
    """La setlist no cumple el esquema. El mensaje incluye la ruta del campo."""


def _exigir(condicion: bool, ruta: str, mensaje: str) -> None:
    if not condicion:
        raise ErrorDeSetlist(f"{ruta}: {mensaje}")


def _texto(datos: dict[str, Any], clave: str, ruta: str, obligatorio: bool = True) -> str:
    valor = datos.get(clave)
    if valor is None and not obligatorio:
        return ""
    _exigir(isinstance(valor, str) and valor != "", f"{ruta}.{clave}",
            "debe ser un texto no vacío")
    return valor  # type: ignore[return-value]


def _parametros(datos: dict[str, Any], ruta: str) -> dict[str, Any]:
    crudo = datos.get("parametros", {})
    _exigir(isinstance(crudo, dict), f"{ruta}.parametros", "debe ser un objeto")
    for nombre, valor in crudo.items():
        _exigir(isinstance(valor, TIPOS_VALOR), f"{ruta}.parametros.{nombre}",
                f"tipo no soportado: {type(valor).__name__}")
    return dict(crudo)


def valor_rpc(valor: Any) -> Any:
    """Adapta un valor al formato que espera el motor.

    Los parámetros booleanos de Guitarix se leen con getInt() (jsonrpc.cpp:1027), así que hay
    que mandarlos como 1/0 y no como true/false.
    """
    return int(valor) if isinstance(valor, bool) else valor


@dataclass
class Stomp:
    """Un pedal en modo Stomp: prende y apaga una unidad del rack."""

    etiqueta: str
    unidad: str
    activo: bool = False
    # Pie de la pedalera (0..7 = A..H) donde está asignado. None en setlists viejas: ahí manda
    # el orden de la lista (el primero es A), ver `Preset.stomps_por_pie`.
    pie: int | None = None

    @property
    def parametro(self) -> str:
        """Id del parámetro on/off en Guitarix (gx_pluginloader.cpp:333)."""
        return f"{self.unidad}.on_off"

    @classmethod
    def desde_dict(cls, datos: dict[str, Any], ruta: str) -> Stomp:
        _exigir(isinstance(datos, dict), ruta, "debe ser un objeto")
        activo = datos.get("activo", False)
        _exigir(isinstance(activo, bool), f"{ruta}.activo", "debe ser booleano")
        pie = datos.get("pie")
        _exigir(pie is None or (isinstance(pie, int) and not isinstance(pie, bool)
                                and 0 <= pie < PIES_STOMP),
                f"{ruta}.pie", f"debe ser un entero de 0 a {PIES_STOMP - 1} (A-H)")
        return cls(
            etiqueta=_texto(datos, "etiqueta", ruta),
            unidad=_texto(datos, "unidad", ruta),
            activo=activo,
            pie=pie,
        )

    def a_dict(self) -> dict[str, Any]:
        salida: dict[str, Any] = {"etiqueta": self.etiqueta, "unidad": self.unidad, "activo": self.activo}
        if self.pie is not None:
            salida["pie"] = self.pie
        return salida


@dataclass
class Escena:
    """Variación dentro de un preset (modo Scene). Pisa parámetros del preset."""

    nombre: str
    parametros: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def desde_dict(cls, datos: dict[str, Any], ruta: str) -> Escena:
        _exigir(isinstance(datos, dict), ruta, "debe ser un objeto")
        return cls(nombre=_texto(datos, "nombre", ruta), parametros=_parametros(datos, ruta))

    def a_dict(self) -> dict[str, Any]:
        salida: dict[str, Any] = {"nombre": self.nombre}
        if self.parametros:
            salida["parametros"] = dict(self.parametros)
        return salida


@dataclass
class Preset:
    nombre: str
    guitarix_banco: str | None = None
    guitarix_preset: str | None = None
    parametros: dict[str, Any] = field(default_factory=dict)
    tempo_bpm: float | None = None
    volumen: float | None = None
    stomps: list[Stomp] = field(default_factory=list)
    escenas: list[Escena] = field(default_factory=list)
    notas: str = ""
    # Orden de bloques del rack por cadena ("mono"/"estereo"), tal como lo guarda el botón de
    # guardar del GRID. Opcional: un preset sin cadena no toca el rack al cargarse (comportamiento
    # anterior, compatible con setlists viejas).
    cadena: dict[str, list[str]] | None = None
    # Líneas paralelas (como Cortex): {"split": bool, "amp": {tramo: visible}, "tramos": {"a": [...],
    # "b": [...], "post": [...]}}. None = una sola línea con el Amp visible (lo de siempre). Los
    # valores de esos bloques van en `parametros` con nombres calificados ("a/ts9sim.drive",
    # "merge.nivel_b"). Ver engine/disposicion.py.
    paralelo: dict[str, Any] | None = None

    @classmethod
    def desde_dict(cls, datos: dict[str, Any], ruta: str) -> Preset:
        _exigir(isinstance(datos, dict), ruta, "debe ser un objeto")

        paralelo = datos.get("paralelo")
        if paralelo is not None:
            r = f"{ruta}.paralelo"
            _exigir(isinstance(paralelo, dict), r, "debe ser un objeto")
            _exigir(isinstance(paralelo.get("split", False), bool), f"{r}.split", "debe ser booleano")
            amp = paralelo.get("amp", {})
            _exigir(isinstance(amp, dict) and all(k in TRAMOS_LINEA and isinstance(v, bool) for k, v in amp.items()),
                    f"{r}.amp", f"tramo -> booleano; tramos: {', '.join(TRAMOS_LINEA)}")
            tramos = paralelo.get("tramos", {})
            _exigir(isinstance(tramos, dict), f"{r}.tramos", "debe ser un objeto")
            for t, unidades in tramos.items():
                _exigir(t in ("a", "b", "post"), f"{r}.tramos.{t}", "tramo desconocido (a, b, post)")
                _exigir(isinstance(unidades, list) and all(isinstance(u, str) and u for u in unidades),
                        f"{r}.tramos.{t}", "debe ser una lista de ids de unidad")
                _exigir(len(unidades) == len(set(unidades)), f"{r}.tramos.{t}",
                        "el mismo modelo va una vez por tramo")

        cadena = None
        if "cadena" in datos:
            crudo_cadena = datos["cadena"]
            _exigir(isinstance(crudo_cadena, dict), f"{ruta}.cadena", "debe ser un objeto")
            cadena = {}
            for clave, unidades in crudo_cadena.items():
                _exigir(clave in CADENAS, f"{ruta}.cadena.{clave}",
                        f"cadena desconocida, válidas: {', '.join(CADENAS)}")
                _exigir(isinstance(unidades, list)
                        and all(isinstance(u, str) and u for u in unidades),
                        f"{ruta}.cadena.{clave}", "debe ser una lista de ids de unidad")
                cadena[clave] = list(unidades)

        banco = preset = None
        if "guitarix" in datos:
            gx = datos["guitarix"]
            _exigir(isinstance(gx, dict), f"{ruta}.guitarix", "debe ser un objeto")
            banco = _texto(gx, "banco", f"{ruta}.guitarix")
            preset = _texto(gx, "preset", f"{ruta}.guitarix")

        tempo = datos.get("tempo_bpm")
        if tempo is not None:
            _exigir(isinstance(tempo, (int, float)) and not isinstance(tempo, bool),
                    f"{ruta}.tempo_bpm", "debe ser un número")
            # 360: el tope real de los delays sincronizables (ControladorEscenario.fijar_tempo).
            _exigir(20 <= tempo <= 360, f"{ruta}.tempo_bpm", "debe estar entre 20 y 360")

        volumen = datos.get("volumen")
        if volumen is not None:
            _exigir(isinstance(volumen, (int, float)) and not isinstance(volumen, bool),
                    f"{ruta}.volumen", "debe ser un número")
            _exigir(0 <= volumen <= 1, f"{ruta}.volumen", "debe estar entre 0 y 1")

        stomps_crudo = datos.get("stomps", [])
        _exigir(isinstance(stomps_crudo, list), f"{ruta}.stomps", "debe ser una lista")
        _exigir(len(stomps_crudo) <= PRESETS_POR_BANCO, f"{ruta}.stomps",
                f"máximo {PRESETS_POR_BANCO} stomps")

        escenas_crudo = datos.get("escenas", [])
        _exigir(isinstance(escenas_crudo, list), f"{ruta}.escenas", "debe ser una lista")
        _exigir(len(escenas_crudo) <= MAX_ESCENAS, f"{ruta}.escenas",
                f"máximo {MAX_ESCENAS} escenas (A-H)")

        stomps = [Stomp.desde_dict(s, f"{ruta}.stomps[{i}]") for i, s in enumerate(stomps_crudo)]
        pies = [pie for pie, _ in Preset._pies(stomps)]
        _exigir(len(pies) == len(set(pies)), f"{ruta}.stomps",
                "dos stomps en el mismo pie de la pedalera")

        return cls(
            nombre=_texto(datos, "nombre", ruta),
            guitarix_banco=banco,
            guitarix_preset=preset,
            parametros=_parametros(datos, ruta),
            tempo_bpm=tempo,
            volumen=volumen,
            stomps=stomps,
            escenas=[Escena.desde_dict(e, f"{ruta}.escenas[{i}]")
                     for i, e in enumerate(escenas_crudo)],
            notas=_texto(datos, "notas", ruta, obligatorio=False),
            cadena=cadena,
            paralelo=paralelo,
        )

    def a_dict(self) -> dict[str, Any]:
        salida: dict[str, Any] = {"nombre": self.nombre}
        if self.guitarix_banco and self.guitarix_preset:
            salida["guitarix"] = {"banco": self.guitarix_banco, "preset": self.guitarix_preset}
        if self.parametros:
            salida["parametros"] = dict(self.parametros)
        if self.tempo_bpm is not None:
            salida["tempo_bpm"] = self.tempo_bpm
        if self.volumen is not None:
            salida["volumen"] = self.volumen
        if self.stomps:
            salida["stomps"] = [s.a_dict() for s in self.stomps]
        if self.escenas:
            salida["escenas"] = [e.a_dict() for e in self.escenas]
        if self.notas:
            salida["notas"] = self.notas
        if self.cadena is not None:
            salida["cadena"] = {k: list(v) for k, v in self.cadena.items()}
        if self.paralelo is not None:
            salida["paralelo"] = {
                "split": bool(self.paralelo.get("split", False)),
                "amp": dict(self.paralelo.get("amp", {})),
                "tramos": {t: list(u) for t, u in self.paralelo.get("tramos", {}).items()},
            }
        return salida

    @staticmethod
    def _pies(stomps: list[Stomp]) -> list[tuple[int, Stomp]]:
        """(pie, stomp) de cada stomp: el `pie` explícito, o su posición en la lista si no
        tiene (setlists anteriores a la asignación desde el GRID)."""
        return [(s.pie if s.pie is not None else i, s) for i, s in enumerate(stomps)]

    def stomp_en_pie(self, pie: int) -> Stomp | None:
        for p, s in self._pies(self.stomps):
            if p == pie:
                return s
        return None

    def pies_de_stomps(self) -> dict[str, int]:
        """unidad -> pie, para dibujar la letra en el bloque del GRID."""
        return {s.unidad: p for p, s in self._pies(self.stomps)}

    def asignar_stomp(self, unidad: str, pie: int | None, etiqueta: str, activo: bool) -> None:
        """Pone `unidad` en el pie dado (A-H), sacándola de donde estuviera y desplazando a
        quien ocupara ese pie. `pie=None` la quita de la pedalera."""
        if pie is not None and not 0 <= pie < PIES_STOMP:
            raise ValueError(f"pie fuera de rango: {pie} (0-{PIES_STOMP - 1})")
        # Fijar el pie efectivo de todos antes de tocar la lista: si no, al sacar uno los
        # stomps sin `pie` explícito cambiarían de letra.
        for p, s in self._pies(self.stomps):
            s.pie = p
        self.stomps = [s for s in self.stomps if s.unidad != unidad and s.pie != pie]
        if pie is not None:
            self.stomps.append(Stomp(etiqueta=etiqueta, unidad=unidad, activo=activo, pie=pie))
            self.stomps.sort(key=lambda s: s.pie)

    def escena(self, nombre: str) -> Escena | None:
        for e in self.escenas:
            if e.nombre == nombre:
                return e
        return None

    def pares_rpc(self, escena: str | None = None) -> list[Any]:
        """Arma la lista plana nombre/valor para una sola llamada `set`.

        Los stomps son parámetros comunes (`<unidad>.on_off`), así que viajan en la misma
        llamada que el resto: un único mensaje sin round-trip para todo el cambio de preset.

        El orden de precedencia es parámetros del preset, después estados de stomp, después la
        escena, que es la que manda por ser la variación más específica.
        """
        valores: dict[str, Any] = dict(self.parametros)
        for stomp in self.stomps:
            valores[stomp.parametro] = stomp.activo
        if escena is not None:
            elegida = self.escena(escena)
            if elegida is None:
                disponibles = ", ".join(e.nombre for e in self.escenas) or "ninguna"
                raise KeyError(
                    f"El preset {self.nombre!r} no tiene la escena {escena!r}. "
                    f"Disponibles: {disponibles}"
                )
            valores.update(elegida.parametros)

        pares: list[Any] = []
        for nombre, valor in valores.items():
            pares.append(nombre)
            pares.append(valor_rpc(valor))
        return pares


@dataclass
class Banco:
    nombre: str
    presets: list[Preset] = field(default_factory=list)

    @classmethod
    def desde_dict(cls, datos: dict[str, Any], ruta: str) -> Banco:
        _exigir(isinstance(datos, dict), ruta, "debe ser un objeto")
        crudo = datos.get("presets", [])
        _exigir(isinstance(crudo, list), f"{ruta}.presets", "debe ser una lista")
        _exigir(len(crudo) <= PRESETS_POR_BANCO, f"{ruta}.presets",
                f"máximo {PRESETS_POR_BANCO} presets por banco, hay {len(crudo)}")
        return cls(
            nombre=_texto(datos, "nombre", ruta),
            presets=[Preset.desde_dict(p, f"{ruta}.presets[{i}]") for i, p in enumerate(crudo)],
        )

    def a_dict(self) -> dict[str, Any]:
        return {"nombre": self.nombre, "presets": [p.a_dict() for p in self.presets]}


@dataclass
class Setlist:
    nombre: str
    bancos: list[Banco] = field(default_factory=list)
    descripcion: str = ""
    version: int = VERSION_FORMATO

    # -- Carga y guardado -------------------------------------------------------------

    @classmethod
    def desde_dict(cls, datos: dict[str, Any]) -> Setlist:
        _exigir(isinstance(datos, dict), "setlist", "debe ser un objeto")

        version = datos.get("version")
        _exigir(version == VERSION_FORMATO, "setlist.version",
                f"se esperaba {VERSION_FORMATO}, llegó {version!r}")

        crudo = datos.get("bancos", [])
        _exigir(isinstance(crudo, list), "setlist.bancos", "debe ser una lista")
        _exigir(len(crudo) <= MAX_BANCOS, "setlist.bancos",
                f"máximo {MAX_BANCOS} bancos, hay {len(crudo)}")

        return cls(
            nombre=_texto(datos, "nombre", "setlist"),
            descripcion=_texto(datos, "descripcion", "setlist", obligatorio=False),
            bancos=[Banco.desde_dict(b, f"setlist.bancos[{i}]") for i, b in enumerate(crudo)],
            version=version,
        )

    @classmethod
    def cargar(cls, ruta: str | Path) -> Setlist:
        ruta = Path(ruta)
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ErrorDeSetlist(f"{ruta}: JSON inválido: {exc}") from exc
        return cls.desde_dict(datos)

    def a_dict(self) -> dict[str, Any]:
        salida: dict[str, Any] = {"version": self.version, "nombre": self.nombre}
        if self.descripcion:
            salida["descripcion"] = self.descripcion
        salida["bancos"] = [b.a_dict() for b in self.bancos]
        return salida

    def guardar(self, ruta: str | Path) -> None:
        """Guarda la setlist de forma atómica.

        Escribe en un temporal y después reemplaza, para que un corte de luz a mitad de
        guardado no deje la setlist truncada. En un equipo de escenario que arranca desde un
        pendrive, perder la setlist es perder el show.
        """
        ruta = Path(ruta)
        temporal = ruta.with_suffix(ruta.suffix + ".tmp")
        contenido = json.dumps(self.a_dict(), indent=2, ensure_ascii=False) + "\n"
        temporal.write_text(contenido, encoding="utf-8")
        temporal.replace(ruta)

    # -- Navegación -------------------------------------------------------------------

    @property
    def total_presets(self) -> int:
        return sum(len(b.presets) for b in self.bancos)

    def preset(self, banco: int, posicion: int) -> Preset:
        _exigir(0 <= banco < len(self.bancos), "banco",
                f"fuera de rango: {banco} (hay {len(self.bancos)} bancos)")
        presets = self.bancos[banco].presets
        _exigir(0 <= posicion < len(presets), "preset",
                f"fuera de rango: {posicion} (el banco tiene {len(presets)})")
        return presets[posicion]

    def preset_por_indice(self, indice: int) -> Preset:
        """Acceso por índice plano 0..255, que es como los numera una pedalera MIDI."""
        _exigir(0 <= indice < MAX_PRESETS, "indice",
                f"fuera de rango: {indice} (válido 0..{MAX_PRESETS - 1})")
        return self.preset(indice // PRESETS_POR_BANCO, indice % PRESETS_POR_BANCO)

    def indice_de(self, banco: int, posicion: int) -> int:
        return banco * PRESETS_POR_BANCO + posicion

    def __iter__(self):
        """Recorre todos los presets en orden, como (indice, banco, preset)."""
        for i, banco in enumerate(self.bancos):
            for j, preset in enumerate(banco.presets):
                yield self.indice_de(i, j), banco, preset


def aplicar(preset: Preset, rpc: Any, escena: str | None = None) -> None:
    """Aplica un preset al motor.

    Todo el cambio son dos notificaciones sin round-trip: el preset base de Guitarix (si el
    preset lo referencia) y un único `set` con parámetros, stomps y escena juntos. Como van por
    el mismo socket TCP, el orden está garantizado.

    `rpc` es un `engine.rpc_client.GuitarixRPC`; se recibe como parámetro en vez de importarlo
    para no acoplar el modelo de datos al transporte.
    """
    if preset.guitarix_banco and preset.guitarix_preset:
        rpc.set_preset(preset.guitarix_banco, preset.guitarix_preset)
    pares = preset.pares_rpc(escena)
    if pares:
        rpc.fijar(*pares)
