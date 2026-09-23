"""Pruebas de server/api.py contra un GuitarixRPC falso (sin motor real).

El flujo end-to-end (curl + un cliente websockets real contra un uvicorn real, hablando con un
Guitarix 0.47.0 real corriendo bajo WSL2) ya se hizo a mano el 23/09/2026 -- ver el docstring de
api.py para el detalle de qué se confirmó ahí. Esto complementa esa prueba manual con algo que
corre solo, sin depender de un motor levantado: reemplaza `server.api.GuitarixRPC` por un fake
antes de crear el `TestClient`.

Requiere `fastapi`, `httpx2` (que pide `TestClient`) y `websockets` -- instalados en el venv del
proyecto (`.venv`), no en el Python del sistema (Debian bloquea `pip install` fuera de un venv,
PEP 668).

Se ejecuta como modulo (python -m server.test_api) para que el import relativo funcione igual en
Windows y en Linux/WSL2.
"""
import sys
import time

from fastapi.testclient import TestClient

import server.api as api

fallos = []


def check(nombre, ok, detalle=""):
    print(f"  {'OK  ' if ok else 'FALLA'}  {nombre}{'  ' + detalle if detalle else ''}")
    if not ok:
        fallos.append(nombre)


class GXFalso:
    """Reemplaza a GuitarixRPC. Cada instancia se registra en `instancias` para poder
    inspeccionar, desde el test, qué llamadas le llegaron."""

    instancias: list["GXFalso"] = []

    def __init__(self, host="127.0.0.1", puerto=7000, timeout=5.0):
        self.conectado = False
        self.llamadas = []
        self.suscripciones = []
        self.eventos_pendientes = []
        self.falla_conectar = False
        self.falla_version = None  # GuitarixError, si se quiere simular un error del motor
        GXFalso.instancias.append(self)

    def conectar(self):
        if self.falla_conectar:
            raise OSError("conexión rechazada (simulada)")
        self.conectado = True

    def cerrar(self):
        self.conectado = False

    def version(self):
        if self.falla_version:
            raise self.falla_version
        return [1, 1, "0.47.0"]

    def estado(self):
        return "running"

    def carga_cpu(self):
        return 3.5

    def bancos(self):
        return [{"name": "Factory", "mutable": 0, "type": "factory", "presets": ["Clean", "Lead"]}]

    def presets(self, banco):
        return ["Clean", "Lead"]

    def set_preset(self, banco, preset):
        self.llamadas.append(("setpreset", banco, preset))

    def obtener(self, *nombres):
        return {n: 1.0 for n in nombres}

    def fijar(self, *pares):
        if len(pares) % 2:
            raise ValueError("fijar() requiere pares nombre/valor: la cantidad debe ser par.")
        self.llamadas.append(("set",) + pares)

    def suscribir(self, *tokens):
        self.suscripciones.extend(tokens)

    def eventos(self, timeout=None):
        if self.eventos_pendientes:
            yield self.eventos_pendientes.pop(0)
        else:
            time.sleep(0.02)


class MixerFalso:
    """Reemplaza a MezcladorJack -- sin tocar JACK para nada."""

    instancias: list["MixerFalso"] = []

    def __init__(self, fuentes, buses, nombre_cliente="pedalsistema_mixer", ganancia_inicial=1.0):
        self.fuentes = list(fuentes)
        self.buses = list(buses)
        self.ganancias = {f: {b: ganancia_inicial for b in buses} for f in fuentes}
        self.falla_iniciar = False
        MixerFalso.instancias.append(self)

    def iniciar(self):
        if self.falla_iniciar:
            raise api.ErrorDeMezclador("jackd no está corriendo (simulado)")

    def detener(self):
        pass

    def fijar_ganancia(self, fuente, bus, valor):
        if fuente not in self.ganancias:
            raise api.ErrorDeMezclador(f"fuente desconocida: {fuente!r}. Válidas: {self.fuentes}")
        if bus not in self.buses:
            raise api.ErrorDeMezclador(f"bus desconocido: {bus!r}. Válidos: {self.buses}")
        self.ganancias[fuente][bus] = float(valor)

    def matriz(self):
        return {f: dict(self.ganancias[f]) for f in self.fuentes}


def reset():
    """Vuelve api._gx/_mezclador a None para que el próximo endpoint cree fakes nuevas."""
    GXFalso.instancias.clear()
    api._gx = None
    MixerFalso.instancias.clear()
    api._mezclador = None


api.GuitarixRPC = GXFalso
api.MezcladorJack = MixerFalso
client = TestClient(api.app)


print("\n1. /salud no toca al motor")
reset()
r = client.get("/salud")
check("200", r.status_code == 200, f"-> {r.status_code}")
check("body", r.json() == {"ok": True})
check("no crea conexion", GXFalso.instancias == [])

print("\n2. /estado")
reset()
r = client.get("/estado")
check("200", r.status_code == 200, f"-> {r.status_code} {r.text}")
check("body", r.json() == {"version": [1, 1, "0.47.0"], "estado": "running", "carga_cpu": 3.5},
      f"-> {r.json()}")

print("\n3. /bancos y /bancos/{banco}/presets")
reset()
r = client.get("/bancos")
check("forma real: objetos con name/mutable/type/presets", r.json() ==
      [{"name": "Factory", "mutable": 0, "type": "factory", "presets": ["Clean", "Lead"]}],
      f"-> {r.json()}")
r = client.get("/bancos/Factory/presets")
check("presets del banco", r.json() == ["Clean", "Lead"], f"-> {r.json()}")

print("\n4. POST /preset es una notificacion (no espera resultado)")
reset()
r = client.post("/preset", json={"banco": "Factory", "preset": "Lead"})
check("200", r.status_code == 200 and r.json() == {"ok": True})
check("llega al motor", GXFalso.instancias[0].llamadas == [("setpreset", "Factory", "Lead")],
      f"-> {GXFalso.instancias[0].llamadas}")

print("\n5. GET /parametros")
reset()
r = client.get("/parametros", params={"nombres": "amp.gain, eq.peak1"})
check("junta y separa por coma (con espacios)", r.json() == {"amp.gain": 1.0, "eq.peak1": 1.0},
      f"-> {r.json()}")
r = client.get("/parametros", params={"nombres": ""})
check("nombres vacio da 400", r.status_code == 400, f"-> {r.status_code}")

print("\n6. POST /parametros")
reset()
r = client.post("/parametros", json={"pares": {"amp.gain": 0.8, "eq.peak1": 200}})
check("200", r.status_code == 200 and r.json() == {"ok": True})
check("llega como pares alternados", GXFalso.instancias[0].llamadas ==
      [("set", "amp.gain", 0.8, "eq.peak1", 200)], f"-> {GXFalso.instancias[0].llamadas}")

print("\n7. Guitarix inalcanzable -> 503")
reset()
GXFalso_original_falla = GXFalso
class GXInalcanzable(GXFalso):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.falla_conectar = True
api.GuitarixRPC = GXInalcanzable
r = client.get("/estado")
check("503", r.status_code == 503, f"-> {r.status_code} {r.text}")
api.GuitarixRPC = GXFalso

print("\n8. Error del motor -> 502")
reset()
from engine.rpc_client import GuitarixError
r = client.get("/estado")  # primero conecta normal para instanciar la fake
api._gx.falla_version = GuitarixError(-32601, "Method not found")
r = client.get("/estado")
check("502", r.status_code == 502, f"-> {r.status_code} {r.text}")
check("mensaje del motor visible", "Method not found" in r.text, f"-> {r.text}")

print("\n9. WebSocket /eventos reenvia lo que llega del motor")
reset()
eventos_canned = [
    {"jsonrpc": "2.0", "method": "preset_changed", "params": ["Factory", "Lead"]},
    {"jsonrpc": "2.0", "method": "state_changed", "params": ["run"]},
]
with client.websocket_connect("/eventos") as ws:
    # La conexion del websocket es propia (no la de _motor()), asi que la fake queda en
    # una instancia nueva -- la ultima registrada.
    fake_ws = GXFalso.instancias[-1]
    fake_ws.eventos_pendientes = list(eventos_canned)
    recibidos = [ws.receive_json() for _ in eventos_canned]
    check("recibe los dos eventos en orden", recibidos == eventos_canned, f"-> {recibidos}")
    check("se suscribe a todo", fake_ws.suscripciones == ["all"], f"-> {fake_ws.suscripciones}")
check("se puede cerrar sin colgarse", True)  # si el proceso llega hasta aca, no se colgo

print("\n10. /mezclador/matriz y /mezclador/ganancia")
reset()
r = client.get("/mezclador/matriz")
check("200", r.status_code == 200, f"-> {r.status_code} {r.text}")
cuerpo = r.json()
check("usa las fuentes/buses configurados", cuerpo["fuentes"] == api.FUENTES_MIXER and
      cuerpo["buses"] == api.BUSES_MIXER, f"-> {cuerpo['fuentes']} / {cuerpo['buses']}")
check("ganancia inicial 1.0 para todos", all(
    v == 1.0 for fila in cuerpo["matriz"].values() for v in fila.values()), f"-> {cuerpo['matriz']}")

r = client.post("/mezclador/ganancia", json={"fuente": api.FUENTES_MIXER[0],
                                              "bus": api.BUSES_MIXER[-1], "valor": 0.3})
check("200", r.status_code == 200 and r.json() == {"ok": True})
check("se aplica en la instancia", MixerFalso.instancias[0].ganancias[api.FUENTES_MIXER[0]][api.BUSES_MIXER[-1]] == 0.3,
      f"-> {MixerFalso.instancias[0].ganancias}")

r = client.post("/mezclador/ganancia", json={"fuente": "no_existe", "bus": api.BUSES_MIXER[0], "valor": 1.0})
check("400 fuente desconocida", r.status_code == 400, f"-> {r.status_code} {r.text}")

print("\n11. Mezclador sin JACK disponible -> 503")
reset()


class MixerQueFalla(MixerFalso):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.falla_iniciar = True


api.MezcladorJack = MixerQueFalla
r = client.get("/mezclador/matriz")
check("503", r.status_code == 503, f"-> {r.status_code} {r.text}")
api.MezcladorJack = MixerFalso
api._mezclador = None

print("\n" + ("FALLARON: " + ", ".join(fallos) if fallos else "TODO OK"))
sys.exit(1 if fallos else 0)
