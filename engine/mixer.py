"""Mezclador interno: N líneas de instrumento → M mezclas de monitor independientes.

Contexto (ver conversación en `docs/mezclas-en-vivo.md`): cada línea de instrumento (guitarra,
bajo, voz) es su propia instancia de Guitarix — un cliente JACK con su propia cadena de efectos,
ya cubierto por `engine/rpc_client.py` y `engine/audio_engine.py`. Lo que faltaba es la capa que
arma varias mezclas *distintas* de esas líneas al mismo tiempo (una por integrante + una para
PA), con volumen y paneo independiente de cada fuente en cada mezcla.

JACK por sí solo no alcanza para esto: conectar el output de dos clientes al mismo puerto de
entrada los SUMA automáticamente (eso ya es gratis), pero no hay forma de darle una ganancia
distinta a cada conexión — todas entran a volumen unidad. Hace falta un cliente JACK propio que
reciba las N fuentes, aplique una matriz de ganancia+paneo fuente×bus, y escriba M salidas. Eso es
este módulo.

División de responsabilidades: JACK maneja el *ruteo* (qué puerto físico o de Guitarix alimenta
cada entrada de este mezclador, y a qué salida física va cada bus) — eso se arma con conexiones
JACK normales, no hace falta reinventarlo. Este módulo maneja solo la *ganancia y el paneo por
mezcla*, que es lo único que JACK no ofrece.

## Paneo estéreo con salida mono por bus

Cada bus se arma **siempre** como una mezcla estéreo interna (cada fuente tiene ganancia + paneo
de -1 a 1), pero el modo del bus (`"mono"` o `"estereo"`, configurable por bus) decide cuántos
puertos JACK físicos expone:

- `"estereo"`: dos puertos de salida (`<bus>_L`, `<bus>_R`) — el paneo se escucha de verdad,
  como en cualquier mezcla estéreo.
- `"mono"`: un solo puerto de salida (`<bus>`) con el fold-down `(L+R)/2` de esa misma mezcla
  estéreo interna. El paneo no da lugar (mono no tiene "lugar"), pero sí sigue afectando el
  *balance relativo* entre fuentes — una fuente panceada duro pierde presencia en el pozo mono,
  tal como en cualquier consola real. Es la manera de mantener "la sensación de los paneos" aun
  cuando la salida física de ese monitor en particular es mono.

Ley de paneo elegida (`ganancias_pan`): **balance lineal con centro a ganancia unidad** — en
`paneo=0` cada canal queda exactamente en `ganancia` (sin atenuar ninguno), y al mover el paneo
hacia un extremo el canal opuesto cae linealmente a 0 mientras el canal del lado hacia el que se
panea se mantiene en `ganancia` (nunca sube). Esto es deliberado, no la ley de "potencia
constante" que suelen usar las consolas: con potencia constante, el centro queda a -3dB en cada
canal (`ganancia × 0.707`), lo que **rompe** la compatibilidad hacia atrás de `fijar_ganancia()` —
alguien que nunca toca el paneo esperaría que `ganancia=1.0` sea 1.0 de verdad, no -3dB. Con esta
ley, no tocar el paneo (queda en 0.0 por default) es matemáticamente idéntico a no tener paneo en
absoluto — `fijar_ganancia()` solo, como ya funcionaba, sigue dando exactamente lo mismo.

Contrapartida aceptada: escuchando en estéreo real, una fuente centrada suena un poco más fuerte
que una panceada al extremo (`ganancia` por los dos canales contra `ganancia` por uno solo) — el
clásico "bulto en el centro" de las leyes de paneo a 0dB. Es una decisión consciente: mantener
`fijar_ganancia()` predecible pesa más que ese matiz, que además solo importa en el bus configurado
como estéreo. En el fold-down a mono, esta ley da exactamente lo que pide el pedido original:
centro = presencia completa, extremo = -6dB (`(ganancia+0)/2`) — el paneo sigue sintiéndose como
pérdida de presencia aunque la salida sea un solo canal.

`mezclar()`/`mezclar_estereo()`/`ganancias_pan()`/`mono_desde_estereo()` son funciones puras (sin
JACK) para poder probar la matemática sin necesitar un servidor JACK corriendo. `MezcladorJack` es
el cliente real; se probó en vivo contra un jackd real bajo WSL2 (23/09/2026) — ver
`engine/test_mixer.py`.

Advertencia de concurrencia: `fijar_ganancia()`/`fijar_paneo()` se llaman desde un hilo de control
(RPC/API), pero la matriz se lee dentro del callback de proceso de JACK, que puede correr en
tiempo real. No hay lock: se confía en que una asignación de un `float` a una clave de `dict` es
atómica bajo el GIL de CPython (no hay torn read). Es una simplificación consciente — un
mezclador con más control de concurrencia (p. ej. doble buffer con swap atómico) queda para si
esto demuestra no alcanzar en la práctica.
"""

from __future__ import annotations

import math

import numpy as np

try:
    import jack
except ImportError:  # pragma: no cover - jack-client no es una dependencia del stdlib
    jack = None

MODOS_BUS = frozenset({"mono", "estereo"})


def mezclar(entradas: dict[str, np.ndarray], ganancias: dict[str, float]) -> np.ndarray:
    """Suma cada entrada multiplicada por su ganancia. Función pura, sin JACK.

    `entradas` y `ganancias` están indexados por el mismo nombre de fuente. Una fuente presente
    en `ganancias` pero no en `entradas` (o viceversa) se ignora — no es un error, porque el
    mezclador real puede tener ganancias configuradas para fuentes que todavía no conectó nadie.
    """
    fuentes = [f for f in ganancias if f in entradas]
    if not fuentes:
        primero = next(iter(entradas.values()), None)
        largo = len(primero) if primero is not None else 0
        return np.zeros(largo, dtype=np.float32)
    salida = np.zeros_like(entradas[fuentes[0]], dtype=np.float32)
    for f in fuentes:
        g = ganancias[f]
        if g != 0.0:
            salida += entradas[f] * np.float32(g)
    return salida


def ganancias_pan(ganancia: float, paneo: float) -> tuple[float, float]:
    """Ley de paneo de balance lineal, centro a ganancia unidad. `paneo`: -1 (izquierda) ..
    0 (centro) .. 1 (derecha). Devuelve (ganancia_izquierda, ganancia_derecha).

    En `paneo=0` da (ganancia, ganancia) — ningún canal se atenúa, así que no tocar el paneo es
    idéntico a no tener paneo. Ver la explicación completa (y por qué no es la ley de "potencia
    constante" habitual) en el docstring del módulo.
    """
    paneo = max(-1.0, min(1.0, paneo))
    return ganancia * (1.0 - max(paneo, 0.0)), ganancia * (1.0 + min(paneo, 0.0))


def mezclar_estereo(
    entradas: dict[str, np.ndarray],
    ganancias: dict[str, float],
    paneos: dict[str, float],
) -> tuple[np.ndarray, np.ndarray]:
    """Como `mezclar()`, pero devuelve (izquierda, derecha) aplicando paneo por fuente.
    Una fuente sin paneo explícito en `paneos` se toma centrada (0.0)."""
    ganancias_l: dict[str, float] = {}
    ganancias_r: dict[str, float] = {}
    for f, g in ganancias.items():
        gl, gr = ganancias_pan(g, paneos.get(f, 0.0))
        ganancias_l[f] = gl
        ganancias_r[f] = gr
    return mezclar(entradas, ganancias_l), mezclar(entradas, ganancias_r)


def mono_desde_estereo(izquierda: np.ndarray, derecha: np.ndarray) -> np.ndarray:
    """Fold-down a mono de una mezcla estéreo: promedio simple de L y R."""
    return (izquierda + derecha) * np.float32(0.5)


class ErrorDeMezclador(Exception):
    pass


class MezcladorJack:
    """Cliente JACK con `len(fuentes)` entradas y `len(buses)` salidas, mezcladas por una
    matriz de ganancia+paneo fuente×bus controlable en caliente. Cada bus es mono o estéreo
    según `modo_buses` (default: mono) — ver el docstring del módulo."""

    def __init__(
        self,
        fuentes: list[str],
        buses: list[str],
        nombre_cliente: str = "pedalsistema_mixer",
        ganancia_inicial: float = 1.0,
        modo_buses: dict[str, str] | None = None,
    ) -> None:
        if jack is None:
            raise ErrorDeMezclador(
                "Falta el paquete 'jack' (JACK-Client). Instalar en el venv del proyecto: "
                "pip install JACK-Client"
            )
        if not fuentes or not buses:
            raise ErrorDeMezclador("fuentes y buses no pueden estar vacíos")
        if len(set(fuentes)) != len(fuentes):
            raise ErrorDeMezclador(f"nombres de fuente repetidos: {fuentes}")
        if len(set(buses)) != len(buses):
            raise ErrorDeMezclador(f"nombres de bus repetidos: {buses}")

        modo_buses = modo_buses or {}
        for b, modo in modo_buses.items():
            if b not in buses:
                raise ErrorDeMezclador(f"modo_buses tiene un bus desconocido: {b!r}")
            if modo not in MODOS_BUS:
                raise ErrorDeMezclador(
                    f"modo desconocido para {b!r}: {modo!r}. Válidos: {sorted(MODOS_BUS)}"
                )
        if not math.isfinite(ganancia_inicial):
            raise ErrorDeMezclador(f"ganancia_inicial debe ser un número finito, no {ganancia_inicial!r}")

        self.fuentes = list(fuentes)
        self.buses = list(buses)
        self.modo_bus: dict[str, str] = {b: modo_buses.get(b, "mono") for b in buses}
        self.ganancias: dict[str, dict[str, float]] = {
            f: {b: ganancia_inicial for b in buses} for f in fuentes
        }
        self.paneos: dict[str, dict[str, float]] = {f: {b: 0.0 for b in buses} for f in fuentes}

        self._client = jack.Client(nombre_cliente)
        self._in_ports = {f: self._client.inports.register(f) for f in fuentes}
        self._out_ports: dict[str, dict[str, "jack.OwnPort"]] = {}
        for b in buses:
            if self.modo_bus[b] == "estereo":
                self._out_ports[b] = {
                    "L": self._client.outports.register(f"{b}_L"),
                    "R": self._client.outports.register(f"{b}_R"),
                }
            else:
                self._out_ports[b] = {"mono": self._client.outports.register(b)}
        self._client.set_process_callback(self._procesar)
        self._activo = False

    def _procesar(self, frames: int) -> None:
        entradas = {f: self._in_ports[f].get_array() for f in self.fuentes}
        for b in self.buses:
            ganancias_bus = {f: self.ganancias[f][b] for f in self.fuentes}
            paneos_bus = {f: self.paneos[f][b] for f in self.fuentes}
            izq, der = mezclar_estereo(entradas, ganancias_bus, paneos_bus)
            puertos = self._out_ports[b]
            if self.modo_bus[b] == "estereo":
                puertos["L"].get_array()[:] = izq
                puertos["R"].get_array()[:] = der
            else:
                puertos["mono"].get_array()[:] = mono_desde_estereo(izq, der)

    def iniciar(self) -> None:
        if not self._activo:
            self._client.activate()
            self._activo = True

    def detener(self) -> None:
        if self._activo:
            self._client.deactivate()
            self._activo = False
        self._client.close()

    def __enter__(self) -> "MezcladorJack":
        self.iniciar()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.detener()

    # -- Control de ganancia y paneo ------------------------------------------------

    def _validar_fuente_bus(self, fuente: str, bus: str) -> None:
        if fuente not in self.ganancias:
            raise ErrorDeMezclador(f"fuente desconocida: {fuente!r}. Válidas: {self.fuentes}")
        if bus not in self.buses:
            raise ErrorDeMezclador(f"bus desconocido: {bus!r}. Válidos: {self.buses}")

    def fijar_ganancia(self, fuente: str, bus: str, valor: float) -> None:
        self._validar_fuente_bus(fuente, bus)
        valor = float(valor)
        if not math.isfinite(valor):
            # NaN/Infinity pasan sin quejarse por json.loads() y por Pydantic (verificado:
            # ninguno de los dos rechaza estos valores por default) y de ahí llegarían
            # directo al callback de audio -- una vez que un NaN entra a la mezcla, se
            # propaga a todo lo que toca y deja ese canal mudo o roto sin ningún error
            # visible. Cortarlo acá es la única barrera real.
            raise ErrorDeMezclador(f"ganancia debe ser un número finito, no {valor!r}")
        self.ganancias[fuente][bus] = valor

    def fijar_paneo(self, fuente: str, bus: str, valor: float) -> None:
        """`valor`: -1 (izquierda) .. 0 (centro) .. 1 (derecha). Fuera de rango se recorta."""
        self._validar_fuente_bus(fuente, bus)
        valor = float(valor)
        if not math.isfinite(valor):
            raise ErrorDeMezclador(f"paneo debe ser un número finito, no {valor!r}")
        self.paneos[fuente][bus] = max(-1.0, min(1.0, valor))

    def matriz(self) -> dict[str, dict[str, dict[str, float]]]:
        return {
            f: {b: {"ganancia": self.ganancias[f][b], "paneo": self.paneos[f][b]}
                for b in self.buses}
            for f in self.fuentes
        }

    # -- Ruteo JACK (conectar puertos externos a este mezclador) ------------------

    def conectar_entrada(self, fuente: str, puerto_externo: str) -> None:
        """Conecta la salida de otro cliente JACK (p. ej. `gx_head_amp:out_0`) a la entrada
        `fuente` de este mezclador."""
        if fuente not in self._in_ports:
            raise ErrorDeMezclador(f"fuente desconocida: {fuente!r}. Válidas: {self.fuentes}")
        self._client.connect(puerto_externo, self._in_ports[fuente])

    def conectar_salida(self, bus: str, puerto_externo: str, canal: str | None = None) -> None:
        """Conecta un puerto de salida del bus `bus` a un puerto externo (p. ej. una salida
        física de la interfaz). En un bus mono, `canal` se ignora (hay un solo puerto). En un
        bus estéreo, `canal` es obligatorio: `"L"` o `"R"`.
        """
        if bus not in self._out_ports:
            raise ErrorDeMezclador(f"bus desconocido: {bus!r}. Válidos: {self.buses}")
        puertos = self._out_ports[bus]
        if self.modo_bus[bus] == "mono":
            if canal not in (None, "mono"):
                raise ErrorDeMezclador(f"el bus {bus!r} es mono, no tiene canal {canal!r}")
            self._client.connect(puertos["mono"], puerto_externo)
        else:
            if canal not in ("L", "R"):
                raise ErrorDeMezclador(
                    f"el bus {bus!r} es estéreo: hace falta canal='L' o canal='R'"
                )
            self._client.connect(puertos[canal], puerto_externo)
