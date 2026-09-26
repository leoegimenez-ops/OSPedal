"""Pruebas de SPLIT/MERGE (líneas paralelas) y de las entradas estéreo del mezclador.

La matemática se prueba como funciones puras. `RuteadorParalelo` y el mezclador estéreo se prueban
en vivo contra un jackd real con clientes sintéticos que emiten señales constantes conocidas y un
receptor que mide lo que sale -- el camino completo por puertos JACK reales. Sin servidor JACK, la
parte en vivo se saltea con un aviso.

Se ejecuta con el venv del proyecto: .venv/bin/python -m engine.test_paralelo
"""
import sys
import time

import numpy as np

from engine.mixer import mezclar_fuentes_estereo
from engine.paralelo import AjustesMerge, AjustesSplit, dividir, unir

try:
    import jack as _jack
    _jack.Client("sonda_paralelo").close()
    hay_jack = True
except Exception as _e:
    hay_jack = False
    print(f"(sin servidor JACK, se saltean las pruebas en vivo: {_e})")

fallos = []


def check(nombre, ok, detalle=""):
    print(f"  {'OK  ' if ok else 'FALLA'}  {nombre}{'  ' + detalle if detalle else ''}")
    if not ok:
        fallos.append(nombre)


x = np.array([0.5, -0.5, 0.25], dtype=np.float32)

print("\n1. SPLIT")
a, b = dividir(x, AjustesSplit())
check("centro: las dos lineas a nivel completo (split en Y)", np.allclose(a, x) and np.allclose(b, x))
a, b = dividir(x, AjustesSplit(balance=-1))
check("balance -1: todo a A, B en silencio", np.allclose(a, x) and np.allclose(b, 0))
a, b = dividir(x, AjustesSplit(balance=0.5))
check("balance +0.5: A a la mitad, B completa", np.allclose(a, x * 0.5) and np.allclose(b, x))

print("\n2. MERGE")
uno = np.ones(3, dtype=np.float32)
l, r = unir(uno, uno, uno * 0.5, uno * 0.5, AjustesMerge())
check("niveles 1/1, centro: suma", np.allclose(l, 1.5) and np.allclose(r, 1.5), f"-> {l}")
l, r = unir(uno, uno, uno, uno, AjustesMerge(fase_b=True))
check("fase B invertida: dos lineas iguales se cancelan", np.allclose(l, 0) and np.allclose(r, 0))
l, r = unir(uno, uno, uno, uno, AjustesMerge(pan_a=-1, pan_b=1))
check("A a la izquierda, B a la derecha", np.allclose(l, 1) and np.allclose(r, 1))
l, r = unir(uno, uno, uno * 0, uno * 0, AjustesMerge(pan_a=-1))
check("A hard-left: la derecha queda en silencio", np.allclose(l, 1) and np.allclose(r, 0), f"-> {l} {r}")
l, r = unir(uno, uno, uno, uno, AjustesMerge(nivel_a=0.25, nivel_b=0))
check("niveles por linea", np.allclose(l, 0.25) and np.allclose(r, 0.25))

print("\n3. Mezclador con fuentes estereo")
l_in = {"g": np.array([1.0, 1.0], dtype=np.float32)}
r_in = {"g": np.array([0.2, 0.2], dtype=np.float32)}
izq, der = mezclar_fuentes_estereo(l_in, r_in, {"g": 1.0}, {"g": 0.0})
check("centro: L y R propios, sin mezclarlos", np.allclose(izq, 1.0) and np.allclose(der, 0.2))
izq, der = mezclar_fuentes_estereo(l_in, r_in, {"g": 1.0}, {"g": 1.0})
check("paneo = balance: hard right apaga L, R intacto", np.allclose(izq, 0) and np.allclose(der, 0.2))

print("\n3b. Plan de cableado JACK (engine/motores.py)")
from engine.motores import nombre_jack, plan_cableado, puerto_rpc  # noqa: E402

ps = lambda l, s: f"ps_split:{l}_{s}"   # noqa: E731
pm = lambda l, s: f"ps_merge:{l}_{s}"   # noqa: E731
sin = plan_cableado("g1", False, False, ps, pm, "mix:g1_L", "mix:g1_R").conexiones
check("sin split: pre_amp -> pre_fx -> mezclador L/R",
      sin == [("ps_g1_pre_amp:out_0", "ps_g1_pre_fx:in_0"),
              ("ps_g1_pre_fx:out_0", "mix:g1_L"), ("ps_g1_pre_fx:out_1", "mix:g1_R")], f"-> {sin}")
con = set(plan_cableado("g1", True, False, ps, pm, "mix:g1_L", "mix:g1_R").conexiones)
check("split con MERGE al final: estereo directo al mezclador",
      {("ps_g1_pre_amp:out_0", "ps_split:g1_in"), ("ps_split:g1_a", "ps_g1_a_amp:in_0"),
       ("ps_split:g1_b", "ps_g1_b_amp:in_0"), ("ps_g1_a_fx:out_1", "ps_merge:g1_a_R"),
       ("ps_merge:g1_L", "mix:g1_L"), ("ps_merge:g1_R", "mix:g1_R")} <= con
      and not any("post" in a or "post" in b for a, b in con), f"-> {sorted(con)}")
post = set(plan_cableado("g1", True, True, ps, pm, "mix:g1_L", "mix:g1_R").conexiones)
check("split con bloques despues del MERGE: mono -> post -> mezclador",
      {("ps_merge:g1_mono", "ps_g1_post_amp:in_0"), ("ps_g1_post_fx:out_0", "mix:g1_L")} <= post
      and ("ps_merge:g1_L", "mix:g1_L") not in post, f"-> {sorted(post)}")
check("puertos RPC: pre compatible (7000+i), extras sin chocar",
      [puerto_rpc(1, t) for t in ("pre", "a", "b", "post")] == [7001, 7111, 7112, 7113]
      and nombre_jack("bajo", "b") == "ps_bajo_b")

print("\n4. En vivo: SPLIT y MERGE por puertos JACK reales")
if hay_jack:
    import jack

    from engine.paralelo import RuteadorParalelo

    medido = {}
    fuente = jack.Client("tp_fuente")
    f_in = fuente.outports.register("seno")          # señal que entra al SPLIT
    f_al = fuente.outports.register("a_L")           # lo que "devolverían" los motores A y B
    f_ar = fuente.outports.register("a_R")
    f_bl = fuente.outports.register("b_L")
    f_br = fuente.outports.register("b_R")

    @fuente.set_process_callback
    def _emitir(frames):
        f_in.get_array()[:] = 0.8
        f_al.get_array()[:] = 0.5
        f_ar.get_array()[:] = 0.5
        f_bl.get_array()[:] = 0.3
        f_br.get_array()[:] = 0.3

    receptor = jack.Client("tp_receptor")
    r_ports = {n: receptor.inports.register(n) for n in ("sa", "sb", "L", "R", "mono")}

    @receptor.set_process_callback
    def _recibir(frames):
        for n, p in r_ports.items():
            medido[n] = float(p.get_array()[0])

    rt = RuteadorParalelo(["g1"], prefijo="tp")
    rt.iniciar()
    fuente.activate()
    receptor.activate()
    conexiones = [
        ("tp_fuente:seno", rt.puerto_split("g1", "in")),
        (rt.puerto_split("g1", "a"), "tp_receptor:sa"),
        (rt.puerto_split("g1", "b"), "tp_receptor:sb"),
        ("tp_fuente:a_L", rt.puerto_merge("g1", "a_L")), ("tp_fuente:a_R", rt.puerto_merge("g1", "a_R")),
        ("tp_fuente:b_L", rt.puerto_merge("g1", "b_L")), ("tp_fuente:b_R", rt.puerto_merge("g1", "b_R")),
        (rt.puerto_merge("g1", "L"), "tp_receptor:L"), (rt.puerto_merge("g1", "R"), "tp_receptor:R"),
        (rt.puerto_merge("g1", "mono"), "tp_receptor:mono"),
    ]
    for o, d in conexiones:
        fuente.connect(o, d)
    time.sleep(0.4)
    check("sin split activo: todo en silencio (no gasta CPU)",
          all(abs(medido.get(n, 1)) < 1e-6 for n in ("sa", "sb", "L")), f"-> {medido}")
    rt.activar("g1", True)
    time.sleep(0.3)
    check("SPLIT en Y: las dos salidas llevan la entrada", abs(medido["sa"] - 0.8) < 1e-4
          and abs(medido["sb"] - 0.8) < 1e-4, f"-> {medido}")
    check("MERGE: A + B", abs(medido["L"] - 0.8) < 1e-4 and abs(medido["R"] - 0.8) < 1e-4, f"-> {medido}")
    rt.fijar("g1", "merge.nivel_b", 0)
    rt.fijar("g1", "split.balance", -1)
    time.sleep(0.3)
    check("en caliente: nivel B = 0 y balance todo a A",
          abs(medido["L"] - 0.5) < 1e-4 and abs(medido["sb"]) < 1e-6, f"-> {medido}")
    rt.fijar("g1", "merge.pan_a", -1)
    time.sleep(0.3)
    check("pan A izquierda: L 0.5, R 0, mono 0.25",
          abs(medido["L"] - 0.5) < 1e-4 and abs(medido["R"]) < 1e-6 and abs(medido["mono"] - 0.25) < 1e-4,
          f"-> {medido}")
    check("valores() refleja lo fijado", rt.valores("g1")["merge.pan_a"] == -1.0)
    try:
        rt.fijar("g1", "merge.nivel_a", float("nan"))
        check("rechaza NaN", False)
    except Exception as e:
        check("rechaza NaN", "finito" in str(e), f"-> {e}")
    fuente.deactivate(); fuente.close()
    receptor.deactivate(); receptor.close()
    rt.detener()

    print("\n5. En vivo: mezclador con entradas estereo")
    from engine.mixer import MezcladorJack
    medido2 = {}
    f2 = jack.Client("tp_fuente2")
    o_l, o_r = f2.outports.register("L"), f2.outports.register("R")

    @f2.set_process_callback
    def _emitir2(frames):
        o_l.get_array()[:] = 0.6
        o_r.get_array()[:] = 0.2

    rec2 = jack.Client("tp_receptor2")
    ri_l, ri_r = rec2.inports.register("L"), rec2.inports.register("R")

    @rec2.set_process_callback
    def _recibir2(frames):
        medido2["L"] = float(ri_l.get_array()[0])
        medido2["R"] = float(ri_r.get_array()[0])

    with MezcladorJack(["gtr"], ["pa"], nombre_cliente="tp_mixer", modo_buses={"pa": "estereo"},
                       entradas_estereo=True) as mx:
        f2.activate(); rec2.activate()
        mx.conectar_entrada("gtr", "tp_fuente2:L", "L")
        mx.conectar_entrada("gtr", "tp_fuente2:R", "R")
        mx.conectar_salida("pa", "tp_receptor2:L", "L")
        mx.conectar_salida("pa", "tp_receptor2:R", "R")
        time.sleep(0.4)
        check("la imagen estereo pasa intacta", abs(medido2["L"] - 0.6) < 1e-4 and abs(medido2["R"] - 0.2) < 1e-4,
              f"-> {medido2}")
        check("nombres de puerto", mx.puerto_entrada("gtr", "R") == "tp_mixer:gtr_R", f"-> {mx.puerto_entrada('gtr', 'R')}")
    f2.deactivate(); f2.close()
    rec2.deactivate(); rec2.close()

print("\n" + ("FALLARON: " + ", ".join(fallos) if fallos else "TODO OK"))
sys.exit(1 if fallos else 0)
