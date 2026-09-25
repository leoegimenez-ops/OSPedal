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
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

# Las setlists de trabajo (las que escribe el botón de guardar) van a un directorio temporal: los
# tests no deben tocar presets/setlists/ del repo. Tiene que fijarse ANTES de importar la API,
# que lee la variable al cargar el módulo.
_DIR_SETLISTS_TEST = tempfile.mkdtemp(prefix="setlists_test_")
os.environ["SETLISTS_DIR"] = _DIR_SETLISTS_TEST

import server.api as api  # noqa: E402

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
        self.falla_conexion = False  # simula que el socket se corto a mitad de pedido
        self.rack = {0: ["ampstack", "freeverb"], 1: []}
        GXFalso.instancias.append(self)

    def conectar(self):
        if self.falla_conectar:
            raise OSError("conexión rechazada (simulada)")
        self.conectado = True

    def cerrar(self):
        self.conectado = False

    def version(self):
        if self.falla_conexion:
            raise ConnectionError("se perdió la conexión (simulada)")
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

    def orden_rack(self, cadena=0):
        return list(self.rack[cadena])

    def insertar_unidad(self, unidad, antes_de="", estereo=False):
        self.llamadas.append(("insert", unidad, int(estereo)))
        self.rack[int(estereo)].append(unidad)

    def quitar_unidad(self, unidad, estereo=False):
        self.llamadas.append(("remove", unidad, int(estereo)))
        self.rack[int(estereo)].remove(unidad)

    def plugins(self):
        return [
            {"id": "12AX7", "flags": 0x128, "name": "12AX7", "category": ""},
            {"id": "ampstack", "flags": 131332, "name": "Amp", "category": ""},
            {"id": "noise_gate", "flags": 0x2094A, "name": "Noise Gate", "category": "NONE"},
            {"id": "ts9sim", "flags": 0x10108, "name": "Tube Screamer", "category": "Distortion"},
            {"id": "freeverb", "flags": 0x10108, "name": "Freeverb", "category": "Reverb"},
            {"id": "echo", "flags": 0x10108, "name": "Echo", "category": "Echo / Delay"},
            {"id": "chorus", "flags": 0x109, "name": "Chorus", "category": "Modulation"},
        ]

    def consultar_unidad(self, unidad):
        if unidad == "ampstack":
            return {
                "ampstack.on_off": {"name": "on/off", "type": "bool", "value": {"ampstack.on_off": 1}},
                "ampstack.position": {"name": "", "type": "int", "lower_bound": -9999,
                                       "upper_bound": 9999, "value": {"ampstack.position": 27}},
                "amp2.stage1.Pregain": {"name": "Pregain", "type": "float", "lower_bound": -20,
                                         "upper_bound": 20, "step": 0.1,
                                         "value": {"amp2.stage1.Pregain": -6}},
            }
        return {}

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

    def __init__(self, fuentes, buses, nombre_cliente="pedalsistema_mixer", ganancia_inicial=1.0,
                 modo_buses=None):
        self.fuentes = list(fuentes)
        self.buses = list(buses)
        modo_buses = modo_buses or {}
        self.modo_bus = {b: modo_buses.get(b, "mono") for b in buses}
        self.ganancias = {f: {b: ganancia_inicial for b in buses} for f in fuentes}
        self.paneos = {f: {b: 0.0 for b in buses} for f in fuentes}
        self.falla_iniciar = False
        MixerFalso.instancias.append(self)

    def iniciar(self):
        if self.falla_iniciar:
            raise api.ErrorDeMezclador("jackd no está corriendo (simulado)")

    def detener(self):
        pass

    def _validar(self, fuente, bus):
        if fuente not in self.ganancias:
            raise api.ErrorDeMezclador(f"fuente desconocida: {fuente!r}. Válidas: {self.fuentes}")
        if bus not in self.buses:
            raise api.ErrorDeMezclador(f"bus desconocido: {bus!r}. Válidos: {self.buses}")

    def fijar_ganancia(self, fuente, bus, valor):
        self._validar(fuente, bus)
        self.ganancias[fuente][bus] = float(valor)

    def fijar_paneo(self, fuente, bus, valor):
        self._validar(fuente, bus)
        self.paneos[fuente][bus] = max(-1.0, min(1.0, float(valor)))

    def matriz(self):
        return {f: {b: {"ganancia": self.ganancias[f][b], "paneo": self.paneos[f][b]}
                    for b in self.buses}
                for f in self.fuentes}


def reset():
    """Vuelve api._gx/_mezclador/_controladores a None para que el próximo endpoint cree fakes
    nuevas."""
    GXFalso.instancias.clear()
    api._gx = None
    MixerFalso.instancias.clear()
    api._mezclador = None
    api._controladores.clear()
    api._cache_plugins.clear()
    for f in Path(_DIR_SETLISTS_TEST).glob("*.json"):
        f.unlink()


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
check("todos los buses mono por default", all(m == "mono" for m in cuerpo["modo_bus"].values()),
      f"-> {cuerpo['modo_bus']}")
check("ganancia 1.0 y paneo 0.0 por default para todos", all(
    celda == {"ganancia": 1.0, "paneo": 0.0}
    for fila in cuerpo["matriz"].values() for celda in fila.values()), f"-> {cuerpo['matriz']}")

r = client.post("/mezclador/ganancia", json={"fuente": api.FUENTES_MIXER[0],
                                              "bus": api.BUSES_MIXER[-1], "valor": 0.3})
check("200", r.status_code == 200 and r.json() == {"ok": True})
check("se aplica en la instancia", MixerFalso.instancias[0].ganancias[api.FUENTES_MIXER[0]][api.BUSES_MIXER[-1]] == 0.3,
      f"-> {MixerFalso.instancias[0].ganancias}")

r = client.post("/mezclador/ganancia", json={"fuente": "no_existe", "bus": api.BUSES_MIXER[0], "valor": 1.0})
check("400 fuente desconocida", r.status_code == 400, f"-> {r.status_code} {r.text}")

print("\n11. /mezclador/paneo")
reset()
r = client.post("/mezclador/paneo", json={"fuente": api.FUENTES_MIXER[0],
                                           "bus": api.BUSES_MIXER[0], "valor": -0.7})
check("200", r.status_code == 200 and r.json() == {"ok": True})
check("se aplica en la instancia",
      MixerFalso.instancias[0].paneos[api.FUENTES_MIXER[0]][api.BUSES_MIXER[0]] == -0.7,
      f"-> {MixerFalso.instancias[0].paneos}")

r = client.post("/mezclador/paneo", json={"fuente": api.FUENTES_MIXER[0],
                                           "bus": api.BUSES_MIXER[0], "valor": 5.0})
check("se recorta a 1.0 fuera de rango",
      MixerFalso.instancias[0].paneos[api.FUENTES_MIXER[0]][api.BUSES_MIXER[0]] == 1.0,
      f"-> {MixerFalso.instancias[0].paneos}")

r = client.post("/mezclador/paneo", json={"fuente": "no_existe", "bus": api.BUSES_MIXER[0], "valor": 0.0})
check("400 fuente desconocida", r.status_code == 400, f"-> {r.status_code} {r.text}")

print("\n12. Mezclador sin JACK disponible -> 503")
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

print("\n13. /app/ sirve la PWA de control remoto (mobile/)")
# Verificado a mano con un navegador real (Playwright) que la app entera funciona -- esto solo
# es la red de seguridad para que una regresion futura en el montaje no pase desapercibida.
r = client.get("/app/")
check("200", r.status_code == 200, f"-> {r.status_code}")
check("es html", "text/html" in r.headers.get("content-type", ""), f"-> {r.headers}")
check("es el index de la PWA", "<title>Arquitec DSP</title>" in r.text, f"-> {r.text[:80]}")
r = client.get("/app/app.js")
check("app.js 200", r.status_code == 200, f"-> {r.status_code}")
r = client.get("/app/manifest.json")
check("manifest.json 200 y valido", r.status_code == 200 and r.json().get("name"), f"-> {r.status_code}")

print("\n14. GET /lineas y /lineas/{linea}/estado")
reset()
r = client.get("/lineas")
check("devuelve los nombres configurados", r.json() == api.FUENTES_MIXER, f"-> {r.json()}")

r = client.get("/lineas/guitarra1/estado")
check("200", r.status_code == 200, f"-> {r.status_code} {r.text}")
cuerpo = r.json()
check("trae preset/modo/stomps/escenas de la setlist de ejemplo real",
      cuerpo["preset"] == "Clean Verso" and cuerpo["modo"] == "preset"
      and len(cuerpo["stomps"]) == 2 and cuerpo["escenas"] == ["Estrofa", "Estribillo"],
      f"-> {cuerpo}")

r = client.get("/lineas/no_existe/estado")
check("404 linea desconocida", r.status_code == 404, f"-> {r.status_code} {r.text}")

print("\n15. POST /lineas/{linea}/accion")
reset()
r = client.post("/lineas/guitarra1/accion", json={"accion": "escena", "parametro": 1})
check("200 y cambia de escena", r.status_code == 200 and r.json()["escena_activa"] == "Estribillo",
      f"-> {r.status_code} {r.json() if r.status_code == 200 else r.text}")

r = client.get("/lineas/guitarra2/estado")
check("otra linea queda independiente (sin escena activa)",
      r.json()["escena_activa"] is None, f"-> {r.json()}")

r = client.post("/lineas/guitarra1/accion", json={"accion": "toggle_stomp", "parametro": 0})
check("toggle_stomp prende el primer stomp",
      r.status_code == 200 and r.json()["stomps"][0]["activo"] is True, f"-> {r.text}")

r = client.post("/lineas/guitarra1/accion", json={"accion": "tap_tempo"})
check("accion sin parametro obligatorio (tap_tempo) no rompe", r.status_code == 200, f"-> {r.text}")

r = client.post("/lineas/guitarra1/accion", json={"accion": "volar"})
check("400 accion desconocida (no 500)", r.status_code == 400, f"-> {r.status_code} {r.text}")

r = client.post("/lineas/guitarra1/accion", json={"accion": "cambiar_preset"})
check("400 sin el parametro que la accion necesita (no 500)",
      r.status_code == 400 and "índice" in r.json()["detail"], f"-> {r.status_code} {r.text}")

print("\n16. GET /lineas/{linea}/cadena y /unidad/{unidad} (editor de nodos)")
reset()
r = client.get("/lineas/guitarra1/cadena")
check("200 y la cadena real", r.status_code == 200 and r.json() == ["ampstack", "freeverb"],
      f"-> {r.status_code} {r.json() if r.status_code == 200 else r.text}")

r = client.get("/lineas/guitarra1/unidad/ampstack")
check("200", r.status_code == 200, f"-> {r.status_code} {r.text}")
cuerpo = r.json()
nombres_param = [p["nombre"] for p in cuerpo["parametros"]]
check("filtra 'position' (type int, no renderizable)",
      "ampstack.position" not in nombres_param, f"-> {nombres_param}")
check("incluye el bool on_off y el float Pregain",
      "ampstack.on_off" in nombres_param and "amp2.stage1.Pregain" in nombres_param,
      f"-> {nombres_param}")
pregain = next(p for p in cuerpo["parametros"] if p["nombre"] == "amp2.stage1.Pregain")
check("trae min/max/valor del float", (pregain["min"], pregain["max"], pregain["valor"]) == (-20, 20, -6),
      f"-> {pregain}")

r = client.get("/lineas/guitarra1/unidad/no_existe")
check("404 unidad sin parametros", r.status_code == 404, f"-> {r.status_code} {r.text}")

print("\n17. GET/POST /lineas/{linea}/parametros")
reset()
r = client.get("/lineas/guitarra1/parametros", params={"nombres": "amp.gain, eq.peak1"})
check("200 junta por coma", r.status_code == 200 and r.json() == {"amp.gain": 1.0, "eq.peak1": 1.0},
      f"-> {r.status_code} {r.json() if r.status_code == 200 else r.text}")
r = client.get("/lineas/guitarra1/parametros", params={"nombres": ""})
check("400 nombres vacio", r.status_code == 400, f"-> {r.status_code}")

r = client.post("/lineas/guitarra1/parametros", json={"pares": {"amp.gain": 0.8}})
check("200 y llega al motor de ESA linea", r.status_code == 200 and
      GXFalso.instancias[0].llamadas == [("set", "amp.gain", 0.8)], f"-> {GXFalso.instancias[0].llamadas}")

print("\n18. Reconexion automatica: GuitarixError -> 502, ConnectionError -> 503 (no 500)")
reset()
r = client.get("/estado")  # instancia la fake
api._gx.falla_version = api.GuitarixError(-32601, "Method not found")
r = client.get("/estado")
check("502 con GuitarixError", r.status_code == 502 and "Method not found" in r.text,
      f"-> {r.status_code} {r.text}")

reset()
r = client.get("/estado")
api._gx.falla_version = None
api._gx.falla_conexion = True
r = client.get("/estado")
check("503 con ConnectionError (no 500)", r.status_code == 503 and "perdió la conexión" in r.text,
      f"-> {r.status_code} {r.text}")

print("\n19. /lineas/{linea}/estado trae lo que necesitan PRESETS y GIG")
reset()
r = client.get("/lineas/guitarra1/estado")
e = r.json()
check("presets del banco visible", e["presets_banco_visible"] == ["Clean Verso", "Crunch", "Lead"],
      f"-> {e.get('presets_banco_visible')}")
check("nombre del banco y total", (e["banco_visible_nombre"], e["total_bancos"]) == ("Set 1", 2),
      f"-> {e.get('banco_visible_nombre')}, {e.get('total_bancos')}")
check("stomps con categoria de interfaz", [s["categoria"] for s in e["stomps"]] == ["modulation", "delay"],
      f"-> {e['stomps']}")
check("stomps marcan si estan en el rack", [s["en_cadena"] for s in e["stomps"]] == [False, False],
      f"-> {e['stomps']}")
check("la setlist de trabajo se creo copiando el ejemplo, fuera del repo",
      (Path(_DIR_SETLISTS_TEST) / "guitarra1.json").exists())

print("\n20. GET /lineas/{linea}/grid: dos filas reales, con nombre/categoria/on-off")
reset()
r = client.get("/lineas/guitarra1/grid")
filas = r.json()["filas"]
check("fila mono y estereo", [f["cadena"] for f in filas] == ["mono", "estereo"], f"-> {filas}")
check("bloques de la fila mono con nombre legible y categoria",
      [(u["id"], u["nombre"], u["categoria"]) for u in filas[0]["unidades"]]
      == [("ampstack", "Amp", "amp"), ("freeverb", "Freeverb", "reverb")], f"-> {filas[0]}")
check("estado on/off", all(u["encendido"] is True for u in filas[0]["unidades"]))
check("ampstack marcado fijo, freeverb no",
      [u["fijo"] for u in filas[0]["unidades"]] == [True, False], f"-> {filas[0]}")

print("\n21. GET /lineas/{linea}/plugins: agrupado por categoria, sin variantes internas")
r = client.get("/lineas/guitarra1/plugins")
cats = r.json()["categorias"]
ids = [p["id"] for c in cats for p in c["plugins"]]
check("orden de la leyenda y solo categorias con modelos",
      [c["id"] for c in cats] == ["overdrive", "modulation", "delay", "reverb"],
      f"-> {[c['id'] for c in cats]}")
check("12AX7 (variante interna) no aparece", "12AX7" not in ids, f"-> {ids}")
check("bloques fijos (ampstack, noise_gate) no aparecen: insertarlos tumba al motor",
      not {"ampstack", "noise_gate"} & set(ids), f"-> {ids}")
check("marca los que ya estan en el rack",
      {p["id"]: p["en_cadena"] for c in cats for p in c["plugins"]}["freeverb"] is True)

print("\n22. Insertar / quitar bloques")
reset()
r = client.post("/lineas/guitarra1/grid/insertar", json={"unidad": "ts9sim", "estereo": False})
check("200 y queda al final de la fila mono",
      r.status_code == 200 and [u["id"] for u in r.json()["filas"][0]["unidades"]][-1] == "ts9sim",
      f"-> {r.status_code} {r.text[:200]}")
fake = api._linea("guitarra1").rpc
check("queda encendido", ("set", "ts9sim.on_off", 1) in fake.llamadas, f"-> {fake.llamadas}")
r = client.post("/lineas/guitarra1/grid/insertar", json={"unidad": "ts9sim", "estereo": False})
check("409 si ya esta en el rack", r.status_code == 409, f"-> {r.status_code}")
r = client.post("/lineas/guitarra1/grid/insertar", json={"unidad": "chorus", "estereo": False})
check("400 si va en la fila equivocada (chorus es estereo)", r.status_code == 400, f"-> {r.status_code} {r.text}")
r = client.post("/lineas/guitarra1/grid/insertar", json={"unidad": "12AX7", "estereo": False})
check("404 si no es un bloque insertable", r.status_code == 404, f"-> {r.status_code}")
r = client.post("/lineas/guitarra1/grid/insertar", json={"unidad": "chorus", "estereo": True})
check("estereo va a la segunda fila", [u["id"] for u in r.json()["filas"][1]["unidades"]] == ["chorus"],
      f"-> {r.json()}")
r = client.post("/lineas/guitarra1/grid/quitar", json={"unidad": "ts9sim", "estereo": False})
check("quitar", "ts9sim" not in [u["id"] for u in r.json()["filas"][0]["unidades"]], f"-> {r.json()}")
r = client.post("/lineas/guitarra1/grid/quitar", json={"unidad": "ts9sim", "estereo": False})
check("404 al quitar algo que no esta", r.status_code == 404, f"-> {r.status_code}")
fake.llamadas.clear()
r = client.post("/lineas/guitarra1/grid/quitar", json={"unidad": "ampstack", "estereo": False})
check("400 al quitar ampstack (segfault en el motor real)", r.status_code == 400, f"-> {r.status_code}")
check("...y no llega a mandarse al motor",
      not any(c[0] in ("remove", "remove_rack_unit") for c in fake.llamadas), f"-> {fake.llamadas}")
r = client.post("/lineas/guitarra1/grid/insertar", json={"unidad": "noise_gate", "estereo": False})
check("404 al insertar un bloque fijo", r.status_code == 404, f"-> {r.status_code}")

print("\n23. Guardar (💾) escribe la cadena y los valores en la setlist de trabajo")
reset()
client.post("/lineas/guitarra1/grid/insertar", json={"unidad": "ts9sim", "estereo": False})
r = client.post("/lineas/guitarra1/guardar")
check("200", r.status_code == 200, f"-> {r.status_code} {r.text[:200]}")
guardado = json.loads((Path(_DIR_SETLISTS_TEST) / "guitarra1.json").read_text(encoding="utf-8"))
preset0 = guardado["bancos"][0]["presets"][0]
check("cadena guardada en disco", preset0.get("cadena") == {"mono": ["ampstack", "freeverb", "ts9sim"],
                                                           "estereo": []}, f"-> {preset0.get('cadena')}")
check("valores capturados (no 'position')",
      "amp2.stage1.Pregain" in preset0["parametros"] and "ampstack.position" not in preset0["parametros"],
      f"-> {preset0['parametros']}")
ejemplo = json.loads(api._RUTA_SETLIST_EJEMPLO.read_text(encoding="utf-8"))
check("la setlist de ejemplo del repo NO se toco", "cadena" not in ejemplo["bancos"][0]["presets"][0])

print("\n24. + New scene: crea 'Scene C' (el preset ya tiene A y B) y la guarda")
reset()
r = client.post("/lineas/guitarra1/escenas")
check("200 y queda activa", r.status_code == 200 and r.json()["escena_activa"] == "Scene C",
      f"-> {r.status_code} {r.text[:200]}")
check("aparece en la lista", r.json()["escenas"] == ["Estrofa", "Estribillo", "Scene C"])
guardado = json.loads((Path(_DIR_SETLISTS_TEST) / "guitarra1.json").read_text(encoding="utf-8"))
check("persistida en disco", [e["nombre"] for e in guardado["bancos"][0]["presets"][0]["escenas"]][-1]
      == "Scene C")
for _ in range(5):
    client.post("/lineas/guitarra1/escenas")
r = client.post("/lineas/guitarra1/escenas")
check("400 al pasar de 8 (A-H)", r.status_code == 400, f"-> {r.status_code} {r.text}")

print("\n" + ("FALLARON: " + ", ".join(fallos) if fallos else "TODO OK"))
sys.exit(1 if fallos else 0)
