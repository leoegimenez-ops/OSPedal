"""Mezclador interno: N líneas de instrumento → M mezclas de monitor independientes.

Contexto (ver conversación en `docs/mezclas-en-vivo.md`): cada línea de instrumento (guitarra,
bajo, voz) es su propia instancia de Guitarix — un cliente JACK con su propia cadena de efectos,
ya cubierto por `engine/rpc_client.py` y `engine/audio_engine.py`. Lo que faltaba es la capa que
arma varias mezclas *distintas* de esas líneas al mismo tiempo (una por integrante + una para
PA), con volumen independiente de cada fuente en cada mezcla.

JACK por sí solo no alcanza para esto: conectar el output de dos clientes al mismo puerto de
entrada los SUMA automáticamente (eso ya es gratis), pero no hay forma de darle una ganancia
distinta a cada conexión — todas entran a volumen unidad. Hace falta un cliente JACK propio que
reciba las N fuentes, aplique una matriz de ganancia fuente×bus, y escriba M salidas. Eso es este
módulo.

División de responsabilidades: JACK maneja el *ruteo* (qué puerto físico o de Guitarix alimenta
cada entrada de este mezclador, y a qué salida física va cada bus) — eso se arma con conexiones
JACK normales, no hace falta reinventarlo. Este módulo maneja solo la *ganancia por mezcla*, que
es lo único que JACK no ofrece.

`mezclar()` es una función pura (sin JACK) para poder probar la matemática sin necesitar un
servidor JACK corriendo. `MezcladorJack` es el cliente real; se probó en vivo contra un jackd real
bajo WSL2 (23/09/2026) — ver `engine/test_mixer.py`.

Advertencia de concurrencia: `fijar_ganancia()` se llama desde un hilo de control (RPC/API), pero
la matriz de ganancias se lee dentro del callback de proceso de JACK, que puede correr en tiempo
real. No hay lock: se confía en que una asignación de un `float` a una clave de `dict` es atómica
bajo el GIL de CPython (no hay torn read). Es una simplificación consciente — un mezclador con
más control de concurrencia (p. ej. doble buffer con swap atómico) queda para si esto demuestra no
alcanzar en la práctica.
"""

from __future__ import annotations

import numpy as np

try:
    import jack
except ImportError:  # pragma: no cover - jack-client no es una dependencia del stdlib
    jack = None


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


class ErrorDeMezclador(Exception):
    pass


class MezcladorJack:
    """Cliente JACK con `len(fuentes)` entradas y `len(buses)` salidas, mezcladas por una
    matriz de ganancia fuente×bus controlable en caliente."""

    def __init__(
        self,
        fuentes: list[str],
        buses: list[str],
        nombre_cliente: str = "pedalsistema_mixer",
        ganancia_inicial: float = 1.0,
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

        self.fuentes = list(fuentes)
        self.buses = list(buses)
        self.ganancias: dict[str, dict[str, float]] = {
            f: {b: ganancia_inicial for b in buses} for f in fuentes
        }
        self._client = jack.Client(nombre_cliente)
        self._in_ports = {f: self._client.inports.register(f) for f in fuentes}
        self._out_ports = {b: self._client.outports.register(b) for b in buses}
        self._client.set_process_callback(self._procesar)
        self._activo = False

    def _procesar(self, frames: int) -> None:
        entradas = {f: self._in_ports[f].get_array() for f in self.fuentes}
        for b in self.buses:
            ganancias_bus = {f: self.ganancias[f][b] for f in self.fuentes}
            self._out_ports[b].get_array()[:] = mezclar(entradas, ganancias_bus)

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

    # -- Control de ganancia ------------------------------------------------------

    def fijar_ganancia(self, fuente: str, bus: str, valor: float) -> None:
        if fuente not in self.ganancias:
            raise ErrorDeMezclador(f"fuente desconocida: {fuente!r}. Válidas: {self.fuentes}")
        if bus not in self.buses:
            raise ErrorDeMezclador(f"bus desconocido: {bus!r}. Válidos: {self.buses}")
        self.ganancias[fuente][bus] = float(valor)

    def matriz(self) -> dict[str, dict[str, float]]:
        return {f: dict(self.ganancias[f]) for f in self.fuentes}

    # -- Ruteo JACK (conectar puertos externos a este mezclador) ------------------

    def conectar_entrada(self, fuente: str, puerto_externo: str) -> None:
        """Conecta la salida de otro cliente JACK (p. ej. `gx_head_amp:out_0`) a la entrada
        `fuente` de este mezclador."""
        if fuente not in self._in_ports:
            raise ErrorDeMezclador(f"fuente desconocida: {fuente!r}. Válidas: {self.fuentes}")
        self._client.connect(puerto_externo, self._in_ports[fuente])

    def conectar_salida(self, bus: str, puerto_externo: str) -> None:
        """Conecta el bus `bus` a un puerto externo (p. ej. una salida física de la interfaz)."""
        if bus not in self._out_ports:
            raise ErrorDeMezclador(f"bus desconocido: {bus!r}. Válidos: {self.buses}")
        self._client.connect(self._out_ports[bus], puerto_externo)
