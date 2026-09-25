"""Pruebas del backend del GRID: categorías de efecto, captura del estado del motor, guardar en
preset, crear escenas y sincronizar la cadena del rack al cargar un preset.

Usa un motor falso que modela el rack de verdad (dos cadenas, insert/remove, queryunit) en vez
de solo registrar llamadas -- así se prueba el resultado (qué queda en el rack), no solo que se
mandó algo. Se ejecuta como módulo: python -m engine.test_grid
"""
import json
import sys
import tempfile
from pathlib import Path

from engine.categorias import CLAVES, categoria, fijos, insertables
from engine.controlador import ControladorEscenario
from engine.midi_engine import Accion
from presets.preset_manager import Banco, Escena, Preset, Setlist

fallos = []


def check(nombre, ok, detalle=""):
    print(f"  {'OK  ' if ok else 'FALLA'}  {nombre}{'  ' + detalle if detalle else ''}")
    if not ok:
        fallos.append(nombre)


class MotorTumbado(Exception):
    """Lo que en el motor real es un segfault."""


# Flags reales de Guitarix 0.47.0 (pluginlist, 25/09/2026).
PLUGINS_FALSOS = [
    {"id": "ampstack", "flags": 0x20104, "name": "Amp", "category": ""},
    {"id": "amp", "flags": 0x90C, "name": "Amplifier", "category": ""},
    {"id": "noise_gate", "flags": 0x2094A, "name": "Noise Gate", "category": "NONE"},
    {"id": "ts9sim", "flags": 0x10108, "name": "Tube Screamer", "category": "Distortion"},
    {"id": "echo", "flags": 0x10108, "name": "Echo", "category": "Echo / Delay"},
    {"id": "freeverb", "flags": 0x10109, "name": "Freeverb", "category": "Reverb"},
]


class MotorFalso:
    """Rack con dos cadenas y valores de parámetro, como el de Guitarix. Insertar o quitar un
    bloque fijo lanza MotorTumbado: en el motor real es un segfault (ver engine/categorias.py)."""

    FIJOS = {"ampstack", "amp", "noise_gate"}

    def __init__(self):
        self.rack = {0: ["ampstack"], 1: []}
        self.valores = {
            "ampstack.on_off": 1, "amp2.stage1.Pregain": -6.0, "ampstack.position": 3,
            "ts9sim.on_off": 0, "ts9sim.drive": 0.5,
            "freeverb.on_off": 0, "freeverb.RoomSize": 0.5,
        }
        self.tipos = {"on_off": "bool", "position": "int"}
        self.llamadas = []

    def orden_rack(self, cadena=0):
        return list(self.rack[cadena])

    def plugins(self):
        return [dict(p) for p in PLUGINS_FALSOS]

    def insertar_unidad(self, unidad, antes_de="", estereo=False):
        self.llamadas.append(("insert", unidad, int(estereo)))
        if unidad in self.FIJOS:
            raise MotorTumbado(f"insert {unidad}")
        fila = self.rack[int(estereo)]
        fila.insert(fila.index(antes_de) if antes_de in fila else len(fila), unidad)

    def quitar_unidad(self, unidad, estereo=False):
        self.llamadas.append(("remove", unidad, int(estereo)))
        if unidad in self.FIJOS:
            raise MotorTumbado(f"remove {unidad}")
        self.rack[int(estereo)].remove(unidad)
        self.valores[f"{unidad}.on_off"] = 0

    def consultar_unidad(self, unidad):
        salida = {}
        for nombre, valor in self.valores.items():
            dueno = "ampstack" if nombre.startswith("amp2.") else nombre.split(".")[0]
            if dueno != unidad:
                continue
            tipo = self.tipos.get(nombre.split(".")[-1], "float")
            salida[nombre] = {"type": tipo, "value": {nombre: valor}}
        return salida

    def set_preset(self, b, p):
        self.llamadas.append(("setpreset", b, p))

    def fijar(self, *pares):
        self.llamadas.append(("set",) + pares)
        for nombre, valor in zip(pares[::2], pares[1::2]):
            self.valores[nombre] = valor

    def notificar(self, metodo, *params):
        self.llamadas.append((metodo,) + params)


print("\n1. Categorias: los plugins reales del motor caen en la leyenda de referencia")
check("ts9sim -> overdrive", categoria("ts9sim", "Distortion") == "overdrive")
check("muff (Fuzz) -> overdrive", categoria("muff", "Fuzz") == "overdrive")
check("echo -> delay", categoria("echo", "Echo / Delay") == "delay")
check("cab (Tone Control) -> cab, no eq", categoria("cab", "Tone Control") == "cab")
check("eq (Tone Control) -> eq", categoria("eq", "Tone Control") == "eq")
check("jconv (Reverb) -> IR loader", categoria("jconv", "Reverb") == "ir")
check("crybaby (Guitar Effects) -> wah", categoria("crybaby", "Guitar Effects") == "wah")
check("compressor (Guitar Effects) -> compressor", categoria("compressor", "Guitar Effects") == "compressor")
check("nam -> neural", categoria("nam", "Neural") == "neural")
check("desconocido -> utility", categoria("xyz", None) == "utility")
check("toda categoria devuelta existe en la leyenda",
      all(categoria(u, c) in CLAVES for u, c in
          [("ts9sim", "Distortion"), ("vu", "Misc"), ("noise_gate", "NONE"), ("zzz", "")]))

print("\n2. insertables(): filtra variantes internas y bloques fijos, marca estereo")
crudo = [
    {"id": "12AX7", "flags": 0x128, "name": "12AX7", "category": ""},          # alternativo
    {"id": "ts9sim", "flags": 0x10108, "name": "Tube Screamer", "category": "Distortion"},
    {"id": "chorus", "flags": 0x109, "name": "Chorus", "category": "Modulation"},
] + [p for p in PLUGINS_FALSOS if p["id"] in MotorFalso.FIJOS] + [
    {"id": "amp.clip", "flags": 0x90C, "name": "Clip", "category": ""},
    {"id": "shaper", "flags": 0x90A, "name": "Shaper", "category": ""},
]
ins = {p["id"]: p for p in insertables(crudo)}
check("12AX7 (PGN_ALTERNATIVE) no es insertable", "12AX7" not in ins, f"-> {list(ins)}")
check("ningun bloque fijo es insertable (tumban al motor)",
      not {"ampstack", "amp", "noise_gate", "amp.clip", "shaper"} & set(ins), f"-> {list(ins)}")
check("fijos() los detecta por flags",
      fijos(crudo) == {"ampstack", "amp", "noise_gate", "amp.clip", "shaper"}, f"-> {sorted(fijos(crudo))}")
check("chorus marcado estereo", ins["chorus"]["estereo"] is True)
check("ts9sim mono y con nombre legible",
      ins["ts9sim"]["estereo"] is False and ins["ts9sim"]["nombre"] == "Tube Screamer")

print("\n3. capturar(): cadena real + solo float/bool (sin 'position')")
motor = MotorFalso()
motor.rack[0] = ["ampstack", "ts9sim"]
motor.rack[1] = ["freeverb"]
setlist = Setlist(nombre="T", bancos=[Banco("A", [Preset("Uno"), Preset("Dos")])])
ctrl = ControladorEscenario(setlist, motor)
cadena, params = ctrl.capturar()
check("cadena mono y estereo", cadena == {"mono": ["ampstack", "ts9sim"], "estereo": ["freeverb"]},
      f"-> {cadena}")
check("no guarda 'position'", "ampstack.position" not in params, f"-> {sorted(params)}")
check("bool guardado como bool", params.get("ampstack.on_off") is True, f"-> {params.get('ampstack.on_off')!r}")
check("float guardado", params.get("ts9sim.drive") == 0.5)

print("\n4. guardar_en_preset(): el preset queda con la cadena y los valores reales")
ctrl.guardar_en_preset()
check("preset.cadena", setlist.preset(0, 0).cadena == cadena)
check("preset.parametros", setlist.preset(0, 0).parametros.get("ts9sim.drive") == 0.5)
with tempfile.TemporaryDirectory() as tmp:
    ruta = Path(tmp) / "s.json"
    setlist.guardar(ruta)
    recargada = Setlist.cargar(ruta)
    check("la cadena sobrevive a disco", recargada.preset(0, 0).cadena == cadena,
          f"-> {recargada.preset(0, 0).cadena}")
    check("json con 'cadena'", "cadena" in json.loads(ruta.read_text(encoding="utf-8"))
          ["bancos"][0]["presets"][0])

print("\n5. Cargar un preset con cadena guardada reconstruye el rack")
motor.rack[0] = ["ampstack"]           # alguien saco bloques a mano
motor.rack[1] = []
motor.llamadas.clear()
ctrl.ejecutar(Accion.CAMBIAR_PRESET, 1)
ctrl.ejecutar(Accion.CAMBIAR_PRESET, 0)
check("rack mono reconstruido en orden", motor.rack[0] == ["ampstack", "ts9sim"], f"-> {motor.rack[0]}")
check("rack estereo reconstruido", motor.rack[1] == ["freeverb"], f"-> {motor.rack[1]}")
check("ampstack nunca se quito ni se inserto",
      not any(c[0] in ("insert", "remove") and c[1] == "ampstack" for c in motor.llamadas),
      f"-> {motor.llamadas}")

print("\n5b. Bloques guardados ANTES del ampstack vuelven a quedar antes")
setlist.preset(0, 1).cadena = {"mono": ["ts9sim", "ampstack", "echo"], "estereo": []}
ctrl.ejecutar(Accion.CAMBIAR_PRESET, 1)
check("orden con ampstack en el medio", motor.rack[0] == ["ts9sim", "ampstack", "echo"],
      f"-> {motor.rack[0]}")
check("estereo vaciado", motor.rack[1] == [], f"-> {motor.rack[1]}")
setlist.preset(0, 1).cadena = None
ctrl.ejecutar(Accion.CAMBIAR_PRESET, 0)
check("y de vuelta al preset 1", motor.rack[0] == ["ampstack", "ts9sim"], f"-> {motor.rack[0]}")

print("\n6. Si la cadena ya coincide, no se toca el rack")
motor.llamadas.clear()
ctrl.ejecutar(Accion.CAMBIAR_PRESET, 0)
check("ningun insert/remove", not any(c[0] in ("insert", "remove") for c in motor.llamadas),
      f"-> {motor.llamadas}")

print("\n7. Preset sin cadena (setlists viejas) no toca el rack")
motor.llamadas.clear()
ctrl.ejecutar(Accion.CAMBIAR_PRESET, 1)
check("ningun insert/remove", not any(c[0] in ("insert", "remove") for c in motor.llamadas),
      f"-> {motor.llamadas}")

print("\n8. nueva_escena(): nombre automatico por letra, queda activa, tope A-H")
ctrl.ejecutar(Accion.CAMBIAR_PRESET, 0)
nombre = ctrl.nueva_escena()
check("'Scene A'", nombre == "Scene A" and ctrl.escena_activa == "Scene A", f"-> {nombre}")
check("guarda el estado actual", setlist.preset(0, 0).escenas[0].parametros.get("ts9sim.drive") == 0.5)
ctrl.nueva_escena()
check("la segunda es 'Scene B'", setlist.preset(0, 0).escenas[1].nombre == "Scene B")
for _ in range(6):
    ctrl.nueva_escena()
try:
    ctrl.nueva_escena()
    check("novena escena rechazada", False)
except ValueError as e:
    check("novena escena rechazada", "8" in str(e), f"-> {e}")

print("\n9. Validacion: cadena mal formada da error con la ruta del campo")
for datos, frag in [
    ({"nombre": "X", "cadena": {"lateral": []}}, "cadena.lateral"),
    ({"nombre": "X", "cadena": {"mono": ["", "a"]}}, "cadena.mono"),
    ({"nombre": "X", "escenas": [{"nombre": f"E{i}"} for i in range(9)]}, "escenas"),
]:
    try:
        Preset.desde_dict(datos, "p")
        check(f"rechaza {frag}", False)
    except ValueError as e:
        check(f"rechaza {frag}", frag in str(e), f"-> {e}")

print("\n" + ("FALLARON: " + ", ".join(fallos) if fallos else "TODO OK"))
sys.exit(1 if fallos else 0)
