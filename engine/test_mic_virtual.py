"""Pruebas del modelo de microfono virtual.

Importante: esto verifica CONSISTENCIA MATEMATICA (monotonia, limites,
relaciones entre tipos de mic), no que "suene bien" -- eso requiere audio
real. Ya se probo aplicar() de punta a punta contra un Guitarix real
corriendo bajo WSL2 (ver docs/mic-virtual.md) -- esto complementa esa
prueba, no la reemplaza, y corre sin necesitar el motor.

Se ejecuta como modulo (python -m engine.test_mic_virtual) para que el
import relativo funcione igual en Windows y en Linux/WSL2.
"""
from engine.mic_virtual import calcular, aplicar, TIPOS_MIC

fallos = []


def check(nombre, ok, detalle=""):
    print(f"  {'OK  ' if ok else 'FALLA'}  {nombre}{'  ' + detalle if detalle else ''}")
    if not ok:
        fallos.append(nombre)


print("\n1. Limites de posicion (centro vs borde)")
centro = calcular(0.0, 0.0, "dinamico")
borde = calcular(1.0, 0.0, "dinamico")
check("centro es brillo_base_hz exacto", centro["pasabajos_hz"] == 9000, f"-> {centro['pasabajos_hz']}")
check("borde es oscurecimiento_hz exacto", borde["pasabajos_hz"] == 5500, f"-> {borde['pasabajos_hz']}")
check("borde mas oscuro que centro", borde["pasabajos_hz"] < centro["pasabajos_hz"])

print("\n2. Monotonia de posicion: mover hacia el borde SIEMPRE oscurece")
valores = [calcular(p / 10, 0.0, "dinamico")["pasabajos_hz"] for p in range(11)]
decreciente = all(valores[i] >= valores[i + 1] for i in range(len(valores) - 1))
check("estrictamente no creciente en todo el rango", decreciente, f"-> {valores}")

print("\n3. Limites de distancia (proximity effect)")
cerca = calcular(0.0, 0.0, "dinamico")
lejos = calcular(0.0, 1.0, "dinamico")
check("distancia=0 da el boost maximo del tipo", cerca["graves_shelf_db"] == 10.0, f"-> {cerca['graves_shelf_db']}")
check("distancia=1 el boost cayo casi a cero", lejos["graves_shelf_db"] < 0.5, f"-> {lejos['graves_shelf_db']}")

print("\n4. Monotonia de distancia: alejarse SIEMPRE reduce el proximity effect")
valores = [calcular(0.0, d / 10, "dinamico")["graves_shelf_db"] for d in range(11)]
decreciente = all(valores[i] >= valores[i + 1] for i in range(len(valores) - 1))
check("estrictamente no creciente en todo el rango", decreciente, f"-> {valores}")

print("\n5. Los tres tipos de mic mantienen el orden que documenta la fisica real")
d0 = {t: calcular(0.0, 0.0, t)["graves_shelf_db"] for t in TIPOS_MIC}
check("cinta > dinamico > condensador en proximity effect",
      d0["cinta"] > d0["dinamico"] > d0["condensador"], f"-> {d0}")
b0 = {t: calcular(0.0, 0.0, t)["pasabajos_hz"] for t in TIPOS_MIC}
check("condensador > dinamico > cinta en brillo (centro del cono)",
      b0["condensador"] > b0["dinamico"] > b0["cinta"], f"-> {b0}")

print("\n6. Clamping de valores fuera de rango")
fuera_alto = calcular(5.0, 5.0, "dinamico")
fuera_bajo = calcular(-3.0, -3.0, "dinamico")
check("posicion/distancia > 1 se recortan a 1", fuera_alto == calcular(1.0, 1.0, "dinamico"))
check("posicion/distancia < 0 se recortan a 0", fuera_bajo == calcular(0.0, 0.0, "dinamico"))

print("\n7. Tipo de mic invalido da error claro")
try:
    calcular(0.5, 0.5, "no_existe")
    check("ValueError", False)
except ValueError as e:
    check("ValueError", "no_existe" in str(e) and "dinamico" in str(e), f"-> {e}")

print("\n8. Reverb sugerido: acotado y monotono, nunca domina la mezcla")
check("distancia=0 no sugiere reverb", calcular(0.5, 0.0, "dinamico")["reverb_wet_sugerido"] == 0.0)
check("distancia=1 no pasa el tope de 0.15", calcular(0.5, 1.0, "dinamico")["reverb_wet_sugerido"] <= 0.15)

print("\n9. aplicar() manda los parametros correctos por RPC")
class RPCFalso:
    def __init__(self):
        self.llamadas = []
    def fijar(self, *pares):
        assert len(pares) % 2 == 0
        self.llamadas.append(pares)

rpc = RPCFalso()
datos = aplicar(rpc, posicion=0.3, distancia=0.1, tipo="cinta", unidad_eq="eq")
pares = dict(zip(rpc.llamadas[0][::2], rpc.llamadas[0][1::2]))
check("manda peak1 (graves, banda Sub)", pares.get("eq.peak1") == 150)
check("manda level1 coincide con calcular()", pares.get("eq.level1") == datos["graves_shelf_db"])
check("manda peak4 (agudos fijo)", pares.get("eq.peak4") == datos["corte_agudos_hz"])
check("manda level4 coincide con calcular()", pares.get("eq.level4") == datos["corte_agudos_db"])

print("\n10. corte_agudos_db: monotono y en 0 cuando posicion=0")
check("posicion=0 no recorta", calcular(0.0, 0.0, "dinamico")["corte_agudos_db"] == 0.0)
check("posicion=1 llega al tope", calcular(1.0, 0.0, "dinamico")["corte_agudos_db"] == -10.0)
valores = [calcular(p / 10, 0.0, "dinamico")["corte_agudos_db"] for p in range(11)]
check("estrictamente no creciente en valor absoluto (cada vez mas negativo)",
      all(valores[i] >= valores[i + 1] for i in range(len(valores) - 1)), f"-> {valores}")

print("\n" + ("FALLARON: " + ", ".join(fallos) if fallos else "TODO OK"))
import sys as s
s.exit(1 if fallos else 0)
