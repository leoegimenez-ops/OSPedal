"""Pruebas del motor MIDI y del controlador de escenario.

Es una prueba de integracion (midi_engine + controlador + presets), no de
un solo modulo -- por eso vive aparte de test_midi_engine.py. Se ejecuta
como modulo (python -m engine.test_integracion) para que el import
relativo funcione igual en Windows y en Linux/WSL2.
"""
import sys
import tempfile
from pathlib import Path

from engine.midi_engine import (
    Accion, Asignacion, Disparador, ErrorDeMapa, MapaMidi,
    MensajeMidi, ParserMidi, TipoMensaje,
)
from engine.controlador import ControladorEscenario, Modo
from presets.preset_manager import Banco, Preset, Setlist, Stomp, Escena

fallos = []


def check(nombre, ok, detalle=""):
    print(f"  {'OK  ' if ok else 'FALLA'}  {nombre}{'  ' + detalle if detalle else ''}")
    if not ok:
        fallos.append(nombre)


class RPCFalso:
    def __init__(self):
        self.llamadas = []

    def set_preset(self, b, p):
        self.llamadas.append(("setpreset", b, p))

    def fijar(self, *pares):
        assert len(pares) % 2 == 0, "cantidad impar de pares"
        self.llamadas.append(("set",) + pares)

    def notificar(self, metodo, *params):
        self.llamadas.append((metodo,) + params)

    def ultimo_set(self):
        for c in reversed(self.llamadas):
            if c[0] == "set":
                return dict(zip(c[1::2], c[2::2]))
        return {}


print("\n1. Parser: mensajes basicos")
p = ParserMidi()
m = p.alimentar([0x90, 60, 100])[0]
check("note on", (m.tipo, m.numero, m.valor) == (TipoMensaje.NOTE_ON, 60, 100))
check("canal 1..16 no 0..15", m.canal == 1, f"-> canal {m.canal}")
m = p.alimentar([0x9F, 60, 100])[0]
check("canal 16", m.canal == 16, f"-> {m.canal}")
m = p.alimentar([0xB0, 80, 127])[0]
check("control change", (m.tipo, m.numero, m.valor) == (TipoMensaje.CONTROL_CHANGE, 80, 127))

print("\n2. Parser: program change lleva UN solo byte de datos")
msgs = p.alimentar([0xC0, 5, 0xC0, 7])
check("dos program change", len(msgs) == 2, f"-> {len(msgs)}")
check("valores correctos", [x.numero for x in msgs] == [5, 7],
      f"-> {[x.numero for x in msgs]}")

print("\n3. Parser: note on con velocity 0 es note off")
m = p.alimentar([0x90, 60, 0])[0]
check("convertido a note_off", m.tipo is TipoMensaje.NOTE_OFF)
check("no es pulsacion", not m.es_pulsacion)

print("\n4. Parser: running status")
# Un solo byte de estado y despues solo datos: tres note on seguidos.
msgs = p.alimentar([0x90, 60, 100, 62, 100, 64, 100])
check("tres mensajes", len(msgs) == 3, f"-> {len(msgs)}")
check("notas correctas", [x.numero for x in msgs] == [60, 62, 64],
      f"-> {[x.numero for x in msgs]}")

print("\n5. Parser: tiempo real intercalado no rompe el mensaje")
p2 = ParserMidi()
# Un MIDI Clock (0xF8) cae justo entre los dos bytes de datos de un control change.
msgs = p2.alimentar([0xB0, 80, 0xF8, 127])
tipos = [x.tipo for x in msgs]
check("dos mensajes", len(msgs) == 2, f"-> {tipos}")
check("realtime primero", msgs[0].tipo is TipoMensaje.REALTIME)
cc = [x for x in msgs if x.tipo is TipoMensaje.CONTROL_CHANGE]
check("el CC sobrevive intacto", cc and cc[0].numero == 80 and cc[0].valor == 127,
      f"-> {cc}")

print("\n6. Parser: mensaje partido entre lecturas")
p3 = ParserMidi()
check("nada aun", p3.alimentar([0xB0, 80]) == [])
msgs = p3.alimentar([127])
check("se completa al llegar el resto", len(msgs) == 1 and msgs[0].valor == 127,
      f"-> {msgs}")

print("\n7. Parser: pitch bend de 14 bits y sysex ignorado")
p4 = ParserMidi()
m = p4.alimentar([0xE0, 0x00, 0x40])[0]
check("pitch bend centrado", m.valor == 8192, f"-> {m.valor}")
msgs = p4.alimentar([0xF0, 1, 2, 3, 0xF7, 0x90, 60, 100])
check("sysex descartado, sigue el resto",
      len(msgs) == 1 and msgs[0].tipo is TipoMensaje.NOTE_ON, f"-> {msgs}")

print("\n8. Mapa: resolucion de acciones")
mapa = MapaMidi(nombre="Test", asignaciones=[
    Asignacion(Disparador(TipoMensaje.CONTROL_CHANGE, 80), Accion.TOGGLE_STOMP, 0),
    Asignacion(Disparador(TipoMensaje.NOTE_ON, 60), Accion.BANCO_SIGUIENTE),
])
check("CC mapeado", mapa.resolver(MensajeMidi(TipoMensaje.CONTROL_CHANGE, 1, 80, 127))
      == (Accion.TOGGLE_STOMP, 0))
check("nota mapeada", mapa.resolver(MensajeMidi(TipoMensaje.NOTE_ON, 1, 60, 100))
      == (Accion.BANCO_SIGUIENTE, None))
check("sin mapear da None",
      mapa.resolver(MensajeMidi(TipoMensaje.CONTROL_CHANGE, 1, 99, 127)) is None)

print("\n9. Mapa: soltar el pedal no dispara de nuevo")
# Un footswitch momentaneo manda 127 al pisar y 0 al soltar.
check("pisar dispara",
      mapa.resolver(MensajeMidi(TipoMensaje.CONTROL_CHANGE, 1, 80, 127)) is not None)
check("soltar NO dispara",
      mapa.resolver(MensajeMidi(TipoMensaje.CONTROL_CHANGE, 1, 80, 0)) is None)
check("note off NO dispara",
      mapa.resolver(MensajeMidi(TipoMensaje.NOTE_OFF, 1, 60, 0)) is None)

print("\n10. Mapa: program change directo")
check("PC 5 -> preset 5",
      mapa.resolver(MensajeMidi(TipoMensaje.PROGRAM_CHANGE, 1, 5))
      == (Accion.CAMBIAR_PRESET, 5))
mapa_sin = MapaMidi(programa_directo=False)
check("desactivable",
      mapa_sin.resolver(MensajeMidi(TipoMensaje.PROGRAM_CHANGE, 1, 5)) is None)

print("\n11. Mapa: filtro por canal")
mapa_canal = MapaMidi(canal=3, asignaciones=[
    Asignacion(Disparador(TipoMensaje.CONTROL_CHANGE, 80, 3), Accion.AFINADOR),
])
check("canal correcto pasa",
      mapa_canal.resolver(MensajeMidi(TipoMensaje.CONTROL_CHANGE, 3, 80, 127)) is not None)
check("otro canal se ignora",
      mapa_canal.resolver(MensajeMidi(TipoMensaje.CONTROL_CHANGE, 5, 80, 127)) is None)

print("\n12. MIDI learn")
aprendido = MapaMidi(programa_directo=False)
msg = MensajeMidi(TipoMensaje.CONTROL_CHANGE, 7, 42, 127)
aprendido.aprender(msg, Accion.TOGGLE_STOMP, 2)
check("queda asociado", aprendido.resolver(msg) == (Accion.TOGGLE_STOMP, 2))
check("respeta el canal aprendido",
      aprendido.resolver(MensajeMidi(TipoMensaje.CONTROL_CHANGE, 8, 42, 127)) is None)
# Reaprender el mismo control reemplaza, no duplica.
aprendido.aprender(msg, Accion.AFINADOR)
check("reaprender reemplaza", len(aprendido.asignaciones) == 1,
      f"-> {len(aprendido.asignaciones)} asignaciones")
check("nueva accion", aprendido.resolver(msg) == (Accion.AFINADOR, None))
# Aprender desde un note off debe registrar el note on (es la pisada).
omni = MapaMidi(programa_directo=False)
omni.aprender(MensajeMidi(TipoMensaje.NOTE_OFF, 2, 64, 0), Accion.TAP_TEMPO, omni=True)
check("note off se aprende como note on",
      omni.resolver(MensajeMidi(TipoMensaje.NOTE_ON, 9, 64, 100)) == (Accion.TAP_TEMPO, None))

print("\n13. Mapa: persistencia")
with tempfile.TemporaryDirectory() as tmp:
    destino = Path(tmp) / "mapa.json"
    mapa.guardar(destino)
    recargado = MapaMidi.cargar(destino)
    check("round-trip", recargado.a_dict() == mapa.a_dict())
    check("sin .tmp sueltos", list(Path(tmp).glob("*.tmp")) == [])

print("\n14. Mapa: validacion")
def espera(nombre, fn, frag):
    try:
        fn()
        check(nombre, False, "-> no lanzo")
    except ErrorDeMapa as e:
        check(nombre, frag in str(e), f"-> {e}")

espera("accion desconocida",
       lambda: MapaMidi.desde_dict({"version": 1, "asignaciones": [
           {"tipo": "control_change", "numero": 1, "accion": "volar"}]}), "accion")
espera("tipo desconocido",
       lambda: MapaMidi.desde_dict({"version": 1, "asignaciones": [
           {"tipo": "telepatia", "numero": 1, "accion": "afinador"}]}), "tipo")
espera("numero fuera de rango",
       lambda: MapaMidi.desde_dict({"version": 1, "asignaciones": [
           {"tipo": "control_change", "numero": 999, "accion": "afinador"}]}), "numero")
espera("canal invalido",
       lambda: MapaMidi.desde_dict({"version": 1, "canal": 44}), "canal")
espera("version incorrecta", lambda: MapaMidi.desde_dict({"version": 7}), "version")

print("\n15. Controlador: carga de preset")
setlist = Setlist(nombre="T", bancos=[
    Banco("A", [
        Preset("Uno", guitarix_banco="F", guitarix_preset="P1",
               parametros={"amp.gain": 0.3},
               stomps=[Stomp("DLY", "echo", False), Stomp("RVB", "freeverb", True)],
               escenas=[Escena("Alta", {"amp.gain": 0.9})], tempo_bpm=120),
        Preset("Dos", parametros={"amp.gain": 0.6}),
        Preset("Tres"),
    ]),
    Banco("B", [Preset("Cuatro")]),
])
rpc = RPCFalso()
ctrl = ControladorEscenario(setlist, rpc)
check("arranca en el primero", ctrl.preset.nombre == "Uno")
check("no toca el motor al construir", rpc.llamadas == [], f"-> {rpc.llamadas}")

rpc.llamadas.clear()
ctrl.ejecutar(Accion.CAMBIAR_PRESET, 1)
check("cambia de preset", ctrl.preset.nombre == "Dos")
check("empuja al motor", any(c[0] == "set" for c in rpc.llamadas))

print("\n16. Controlador: subir de banco NO cambia el sonido")
ctrl.cargar(0, 0)
rpc.llamadas.clear()
r = ctrl.ejecutar(Accion.BANCO_SIGUIENTE)
check("banco visible avanza", ctrl.banco_visible == 1, f"-> {r}")
check("el preset que suena no cambia", ctrl.preset.nombre == "Uno")
check("no se manda nada al motor", rpc.llamadas == [], f"-> {rpc.llamadas}")
# Recien al elegir un preset del banco nuevo suena.
ctrl.ejecutar(Accion.PRESET_EN_BANCO, 0)
check("ahora si suena el del banco B", ctrl.preset.nombre == "Cuatro")

print("\n17. Controlador: navegacion saltea huecos")
ctrl.cargar(0, 2)          # "Tres", ultimo del banco A (indice 2)
ctrl.ejecutar(Accion.PRESET_SIGUIENTE)
# El banco A tiene 3 presets, el B arranca en el indice 8: hay que saltar el hueco.
check("salta al banco siguiente", ctrl.preset.nombre == "Cuatro",
      f"-> {ctrl.preset.nombre} (indice {ctrl.indice_activo})")
ctrl.ejecutar(Accion.PRESET_SIGUIENTE)
check("da la vuelta al final", ctrl.preset.nombre == "Uno", f"-> {ctrl.preset.nombre}")
ctrl.ejecutar(Accion.PRESET_ANTERIOR)
check("y hacia atras tambien", ctrl.preset.nombre == "Cuatro", f"-> {ctrl.preset.nombre}")

print("\n18. Controlador: stomps")
ctrl.cargar(0, 0)
check("estado inicial del preset", (ctrl.stomp_activo(0), ctrl.stomp_activo(1)) == (False, True))
rpc.llamadas.clear()
r = ctrl.ejecutar(Accion.TOGGLE_STOMP, 0)
check("se prende", ctrl.stomp_activo(0) is True, f"-> {r}")
check("etiqueta en la respuesta", "DLY" in r and "ON" in r, f"-> {r}")
check("un solo parametro al motor", rpc.llamadas == [("set", "echo.on_off", 1)],
      f"-> {rpc.llamadas}")
ctrl.ejecutar(Accion.TOGGLE_STOMP, 0)
check("se apaga", ctrl.stomp_activo(0) is False)
check("stomp inexistente no rompe", "Sin stomp" in ctrl.ejecutar(Accion.TOGGLE_STOMP, 5))

print("\n19. Controlador: el stomp pisado sobrevive al cambio de escena")
ctrl.cargar(0, 0)
ctrl.ejecutar(Accion.TOGGLE_STOMP, 0)      # echo ON, distinto de lo que dice el preset
rpc.llamadas.clear()
ctrl.ejecutar(Accion.ESCENA, 0)
env = rpc.ultimo_set()
check("la escena pisa el parametro", env.get("amp.gain") == 0.9, f"-> {env.get('amp.gain')}")
check("el stomp pisado se respeta", env.get("echo.on_off") == 1, f"-> {env.get('echo.on_off')}")
check("escena inexistente no rompe", "Sin escena" in ctrl.ejecutar(Accion.ESCENA, 9))
# Bug encontrado en revision de codigo (23/09/2026): cambiar de escena reenviaba setpreset,
# un recargado completo del preset base -- innecesario y con riesgo real de corte de audio,
# para lo que tiene que ser solo un ajuste de parametros. El preset base ya esta cargado.
check("NO reenvia setpreset al cambiar de escena (el preset base ya esta cargado)",
      not any(c[0] == "setpreset" for c in rpc.llamadas), f"-> {rpc.llamadas}")

print("\n20. Controlador: cambiar de preset reinicia los stomps")
ctrl.cargar(0, 0)
ctrl.ejecutar(Accion.TOGGLE_STOMP, 0)
check("quedo pisado", ctrl.stomp_activo(0) is True)
ctrl.cargar(0, 1)
ctrl.cargar(0, 0)
check("vuelve al estado del preset", ctrl.stomp_activo(0) is False)

print("\n21. Controlador: modo, afinador y rangos")
check("cambia de modo", "stomp" in ctrl.ejecutar(Accion.MODO, 1) and ctrl.modo is Modo.STOMP)
rpc.llamadas.clear()
ctrl.ejecutar(Accion.AFINADOR)
check("llama al afinador", rpc.llamadas == [("switch_tuner", 1)], f"-> {rpc.llamadas}")
check("preset fuera de rango", "fuera de rango" in ctrl.ejecutar(Accion.CAMBIAR_PRESET, 300))
check("preset vacio", "vac" in ctrl.ejecutar(Accion.CAMBIAR_PRESET, 100))

print("\n22. Controlador: tap tempo")
reloj = {"t": 0.0}
ctrl2 = ControladorEscenario(setlist, RPCFalso(), reloj=lambda: reloj["t"])
ctrl2.ejecutar(Accion.TAP_TEMPO)
for _ in range(3):
    reloj["t"] += 0.5          # 0.5s entre pisadas = 120 BPM
    r = ctrl2.ejecutar(Accion.TAP_TEMPO)
check("120 BPM", ctrl2.tempo_bpm == 120.0, f"-> {ctrl2.tempo_bpm} ({r})")
reloj["t"] += 10.0             # pausa larga: arranca serie nueva
check("reinicia tras pausa", "Tap" in ctrl2.ejecutar(Accion.TAP_TEMPO))
for _ in range(3):
    reloj["t"] += 0.25         # 240 BPM
    ctrl2.ejecutar(Accion.TAP_TEMPO)
check("240 BPM", ctrl2.tempo_bpm == 240.0, f"-> {ctrl2.tempo_bpm}")

print("\n23. Cadena completa: bytes MIDI -> accion -> motor")
rpc3 = RPCFalso()
ctrl3 = ControladorEscenario(setlist, rpc3)
parser = ParserMidi()
mapa3 = MapaMidi(asignaciones=[
    Asignacion(Disparador(TipoMensaje.CONTROL_CHANGE, 80), Accion.TOGGLE_STOMP, 0),
])
rpc3.llamadas.clear()
# Lo que mandaria una pedalera al pisar y soltar un switch.
for mensaje in parser.alimentar([0xB0, 80, 127, 0xB0, 80, 0]):
    resuelto = mapa3.resolver(mensaje)
    if resuelto:
        ctrl3.ejecutar(*resuelto)
check("una sola accion por pisada", rpc3.llamadas == [("set", "echo.on_off", 1)],
      f"-> {rpc3.llamadas}")

# Y un program change eligiendo preset.
rpc3.llamadas.clear()
for mensaje in parser.alimentar([0xC0, 1]):
    resuelto = mapa3.resolver(mensaje)
    if resuelto:
        ctrl3.ejecutar(*resuelto)
check("PC cambia de preset", ctrl3.preset.nombre == "Dos", f"-> {ctrl3.preset.nombre}")

print("\n" + ("FALLARON: " + ", ".join(fallos) if fallos else "TODO OK"))
sys.exit(1 if fallos else 0)
