"""Pruebas del gestor de setlists.

Se ejecuta como modulo (python -m presets.test_preset_manager) para que el
import relativo funcione igual en Windows y en Linux/WSL2.
"""
import json
import sys
import tempfile
from pathlib import Path

from presets.preset_manager import (
    Banco, ErrorDeSetlist, Preset, Setlist, Stomp,
    MAX_BANCOS, MAX_PRESETS, PRESETS_POR_BANCO, aplicar,
)

RAIZ = Path(__file__).resolve().parent.parent

fallos = []


def check(nombre, ok, detalle=""):
    print(f"  {'OK  ' if ok else 'FALLA'}  {nombre}{'  ' + detalle if detalle else ''}")
    if not ok:
        fallos.append(nombre)


def espera_error(nombre, fn, fragmento_ruta):
    try:
        fn()
        check(nombre, False, "-> no lanzo error")
    except ErrorDeSetlist as e:
        ok = fragmento_ruta in str(e)
        check(nombre, ok, f"-> {e}")
    except Exception as e:
        check(nombre, False, f"-> error inesperado {type(e).__name__}: {e}")


class RPCFalso:
    """Registra lo que se le manda, para verificar el protocolo sin un motor real."""

    def __init__(self):
        self.llamadas = []

    def set_preset(self, banco, preset):
        self.llamadas.append(("setpreset", banco, preset))

    def fijar(self, *pares):
        if len(pares) % 2:
            raise ValueError("cantidad impar")
        self.llamadas.append(("set",) + pares)


print("\n1. Carga del ejemplo real del repo")
ruta_ejemplo = RAIZ / "presets" / "ejemplo-setlist.json"
sl = Setlist.cargar(ruta_ejemplo)
check("carga", sl.nombre == "Ejemplo")
check("bancos", len(sl.bancos) == 2, f"-> {[b.nombre for b in sl.bancos]}")
check("total presets", sl.total_presets == 4, f"-> {sl.total_presets}")

print("\n2. Navegacion")
check("preset(0,0)", sl.preset(0, 0).nombre == "Clean Verso")
check("preset(1,0)", sl.preset(1, 0).nombre == "Acústico")
# El indice plano salta de a 8: el banco 1 arranca en 8, no en 3.
check("indice_de(1,0)", sl.indice_de(1, 0) == 8, f"-> {sl.indice_de(1, 0)}")
check("preset_por_indice(8)", sl.preset_por_indice(8).nombre == "Acústico")
check("preset_por_indice(2)", sl.preset_por_indice(2).nombre == "Lead")
check("iteracion", [n for n, _, _ in sl] == [0, 1, 2, 8],
      f"-> {[n for n, _, _ in sl]}")

print("\n3. Rangos fuera de limite")
espera_error("banco inexistente", lambda: sl.preset(9, 0), "banco")
espera_error("preset inexistente", lambda: sl.preset(1, 5), "preset")
espera_error("indice 256", lambda: sl.preset_por_indice(MAX_PRESETS), "indice")
espera_error("indice negativo", lambda: sl.preset_por_indice(-1), "indice")
# Hueco: el banco 1 solo tiene 1 preset, el indice 9 cae en el vacio.
espera_error("indice en hueco", lambda: sl.preset_por_indice(9), "preset")

print("\n4. Pares RPC: parametros + stomps en una sola llamada")
p = sl.preset(0, 0)
pares = p.pares_rpc()
check("cantidad par", len(pares) % 2 == 0, f"-> {len(pares)} elementos")
d = dict(zip(pares[::2], pares[1::2]))
check("incluye parametros", d.get("amp.stage1.gain") == 0.35)
check("incluye stomp on", d.get("echo.on_off") == 1, f"-> {d.get('echo.on_off')!r}")
check("incluye stomp off", d.get("chorus.on_off") == 0, f"-> {d.get('chorus.on_off')!r}")
check("bool convertido a int",
      all(not isinstance(v, bool) for v in pares[1::2]),
      "-> ningun booleano crudo")

print("\n5. Escenas pisan al preset")
base = dict(zip(p.pares_rpc()[::2], p.pares_rpc()[1::2]))
estr = dict(zip(p.pares_rpc("Estribillo")[::2], p.pares_rpc("Estribillo")[1::2]))
check("preset base gain", base["amp.stage1.gain"] == 0.35)
check("escena pisa gain", estr["amp.stage1.gain"] == 0.55, f"-> {estr['amp.stage1.gain']}")
estrofa = dict(zip(p.pares_rpc("Estrofa")[::2], p.pares_rpc("Estrofa")[1::2]))
check("escena pisa stomp", estrofa["echo.on_off"] == 0, f"-> {estrofa['echo.on_off']!r}")

try:
    p.pares_rpc("NoExiste")
    check("escena inexistente", False)
except KeyError as e:
    check("escena inexistente", "Estribillo" in str(e), f"-> {e}")

print("\n6. Aplicar al motor")
rpc = RPCFalso()
aplicar(sl.preset(0, 0), rpc)
check("dos llamadas", len(rpc.llamadas) == 2, f"-> {len(rpc.llamadas)}")
check("primero setpreset", rpc.llamadas[0] == ("setpreset", "Factory", "Clean"),
      f"-> {rpc.llamadas[0]}")
check("despues un solo set", rpc.llamadas[1][0] == "set")

rpc2 = RPCFalso()
aplicar(sl.preset(0, 2), rpc2)   # "Lead" no tiene preset base de Guitarix
check("sin preset base: solo set", len(rpc2.llamadas) == 1 and rpc2.llamadas[0][0] == "set",
      f"-> {[c[0] for c in rpc2.llamadas]}")

print("\n7. Validacion rechaza datos malos")
def malo(mut):
    datos = json.loads(ruta_ejemplo.read_text(encoding="utf-8"))
    mut(datos)
    return lambda: Setlist.desde_dict(datos)

espera_error("version incorrecta", malo(lambda d: d.__setitem__("version", 99)), "version")
espera_error("sin nombre", malo(lambda d: d.__setitem__("nombre", "")), "nombre")
espera_error("33 bancos", malo(lambda d: d.__setitem__("bancos", d["bancos"] * 17)), "bancos")
espera_error("9 presets en banco",
             malo(lambda d: d["bancos"][0].__setitem__("presets", d["bancos"][0]["presets"] * 3)),
             "presets")
espera_error("tempo fuera de rango",
             malo(lambda d: d["bancos"][0]["presets"][0].__setitem__("tempo_bpm", 999)),
             "tempo_bpm")
espera_error("volumen fuera de rango",
             malo(lambda d: d["bancos"][0]["presets"][0].__setitem__("volumen", 5)),
             "volumen")
espera_error("parametro de tipo invalido",
             malo(lambda d: d["bancos"][0]["presets"][0]["parametros"].__setitem__("x", [1, 2])),
             "parametros.x")
espera_error("stomp sin unidad",
             malo(lambda d: d["bancos"][0]["presets"][0]["stomps"][0].__setitem__("unidad", "")),
             "stomps[0].unidad")

print("\n8. La ruta del error apunta al campo exacto")
datos = json.loads(ruta_ejemplo.read_text(encoding="utf-8"))
datos["bancos"][0]["presets"][1]["tempo_bpm"] = 9999
try:
    Setlist.desde_dict(datos)
    check("ruta precisa", False)
except ErrorDeSetlist as e:
    check("ruta precisa", "bancos[0].presets[1].tempo_bpm" in str(e), f"-> {e}")

print("\n9. Ida y vuelta a disco")
with tempfile.TemporaryDirectory() as tmp:
    destino = Path(tmp) / "sub" / "x.json"
    destino.parent.mkdir(parents=True)
    sl.guardar(destino)
    recargada = Setlist.cargar(destino)
    check("round-trip idempotente", recargada.a_dict() == sl.a_dict())
    check("sin temporales sueltos",
          list(destino.parent.glob("*.tmp")) == [],
          f"-> {[f.name for f in destino.parent.iterdir()]}")
    check("json legible", "Clean Verso" in destino.read_text(encoding="utf-8"))

print("\n10. JSON invalido da error claro")
with tempfile.TemporaryDirectory() as tmp:
    roto = Path(tmp) / "roto.json"
    roto.write_text("{ esto no es json", encoding="utf-8")
    espera_error("json roto", lambda: Setlist.cargar(roto), "JSON inválido")

print("\n11. Setlist llena: 32 bancos x 8 presets")
llena = Setlist(
    nombre="Llena",
    bancos=[Banco(nombre=f"B{i}",
                  presets=[Preset(nombre=f"P{i}-{j}") for j in range(PRESETS_POR_BANCO)])
            for i in range(MAX_BANCOS)],
)
check("256 presets", llena.total_presets == MAX_PRESETS, f"-> {llena.total_presets}")
check("ultimo indice", llena.preset_por_indice(255).nombre == "P31-7",
      f"-> {llena.preset_por_indice(255).nombre}")
check("valida al recargar", Setlist.desde_dict(llena.a_dict()).total_presets == MAX_PRESETS)

print("\n" + ("FALLARON: " + ", ".join(fallos) if fallos else "TODO OK"))
sys.exit(1 if fallos else 0)
