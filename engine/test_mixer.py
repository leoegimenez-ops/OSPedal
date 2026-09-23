"""Pruebas del mezclador interno.

`mezclar()` se prueba como función pura, sin JACK. `MezcladorJack` se prueba en vivo contra un
jackd real: se crea un cliente sintético que escribe una señal constante conocida, se conecta a
través del mezclador, y se lee lo que sale del otro lado con un tercer cliente — así la prueba
cubre el camino completo (puertos JACK reales, no solo la matemática).

Requiere el paquete `jack` (JACK-Client) y `numpy`, instalados en `.venv/` (no en el Python de
sistema). Si no hay un servidor JACK corriendo, la parte en vivo se saltea con un aviso en vez de
fallar — no todas las máquinas donde corre este repo van a tener jackd arriba.

Se ejecuta como módulo (python -m engine.test_mixer) para que el import relativo funcione igual
en Windows y en Linux/WSL2.
"""
import sys
import time

import numpy as np

from engine.mixer import ErrorDeMezclador, mezclar

fallos = []


def check(nombre, ok, detalle=""):
    print(f"  {'OK  ' if ok else 'FALLA'}  {nombre}{'  ' + detalle if detalle else ''}")
    if not ok:
        fallos.append(nombre)


print("\n1. mezclar(): suma ponderada simple")
entradas = {"a": np.array([1.0, 2.0, 3.0], dtype=np.float32),
            "b": np.array([10.0, 10.0, 10.0], dtype=np.float32)}
r = mezclar(entradas, {"a": 1.0, "b": 0.5})
check("a*1 + b*0.5", np.allclose(r, [6.0, 7.0, 8.0]), f"-> {r}")

print("\n2. mezclar(): ganancia 0 silencia la fuente sin romper")
r = mezclar(entradas, {"a": 0.0, "b": 1.0})
check("solo b", np.allclose(r, [10.0, 10.0, 10.0]), f"-> {r}")

print("\n3. mezclar(): fuente en ganancias sin entrada conectada se ignora")
r = mezclar({"a": entradas["a"]}, {"a": 1.0, "b": 2.0})
check("no revienta, usa solo lo conectado", np.allclose(r, entradas["a"]), f"-> {r}")

print("\n4. mezclar(): sin ninguna fuente activa da silencio del largo correcto")
r = mezclar(entradas, {})
check("silencio, largo 3", np.allclose(r, [0, 0, 0]) and len(r) == 3, f"-> {r}")

print("\n5. mezclar(): ganancia negativa (fase invertida) funciona")
r = mezclar({"a": entradas["a"]}, {"a": -1.0})
check("invierte", np.allclose(r, [-1.0, -2.0, -3.0]), f"-> {r}")

print("\n6. MezcladorJack: validaciones sin necesitar JACK")
try:
    from engine.mixer import MezcladorJack
    MezcladorJack([], ["pa"])
    check("fuentes vacias", False)
except ErrorDeMezclador as e:
    check("fuentes vacias", "vac" in str(e), f"-> {e}")
try:
    MezcladorJack(["g1", "g1"], ["pa"])
    check("fuentes repetidas", False)
except ErrorDeMezclador as e:
    check("fuentes repetidas", "repetid" in str(e), f"-> {e}")

print("\n7. MezcladorJack en vivo: contra un jackd real")
try:
    import jack as _jack
    _jack.Client("sonda_disponibilidad").close()
    hay_jack = True
except Exception as e:
    hay_jack = False
    print(f"  (sin servidor JACK disponible, se saltea: {e})")

if hay_jack:
    import jack

    capturado = {"buf": None}

    fuente = jack.Client("test_mixer_fuente")
    out_a = fuente.outports.register("a_out")
    out_b = fuente.outports.register("b_out")

    @fuente.set_process_callback
    def _emitir(frames):
        out_a.get_array()[:] = 0.5
        out_b.get_array()[:] = 0.25

    receptor = jack.Client("test_mixer_receptor")
    in_salida = receptor.inports.register("in_salida")

    @receptor.set_process_callback
    def _recibir(frames):
        capturado["buf"] = in_salida.get_array().copy()

    from engine.mixer import MezcladorJack

    with MezcladorJack(["a", "b"], ["salida"], nombre_cliente="test_mixer_medio") as mezclador:
        fuente.activate()
        receptor.activate()
        time.sleep(0.2)

        mezclador.conectar_entrada("a", "test_mixer_fuente:a_out")
        mezclador.conectar_entrada("b", "test_mixer_fuente:b_out")
        mezclador.conectar_salida("salida", "test_mixer_receptor:in_salida")
        mezclador.fijar_ganancia("a", "salida", 2.0)
        mezclador.fijar_ganancia("b", "salida", 1.0)
        time.sleep(0.5)

        esperado = 2.0 * 0.5 + 1.0 * 0.25  # 1.25
        buf = capturado["buf"]
        check("puertos reales conectados y sumados con ganancia",
              buf is not None and np.allclose(buf, esperado, atol=1e-4),
              f"-> {buf[:4] if buf is not None else None} (esperado {esperado})")

        mezclador.fijar_ganancia("a", "salida", 0.0)
        time.sleep(0.3)
        buf2 = capturado["buf"]
        check("cambiar ganancia en caliente se refleja sin reconectar",
              buf2 is not None and np.allclose(buf2, 0.25, atol=1e-4),
              f"-> {buf2[:4] if buf2 is not None else None}")

    fuente.deactivate()
    fuente.close()
    receptor.deactivate()
    receptor.close()

print("\n" + ("FALLARON: " + ", ".join(fallos) if fallos else "TODO OK"))
sys.exit(1 if fallos else 0)
