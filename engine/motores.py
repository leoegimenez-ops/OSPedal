"""Motores por tramo y cableado JACK de las líneas paralelas.

Cada instrumento tiene hasta cuatro tramos, cada uno con su propia instancia de Guitarix:

    pre   ─ lo que va antes del SPLIT (o toda la cadena, si no hay líneas paralelas)
    a, b  ─ las dos líneas paralelas
    post  ─ lo que va después del MERGE

Instancias con nombre fijo (`guitarix -N -p <puerto> -n <nombre> -J`): JACK las expone como
`<nombre>_amp` (parte mono: in_0 → out_0) y `<nombre>_fx` (parte estéreo: UNA entrada mono in_0 →
out_0/out_1). `-J` = no auto-conectarse: todo el cableado lo arma `cablear()`, así sabemos siempre
exactamente por dónde pasa la señal. Verificado el 25/09/2026 con jack_lsp.

Puertos RPC: el tramo "pre" usa el de siempre (7000 + índice de la línea, compatible con todo lo
anterior); los tramos extra, 7100 + 10 × índice + (1 a, 2 b, 3 post). Los tramos extra se levantan
recién cuando el usuario crea una línea paralela (arrancar un Guitarix tarda unos segundos) y
quedan vivos después, para que volver a dividir sea instantáneo.
"""

from __future__ import annotations

import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

TRAMOS = ("pre", "a", "b", "post")
_DESPLAZAMIENTO = {"a": 1, "b": 2, "post": 3}


class ErrorMotores(Exception):
    pass


def puerto_rpc(indice_linea: int, tramo: str) -> int:
    if tramo == "pre":
        return 7000 + indice_linea
    return 7100 + 10 * indice_linea + _DESPLAZAMIENTO[tramo]


def nombre_jack(linea: str, tramo: str) -> str:
    return f"ps_{linea}_{tramo}"


def puerto_escuchando(host: str, puerto: int) -> bool:
    try:
        with socket.create_connection((host, puerto), timeout=0.3):
            return True
    except OSError:
        return False


@dataclass
class Cableado:
    """Qué conexiones JACK hacen falta para una línea, según su disposición."""
    conexiones: list[tuple[str, str]]
    # Puertos de SALIDA que este cableado administra: antes de conectar, se les sacan todas
    # sus conexiones viejas (así mover el MERGE o quitar la línea B no deja cables colgados).
    administrados: list[str]


def plan_cableado(
    linea: str,
    con_split: bool,
    con_post: bool,
    puerto_split: Callable[[str, str], str],
    puerto_merge: Callable[[str, str], str],
    destino_l: str,
    destino_r: str,
) -> Cableado:
    """Arma la lista de conexiones. Función pura: se prueba sin JACK (engine/test_motores.py)."""
    amp = lambda t, p: f"{nombre_jack(linea, t)}_amp:{p}"      # noqa: E731
    fx = lambda t, p: f"{nombre_jack(linea, t)}_fx:{p}"        # noqa: E731
    c: list[tuple[str, str]] = []
    administrados = [amp(t, "out_0") for t in TRAMOS] + [fx(t, o) for t in TRAMOS for o in ("out_0", "out_1")]
    administrados += [puerto_split(linea, s) for s in ("a", "b")]
    administrados += [puerto_merge(linea, s) for s in ("L", "R", "mono")]

    if not con_split:
        c += [(amp("pre", "out_0"), fx("pre", "in_0")),
              (fx("pre", "out_0"), destino_l), (fx("pre", "out_1"), destino_r)]
        return Cableado(c, administrados)

    c.append((amp("pre", "out_0"), puerto_split(linea, "in")))
    for t in ("a", "b"):
        c += [(puerto_split(linea, t), amp(t, "in_0")),
              (amp(t, "out_0"), fx(t, "in_0")),
              (fx(t, "out_0"), puerto_merge(linea, f"{t}_L")),
              (fx(t, "out_1"), puerto_merge(linea, f"{t}_R"))]
    if con_post:
        # El motor solo recibe mono: las líneas se juntan en mono antes del tramo "post"
        # (límite aceptado por el usuario; ver engine/paralelo.py).
        c += [(puerto_merge(linea, "mono"), amp("post", "in_0")),
              (amp("post", "out_0"), fx("post", "in_0")),
              (fx("post", "out_0"), destino_l), (fx("post", "out_1"), destino_r)]
    else:
        c += [(puerto_merge(linea, "L"), destino_l), (puerto_merge(linea, "R"), destino_r)]
    return Cableado(c, administrados)


class Orquestador:
    """Levanta (si hace falta) el Guitarix de cada tramo y aplica el cableado JACK."""

    def __init__(
        self,
        lineas: list[str],
        host: str = "127.0.0.1",
        comando: str = "guitarix",
        dir_logs: str = "/tmp",
        lanzar: bool = True,
        puertos_pre: dict[str, int] | None = None,
    ) -> None:
        """`puertos_pre`: puerto del tramo "pre" por línea cuando la configuración (LINEAS) no
        usa el 7000 + índice de siempre."""
        self.puertos_pre = dict(puertos_pre or {})
        self.indices = {l: i for i, l in enumerate(lineas)}
        self.host = host
        self.comando = comando
        self.dir_logs = Path(dir_logs)
        self.lanzar = lanzar
        self._procesos: dict[tuple[str, str], subprocess.Popen] = {}

    def puerto(self, linea: str, tramo: str) -> int:
        if linea not in self.indices:
            raise ErrorMotores(f"línea desconocida: {linea!r}")
        if tramo not in TRAMOS:
            raise ErrorMotores(f"tramo desconocido: {tramo!r}")
        if tramo == "pre" and linea in self.puertos_pre:
            return self.puertos_pre[linea]
        return puerto_rpc(self.indices[linea], tramo)

    def asegurar(self, linea: str, tramo: str, espera: float = 25.0) -> int:
        """Devuelve el puerto RPC del motor del tramo, arrancándolo si no está. Bloquea hasta
        que responde (un Guitarix tarda 2-6 s en arrancar)."""
        puerto = self.puerto(linea, tramo)
        if puerto_escuchando(self.host, puerto):
            return puerto
        if not self.lanzar:
            raise ErrorMotores(f"el motor {linea}/{tramo} (puerto {puerto}) no está corriendo")
        log = open(self.dir_logs / f"gx_{linea}_{tramo}.log", "ab")
        self._procesos[(linea, tramo)] = subprocess.Popen(
            [self.comando, "-N", "-p", str(puerto), "-n", nombre_jack(linea, tramo), "-J"],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            cwd=str(self.dir_logs), start_new_session=True,
        )
        limite = time.monotonic() + espera
        while time.monotonic() < limite:
            if puerto_escuchando(self.host, puerto):
                time.sleep(0.5)            # el RPC escucha un toque antes de que JACK registre puertos
                return puerto
            if self._procesos[(linea, tramo)].poll() is not None:
                raise ErrorMotores(f"el motor {linea}/{tramo} se cerró al arrancar (ver {log.name})")
            time.sleep(0.25)
        raise ErrorMotores(f"el motor {linea}/{tramo} no respondió en {espera:.0f} s")

    @staticmethod
    def aplicar(cliente_jack: Any, cableado: Cableado) -> list[str]:
        """Aplica un plan con cualquier cliente JACK activo (cualquiera puede conectar puertos
        ajenos). Devuelve los problemas encontrados en vez de cortar a la mitad: un cable que
        falta es mejor que una línea entera muda."""
        problemas = []
        existentes = {p.name for p in cliente_jack.get_ports()}
        for puerto in cableado.administrados:
            if puerto not in existentes:
                continue
            for destino in cliente_jack.get_all_connections(puerto):
                try:
                    cliente_jack.disconnect(puerto, destino)
                except Exception as exc:  # noqa: BLE001
                    problemas.append(f"desconectar {puerto} -> {destino.name}: {exc}")
        for origen, destino in cableado.conexiones:
            if origen not in existentes or destino not in existentes:
                problemas.append(f"falta un puerto: {origen} -> {destino}")
                continue
            try:
                cliente_jack.connect(origen, destino)
            except Exception as exc:  # noqa: BLE001
                if "already exists" not in str(exc).lower():
                    problemas.append(f"conectar {origen} -> {destino}: {exc}")
        return problemas
