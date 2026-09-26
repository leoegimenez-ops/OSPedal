"""Pruebas de líneas paralelas: MotorLinea (reparte parámetros por tramo) y GestorLineas (mueve
bloques entre motores, SPLIT/MERGE, reglas mono/estéreo, guardar/cargar).

Motores falsos por tramo que modelan el rack de verdad (mover = insert sobre una unidad presente,
el Amp tumba al motor si se lo inserta o quita). Se ejecuta: python -m engine.test_lineas
"""
import sys

from engine.disposicion import MERGE, SPLIT, ErrorDisposicion, GestorLineas
from engine.motor_linea import MotorLinea, separar
from engine.rpc_client import GuitarixRPC
from engine.ruteo import PARAMETROS as PARAMETROS_RUTEO

fallos = []


def check(nombre, ok, detalle=""):
    print(f"  {'OK  ' if ok else 'FALLA'}  {nombre}{'  ' + detalle if detalle else ''}")
    if not ok:
        fallos.append(nombre)


PLUGINS = [
    {"id": "ampstack", "flags": 0x20104}, {"id": "ts9sim", "flags": 0x10108},
    {"id": "echo", "flags": 0x10108}, {"id": "comp", "flags": 0x10108},
    {"id": "freeverb", "flags": 0x10109}, {"id": "chorus", "flags": 0x10109},
]


class Tumbado(Exception):
    pass


class MotorFalso:
    def __init__(self, nombre):
        self.nombre = nombre
        self.rack = {0: ["ampstack"], 1: []}
        self.valores = {"ampstack.on_off": 1, "ampstack.gain": 0.5}

    def plugins(self):
        return PLUGINS

    def orden_rack(self, c=0):
        return list(self.rack[c])

    def insertar_unidad(self, u, antes="", est=False):
        if u == "ampstack":
            raise Tumbado(f"{self.nombre}: insert ampstack")
        fila = self.rack[int(est)]
        if u in fila:
            fila.remove(u)
        else:
            self.valores.setdefault(f"{u}.on_off", 0)
            self.valores.setdefault(f"{u}.nivel", 0.5)
        fila.insert(fila.index(antes) if antes in fila else len(fila), u)

    def quitar_unidad(self, u, est=False):
        if u == "ampstack":
            raise Tumbado(f"{self.nombre}: remove ampstack")
        self.rack[int(est)].remove(u)

    renumerar = GuitarixRPC.renumerar

    def fijar(self, *pares):
        self.valores.update(zip(pares[::2], pares[1::2]))

    def obtener(self, *nombres):
        return {n: self.valores.get(n) for n in nombres}

    def consultar_unidad(self, u):
        if u not in self.rack[0] + self.rack[1]:
            return {}
        return {n: {"type": "bool" if n.endswith("on_off") else ("int" if n.endswith((".position", ".pp")) else "float"),
                    "value": {n: v}}
                for n, v in self.valores.items() if n.split(".")[0] == u}

    def cerrar(self):
        pass


def armar():
    motores = {"pre": MotorFalso("pre")}
    ruteo = {n: 0.0 for n in PARAMETROS_RUTEO}      # el SPLIT/MERGE real siempre informa sus valores
    rutas = []

    def abrir(t):
        motores[t] = MotorFalso(t)
        return motores[t]

    ml = MotorLinea(motores["pre"], abrir, lambda n, v: ruteo.__setitem__(n, v),
                    lambda: dict(ruteo))
    g = GestorLineas(ml, lambda s, p: rutas.append((s, p)))
    return motores, ruteo, rutas, ml, g


print("\n1. MotorLinea reparte por tramo")
motores, ruteo, rutas, ml, g = armar()
ml.fijar("ampstack.gain", 0.7, "a/ampstack.gain", 0.2, "merge.nivel_b", 0.5)
check("pre", motores["pre"].valores["ampstack.gain"] == 0.7)
check("a (arranca su motor al primer uso)", motores["a"].valores["ampstack.gain"] == 0.2)
check("ruteo", ruteo["merge.nivel_b"] == 0.5)
check("obtener califica los nombres",
      ml.obtener("a/ampstack.gain", "ampstack.gain", "merge.nivel_b")
      == {"a/ampstack.gain": 0.2, "ampstack.gain": 0.7, "merge.nivel_b": 0.5})
check("separar", separar("post/echo.bpm") == ("post", "echo.bpm") and separar("x/y.z") == ("pre", "x/y.z"))

print("\n2. Sin paralelo: todo en el tramo principal")
motores, ruteo, rutas, ml, g = armar()
g.insertar("ts9sim", "pre")
g.insertar("echo", "pre")
check("fila principal", g.disposicion()["principal"] == ["ampstack", "ts9sim", "echo"],
      f"-> {g.disposicion()}")

print("\n3. Crear la linea paralela arrastrando el punto: SPLIT despues del Amp")
motores["pre"].valores["ts9sim.nivel"] = 0.3
avisos = g.disponer(["ampstack", SPLIT, "ts9sim", MERGE, "echo"], [])
d = g.disposicion()
check("disposicion", d["principal"] == ["ampstack", SPLIT, "a/ts9sim", MERGE, "post/echo"] and d["paralela"] == [],
      f"-> {d}")
check("ts9 se mudo al motor A con sus ajustes", "ts9sim" in motores["a"].rack[0]
      and motores["a"].valores["ts9sim.nivel"] == 0.3 and "ts9sim" not in motores["pre"].rack[0])
check("los tramos nuevos arrancan con el Amp oculto y bypaseado",
      motores["b"].valores["ampstack.on_off"] == 0 and "ampstack" not in g.unidades("b"))
check("aviso de ruta: split con post", rutas[-1] == (True, True), f"-> {rutas}")

print("\n4. Mover el Amp a la linea B (el Amp nunca se inserta ni quita: se oculta/muestra)")
motores["pre"].valores["ampstack.gain"] = 0.9
g.disponer([SPLIT, "a/ts9sim", MERGE, "post/echo"], ["ampstack"])
check("B muestra el Amp con los ajustes que tenia", g.unidades("b") == ["ampstack"]
      and motores["b"].valores["ampstack.gain"] == 0.9 and motores["b"].valores["ampstack.on_off"] == 1)
check("el principal ya no lo muestra y queda bypaseado",
      g.unidades("pre") == [] and motores["pre"].valores["ampstack.on_off"] == 0)

print("\n5. Reglas del motor (el Amp ahora es de B: su id es 'b/ampstack')")
g.insertar("freeverb", "b")
g.insertar("comp", "b")
check("en B el estereo queda despues del mono al insertar", g.unidades("b") == ["ampstack", "comp", "freeverb"],
      f"-> {g.unidades('b')}")
avisos = g.disponer([SPLIT, "a/ts9sim", MERGE, "post/echo"], ["b/freeverb", "b/ampstack", "b/comp"])
check("arrastrar un estereo antes que un mono: se reordena solo y avisa",
      g.unidades("b") == ["ampstack", "comp", "freeverb"] and avisos, f"-> {g.unidades('b')} {avisos}")
try:
    g.disponer(["b/freeverb", SPLIT, "a/ts9sim", MERGE, "post/echo"], ["b/ampstack", "b/comp"])
    check("antes del SPLIT no va nada estereo", False)
except ErrorDisposicion as e:
    check("antes del SPLIT no va nada estereo", "mono" in str(e), f"-> {e}")
try:
    g.insertar("freeverb", "pre")
    check("tampoco insertandolo", False)
except ErrorDisposicion:
    check("tampoco insertandolo", True)
g.insertar("ts9sim", "b")
try:
    g.disponer([SPLIT, "a/ts9sim", "b/ts9sim", MERGE, "post/echo"], ["b/ampstack", "b/comp", "b/freeverb"])
    check("el mismo modelo una vez por tramo", False)
except ErrorDisposicion as e:
    check("el mismo modelo una vez por tramo", "once" in str(e), f"-> {e}")
try:
    g.disponer([SPLIT, "a/ts9sim", MERGE], ["b/ampstack"])
    check("no se pueden 'perder' bloques al disponer", False)
except ErrorDisposicion:
    check("no se pueden 'perder' bloques al disponer", True)
check("mover el MERGE: echo pasa de post a la linea A",
      not g.disponer([SPLIT, "a/ts9sim", "post/echo", MERGE], ["b/ampstack", "b/comp", "b/ts9sim", "b/freeverb"])
      and g.unidades("a") == ["ts9sim", "echo"] and g.unidades("post") == [] and rutas[-1] == (True, False),
      f"-> a={g.unidades('a')} post={g.unidades('post')} ruta={rutas[-1]}")

print("\n6. Guardar y cargar la disposicion con el preset")
datos = g.exportar()
extra = g.capturar_extra()
check("exporta tramos y visibilidad del Amp",
      datos["split"] and datos["tramos"]["b"] == ["ampstack", "comp", "ts9sim", "freeverb"] and datos["amp"]["pre"] is False,
      f"-> {datos}")
check("capturar_extra trae parametros calificados y del ruteo",
      "b/ampstack.gain" in extra and "a/echo.nivel" in extra and "merge.nivel_a" in extra, f"-> {sorted(extra)[:8]}")
motores2, ruteo2, rutas2, ml2, g2 = armar()
g2.cargar(datos)
ml2.fijar(*[x for par in extra.items() if par[1] is not None for x in par])
check("en un equipo limpio queda igual",
      g2.disposicion()["principal"] == g.disposicion()["principal"]
      and g2.disposicion()["paralela"] == g.disposicion()["paralela"], f"-> {g2.disposicion()}")
check("con los mismos ajustes", motores2["b"].valores.get("ampstack.gain") == 0.9)
g2.cargar(None)
check("cargar un preset sin paralelo lo deshace", g2.disposicion() == {"split": False, "tramos": {"pre": ["ampstack"]},
                                                                      "principal": ["ampstack"], "paralela": []},
      f"-> {g2.disposicion()}")

print("\n7. Quitar la linea paralela")
g.quitar_linea()
check("A y post vuelven al principal, B se va", g.disposicion()["principal"] == ["ts9sim", "echo"]
      and not g.split and rutas[-1] == (False, False), f"-> {g.disposicion()}")
check("el Amp del principal sigue oculto (se habia movido a B)", "ampstack" not in g.unidades("pre"))
g.insertar("ampstack", "pre")
check("agregar el Amp = mostrarlo (al final, como todo '+') y prenderlo",
      g.unidades("pre") == ["ts9sim", "echo", "ampstack"] and motores["pre"].valores["ampstack.on_off"] == 1,
      f"-> {g.unidades('pre')}")
g.quitar("ampstack")
check("quitar el Amp = ocultarlo y bypasearlo (no tumba al motor)",
      "ampstack" not in g.unidades("pre") and motores["pre"].valores["ampstack.on_off"] == 0)

print("\n" + ("FALLARON: " + ", ".join(fallos) if fallos else "TODO OK"))
sys.exit(1 if fallos else 0)
