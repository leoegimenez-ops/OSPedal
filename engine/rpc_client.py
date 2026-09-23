"""Cliente JSON-RPC para el motor Guitarix.

Guitarix expone un servidor JSON-RPC 2.0 sobre socket TCP plano cuando se arranca en modo
headless:

    guitarix -N -p 7000

El protocolo está documentado en `docs/guitarix-integracion.md` y la lista completa de métodos
en `docs/guitarix-rpc-methods.md`. Particularidades del servidor que condicionan este cliente,
las tres primeras confirmadas leyendo el código fuente del motor y la última contra un Guitarix
real corriendo (22/09/2026, ver docs/guitarix-integracion.md):

1. Los mensajes van delimitados por salto de línea, no por longitud ni framing HTTP.
2. Los parámetros deben ser posicionales (array JSON). Pasarlos por nombre devuelve el error
   -32000 "by-name parameters not implemented".
3. El `id` de la respuesta viene como **string** aunque se lo mande como número (se pide `id: 1`,
   responde `"id": "1"`). `llamar()` compara con `str()` en ambos lados por esto.
4. `getversion` no devuelve un string simple: devuelve un array `[major, minor, "version_completa"]`,
   por ejemplo `[1, 1, "0.47.0"]`.
"""

from __future__ import annotations

import json
import socket
from collections import deque
from typing import Any, Iterator

PUERTO_DEFECTO = 7000
HOST_DEFECTO = "localhost"

# Tokens aceptados por el método `listen` para suscribirse a eventos del motor.
TOKENS_EVENTOS = frozenset({
    "all",
    "preset",
    "state",
    "freq",
    "display",
    "tuner",
    "presetlist_changed",
    "logger",
    "midi",
    "param",
    "plugins_changed",
    "misc",
    "units_changed",
})


class GuitarixError(Exception):
    """Error devuelto por el servidor RPC de Guitarix."""

    def __init__(self, codigo: int, mensaje: str) -> None:
        super().__init__(f"[{codigo}] {mensaje}")
        self.codigo = codigo
        self.mensaje = mensaje


class GuitarixRPC:
    """Conexión con el motor Guitarix.

    Uso básico:

        with GuitarixRPC() as gx:
            print(gx.version())
            gx.set_preset("Rock", "Crunch")
    """

    def __init__(
        self,
        host: str = HOST_DEFECTO,
        puerto: int = PUERTO_DEFECTO,
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.puerto = puerto
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._buffer = b""
        self._id = 0
        # Las notificaciones pueden llegar intercaladas con las respuestas. Las que aparezcan
        # mientras esperamos un resultado se guardan acá en vez de descartarse.
        self._notificaciones: deque[dict[str, Any]] = deque()

    # -- Ciclo de vida ----------------------------------------------------------------

    def conectar(self) -> None:
        if self._sock is not None:
            return
        self._sock = socket.create_connection((self.host, self.puerto), timeout=self.timeout)
        # TCP_NODELAY: sin esto, el algoritmo de Nagle puede retrasar los mensajes cortos
        # (un cambio de preset son pocos bytes) hasta 40ms, que en escenario se nota.
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def cerrar(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        self._buffer = b""
        self._notificaciones.clear()

    def __enter__(self) -> GuitarixRPC:
        self.conectar()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.cerrar()

    # -- Transporte -------------------------------------------------------------------

    def _enviar(self, mensaje: dict[str, Any]) -> None:
        if self._sock is None:
            raise ConnectionError("No hay conexión con Guitarix. Llamar a conectar() primero.")
        crudo = json.dumps(mensaje, separators=(",", ":")).encode("utf-8") + b"\n"
        self._sock.sendall(crudo)

    def _leer_linea(self) -> dict[str, Any]:
        if self._sock is None:
            raise ConnectionError("No hay conexión con Guitarix.")
        while b"\n" not in self._buffer:
            trozo = self._sock.recv(4096)
            if not trozo:
                raise ConnectionError("Guitarix cerró la conexión.")
            self._buffer += trozo
        linea, self._buffer = self._buffer.split(b"\n", 1)
        return json.loads(linea.decode("utf-8"))

    # -- Llamadas ---------------------------------------------------------------------

    def llamar(self, metodo: str, *params: Any) -> Any:
        """Llama a un método que devuelve resultado y espera la respuesta.

        Solo para métodos con `has_result = true`. Ver `docs/guitarix-rpc-methods.md`.
        """
        self.conectar()
        self._id += 1
        id_peticion = self._id
        self._enviar({
            "jsonrpc": "2.0",
            "method": metodo,
            "params": list(params),
            "id": id_peticion,
        })

        while True:
            mensaje = self._leer_linea()
            id_mensaje = mensaje.get("id")
            # Guitarix devuelve el id como string aunque se lo mandemos como
            # número (verificado con un socket crudo contra el motor real:
            # pedís id=1, responde "id":"1"). Comparar sin convertir nunca
            # hace match y el cliente termina esperando hasta el timeout del
            # socket. Nuestro servidor simulado no reproducía este detalle
            # -- hacía eco del id tal cual se lo mandaban -- así que los
            # tests no lo agarraron; ver test_rpc_client.py.
            if str(id_mensaje) == str(id_peticion):
                if "error" in mensaje:
                    error = mensaje["error"]
                    raise GuitarixError(error.get("code", 0), error.get("message", ""))
                return mensaje.get("result")
            if "error" in mensaje and id_mensaje is None:
                # Errores de parseo: el servidor responde con id nulo y no habrá respuesta
                # para nuestra petición, así que no tiene sentido seguir esperando.
                error = mensaje["error"]
                raise GuitarixError(error.get("code", 0), error.get("message", ""))
            if "method" in mensaje:
                self._notificaciones.append(mensaje)

    def notificar(self, metodo: str, *params: Any) -> None:
        """Envía un método sin esperar respuesta.

        Es el modo correcto para los métodos con `has_result = false` y para todo lo que esté
        en el camino crítico de latencia: evita el round-trip completo.
        """
        self.conectar()
        self._enviar({"jsonrpc": "2.0", "method": metodo, "params": list(params)})

    # -- Eventos ----------------------------------------------------------------------

    def suscribir(self, *tokens: str) -> None:
        """Se suscribe a grupos de eventos del motor.

        Permite mantener sincronizadas la GUI y la PWA sin hacer polling.
        """
        for token in tokens:
            if token not in TOKENS_EVENTOS:
                raise ValueError(
                    f"Token de evento desconocido: {token!r}. "
                    f"Válidos: {', '.join(sorted(TOKENS_EVENTOS))}"
                )
            self.notificar("listen", token)

    def desuscribir(self, *tokens: str) -> None:
        for token in tokens:
            self.notificar("unlisten", token)

    def eventos(self, timeout: float | None = None) -> Iterator[dict[str, Any]]:
        """Itera sobre las notificaciones que emite el motor.

        Primero devuelve las que se hayan acumulado durante llamadas previas, y después queda
        leyendo del socket. Con `timeout=None` bloquea indefinidamente; con un valor numérico
        corta por `socket.timeout` al agotarse.
        """
        while self._notificaciones:
            yield self._notificaciones.popleft()

        self.conectar()
        assert self._sock is not None
        anterior = self._sock.gettimeout()
        self._sock.settimeout(timeout)
        try:
            while True:
                try:
                    mensaje = self._leer_linea()
                except socket.timeout:
                    return
                if "method" in mensaje:
                    yield mensaje
        finally:
            if self._sock is not None:
                self._sock.settimeout(anterior)

    # -- Atajos de uso frecuente ------------------------------------------------------

    def version(self) -> Any:
        return self.llamar("getversion")

    def estado(self) -> Any:
        return self.llamar("getstate")

    def carga_cpu(self) -> Any:
        """Carga de CPU reportada por JACK. Para el monitor de rendimiento en escenario."""
        return self.llamar("jack_cpu_load")

    def bancos(self) -> Any:
        return self.llamar("banks")

    def presets(self, banco: str) -> Any:
        return self.llamar("presets", banco)

    def set_preset(self, banco: str, preset: str) -> None:
        """Cambia el preset activo. Notificación pura: sin round-trip, sin gap de audio."""
        self.notificar("setpreset", banco, preset)

    def parametros(self) -> Any:
        return self.llamar("parameterlist")

    def obtener(self, *nombres: str) -> Any:
        return self.llamar("get", *nombres)

    def fijar(self, *pares: Any) -> None:
        """Fija parámetros alternando nombre y valor: fijar("amp.gain", 0.8).

        El motor exige cantidad par de argumentos; si no, devuelve -32602. Como `set` va como
        notificación, ese error del servidor no llegaría a verse: lo validamos acá.
        """
        if len(pares) % 2:
            raise ValueError(
                "fijar() requiere pares nombre/valor: la cantidad de argumentos debe ser par."
            )
        self.notificar("set", *pares)

    def plugins(self) -> Any:
        return self.llamar("pluginlist")

    def orden_rack(self) -> Any:
        return self.llamar("get_rack_unit_order")

    def archivos(self, categoria: str) -> Any:
        """Llama a `get_file_list`. Existe en la tabla de métodos RPC pero no
        pude confirmar para qué categoría de unidad está pensado ni la forma
        exacta de `categoria` — **no es** el mecanismo real de NAM/RTNeural
        (ver `cargar_nam`/`cargar_rtneural` más abajo, esos sí están
        verificados contra el código fuente del motor). Se deja por si sirve
        para otra cosa; no usar para cargar capturas todavía.
        """
        return self.llamar("get_file_list", categoria)

    def recargar_impulse_responses(self) -> None:
        """Vuelve a escanear el directorio de IRs sin reiniciar el motor.

        Guitarix no re-escanea solo cuando se copian archivos nuevos mientras
        corre; hay que pedírselo después de que el usuario agregue modelos.
        """
        self.notificar("reload_impresp_list")

    def directorios_impulse_response(self) -> Any:
        return self.llamar("load_impresp_dirs")

    # -- Capturas NAM / RTNeural --------------------------------------------------
    #
    # Verificado en el código fuente del motor (gx_neural_plugins.cpp/.h,
    # gx_engine.cpp): NeuralAmp y RtNeural NO son una propiedad del bloque
    # "amp" — son unidades de rack propias, cada una con un par de parámetros
    # de texto/número normales, sin ningún método RPC dedicado:
    #
    #   <ranura>.loadpath  (string)  carpeta a escanear; al cambiar dispara un
    #                                rescan interno (create_nam_filelist)
    #   <ranura>.flist     (número)  índice dentro de esa carpeta a cargar;
    #                                0 siempre es "None", los archivos
    #                                encontrados ocupan 1..126 en el orden que
    #                                los devuelve el sistema de archivos (NO
    #                                alfabético, no está garantizado)
    #
    # Guitarix filtra por sufijo exacto: ".nam" para NeuralAmp, ".json" o
    # "idax" (".aidax") para RtNeural. `loadpath` arranca vacío — no hay
    # convención de carpeta fija del lado de Guitarix, así que apuntarlo a
    # nuestro propio models/nam o models/aidax es una decisión enteramente
    # nuestra, no algo que haya que descubrir.
    #
    # Nombres de ranura reales (gx_engine.cpp:310-315):
    #   nam / snam / mnam        -> NeuralAmp (mono, segunda instancia, A/B)
    #   rtneural / srtneural / mrtneural -> RtNeural (mono, segunda, A/B)
    #
    # Como el orden de `flist` no está garantizado, en vez de adivinar el
    # índice apuntamos `loadpath` a una carpeta que contenga solo el archivo
    # que queremos (o un symlink a él) y usamos `flist=1` siempre — determinista,
    # sin depender de leer de vuelta la lista que arma Guitarix.

    def _insertar_en_rack_si_falta(self, unidad: str) -> None:
        """Inserta `unidad` en la cadena mono (0) del rack si todavía no está ahí.

        Verificado contra un Guitarix 0.47.0 real (23/09/2026): cargar un modelo con
        `loadpath`/`flist` NO alcanza para que se escuche — la unidad tiene que estar además en
        la cadena del rack (`get_rack_unit_order`), algo que no estaba documentado antes de esta
        verificación. `insert_rack_unit` es una **notificación** (`has_result: false`), no una
        llamada con resultado: mandarla con `id` (como si fuera `llamar()`) hace que el motor
        devuelva un `"result":` mal formado que rompe el parseo JSON del lado del cliente — hay
        que usar `notificar()`. Firma real, confirmada leyendo `jsonrpc.cpp` en el código fuente
        del motor (no estaba en `docs/guitarix-rpc-methods.md`): `(unidad: str, antes_de: str,
        estéreo: int)`. `antes_de=""` inserta al final de la cadena; `estéreo=0` es la cadena
        mono, la que usan NAM/RTNeural (señal de guitarra).
        """
        orden = self.llamar("get_rack_unit_order", 0)
        if unidad not in orden:
            self.notificar("insert_rack_unit", unidad, "", 0)

    def cargar_nam(self, carpeta: str, indice: int = 1, ranura: str = "nam") -> None:
        """Carga un modelo .nam y lo deja sonando. `carpeta` es una ruta absoluta que Guitarix
        va a escanear buscando archivos *.nam; `indice` es la posición dentro
        de esa carpeta (1 = primer archivo encontrado). Si la carpeta tiene
        un solo *.nam, `indice=1` siempre apunta a ese archivo sin ambigüedad.
        `ranura`: "nam" (principal), "snam" (segunda) o "mnam" (modo A/B).
        """
        self.fijar(f"{ranura}.loadpath", carpeta)
        self.fijar(f"{ranura}.flist", indice)
        self._insertar_en_rack_si_falta(ranura)
        self.fijar(f"{ranura}.on_off", 1)

    def cargar_rtneural(self, carpeta: str, indice: int = 1, ranura: str = "rtneural") -> None:
        """Como `cargar_nam` pero para modelos .json/.aidax de RTNeural.
        `ranura`: "rtneural", "srtneural" o "mrtneural" (modo A/B)."""
        self.fijar(f"{ranura}.loadpath", carpeta)
        self.fijar(f"{ranura}.flist", indice)
        self._insertar_en_rack_si_falta(ranura)
        self.fijar(f"{ranura}.on_off", 1)

    def mapa_midi(self) -> Any:
        return self.llamar("get_midi_controller_map")

    def midi_learn(self, activo: bool) -> None:
        """Activa el modo aprendizaje MIDI.

        Con esto la pedalera se mapea moviendo un control, sin necesidad de conocer el modelo
        del dispositivo: es la base del soporte MIDI genérico del proyecto.
        """
        self.notificar("midi_set_config_mode", activo)


def _diagnostico() -> int:
    """Chequeo de conectividad contra un Guitarix headless en ejecución.

    Pensado para validar las fases 1 y 2: confirma que el motor está vivo y respondiendo.

        python -m engine.rpc_client [host] [puerto]
    """
    import sys

    host = sys.argv[1] if len(sys.argv) > 1 else HOST_DEFECTO
    puerto = int(sys.argv[2]) if len(sys.argv) > 2 else PUERTO_DEFECTO

    try:
        with GuitarixRPC(host, puerto) as gx:
            print(f"Conectado a {host}:{puerto}")
            print(f"  versión .......... {gx.version()}")
            print(f"  estado ........... {gx.estado()}")
            print(f"  carga CPU (JACK) . {gx.carga_cpu()}")
            bancos = gx.bancos()
            print(f"  bancos ........... {len(bancos) if bancos else 0}")
    except ConnectionRefusedError:
        print(f"No se pudo conectar a {host}:{puerto}.")
        print("¿Está corriendo el motor? Arrancalo con:  guitarix -N -p 7000")
        return 1
    except (OSError, GuitarixError) as exc:
        print(f"Error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_diagnostico())
