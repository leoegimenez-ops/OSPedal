"""Pruebas del enumerador de audio (ALSA) y JACK.

Los parsers (parsear_aplay, parsear_jack_lsp) son funciones puras: no tocan el sistema, así que
se prueban con texto fijo. La sección de jack_lsp usa la salida real capturada contra un jackd
corriendo bajo WSL2 (ver docstring de audio_engine.py); la de aplay usa texto de ejemplo con el
formato documentado de alsa-utils, porque WSL2 no tiene forma de exponer una tarjeta ALSA real
para grabar la salida genuina — sigue pendiente de confirmar en la máquina de destino.

Se ejecuta como modulo (python -m engine.test_audio_engine) para que el import relativo
funcione igual en Windows y en Linux/WSL2.
"""
import sys

from engine.audio_engine import (
    DispositivoALSA, PuertoJack, TIPOS_DISPOSITIVO,
    dispositivos_alsa, parsear_aplay, parsear_jack_lsp, puertos_jack,
)

fallos = []


def check(nombre, ok, detalle=""):
    print(f"  {'OK  ' if ok else 'FALLA'}  {nombre}{'  ' + detalle if detalle else ''}")
    if not ok:
        fallos.append(nombre)


print("\n1. parsear_aplay: sin tarjetas (caso real confirmado en WSL2)")
check("lista vacia", parsear_aplay("") == [])

print("\n2. parsear_aplay: una tarjeta, un dispositivo")
texto = "**** List of PLAYBACK Hardware Devices ****\n" \
        "card 0: PCH [HDA Intel PCH], device 0: ALC3234 Analog [ALC3234 Analog]\n" \
        "  Subdevices: 1/1\n" \
        "  Subdevice #0: subdevice #0\n"
r = parsear_aplay(texto)
check("una tarjeta", len(r) == 1, f"-> {r}")
check("campos", r[0] == DispositivoALSA(0, "PCH", "HDA Intel PCH", 0, "ALC3234 Analog"))
check("hw calculado", r[0].hw == "hw:0,0")

print("\n3. parsear_aplay: varias tarjetas, varios dispositivos")
texto = (
    "**** List of PLAYBACK Hardware Devices ****\n"
    "card 0: PCH [HDA Intel PCH], device 0: ALC3234 Analog [ALC3234 Analog]\n"
    "  Subdevices: 1/1\n"
    "  Subdevice #0: subdevice #0\n"
    "card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]\n"
    "  Subdevices: 1/1\n"
    "  Subdevice #0: subdevice #0\n"
    "card 1: Device [USB Audio Device], device 1: USB Audio [USB Audio #1]\n"
    "  Subdevices: 1/1\n"
    "  Subdevice #0: subdevice #0\n"
)
r = parsear_aplay(texto)
check("tres dispositivos", len(r) == 3, f"-> {r}")
check("hw de cada uno", [d.hw for d in r] == ["hw:0,0", "hw:1,0", "hw:1,1"],
      f"-> {[d.hw for d in r]}")
check("nombres de tarjeta", [d.nombre_tarjeta for d in r] ==
      ["HDA Intel PCH", "USB Audio Device", "USB Audio Device"])

print("\n4. parsear_aplay: ignora encabezados y lineas de subdevice")
check("no cuela el encabezado como dispositivo",
      all("List of" not in d.nombre_tarjeta for d in r))

print("\n5. parsear_jack_lsp: salida real capturada (jackd dummy + Guitarix, WSL2)")
texto_jack = (
    "system:capture_1\n"
    "\tproperties: output,physical,terminal,\n"
    "\t32 bit float mono audio\n"
    "system:playback_1\n"
    "\tproperties: input,physical,terminal,\n"
    "\t32 bit float mono audio\n"
    "gx_head_amp:in_0\n"
    "\tproperties: input,\n"
    "\t32 bit float mono audio\n"
    "gx_head_amp:midi_in_1\n"
    "\tproperties: input,\n"
    "\t8 bit raw midi\n"
    "gx_head_amp:out_0\n"
    "\tproperties: output,\n"
    "\t32 bit float mono audio\n"
)
r = parsear_jack_lsp(texto_jack)
check("cinco puertos", len(r) == 5, f"-> {len(r)}")
check("puerto fisico de captura",
      r[0] == PuertoJack("system", "capture_1", "system:capture_1", "salida", "audio", True, True),
      f"-> {r[0]}")
check("puerto de entrada del amp",
      r[2] == PuertoJack("gx_head_amp", "in_0", "gx_head_amp:in_0", "entrada", "audio", False, False),
      f"-> {r[2]}")
check("puerto midi detectado", r[3].tipo == "midi", f"-> {r[3]}")
check("puerto midi no fisico ni terminal", not r[3].fisico and not r[3].terminal)

print("\n6. parsear_jack_lsp: vacio si no hay servidor")
check("lista vacia", parsear_jack_lsp("") == [])

print("\n7. dispositivos_alsa: valida el tipo")
try:
    dispositivos_alsa("no_existe")
    check("ValueError", False)
except ValueError as e:
    check("ValueError", "no_existe" in str(e), f"-> {e}")
check("tipos validos son los documentados", TIPOS_DISPOSITIVO == frozenset({"reproduccion", "captura"}))

print("\n8. dispositivos_alsa / puertos_jack: no explotan si falta el binario o no hay servidor")
# No se puede garantizar que aplay/arecord/jack_lsp existan en toda maquina que corra esto
# (por ejemplo, este mismo repo corriendo en Windows) -- el contrato es "lista vacia", nunca
# una excepcion sin capturar.
try:
    dispositivos_alsa("reproduccion")
    dispositivos_alsa("captura")
    puertos_jack()
    check("no lanza", True)
except Exception as e:
    check("no lanza", False, f"-> {type(e).__name__}: {e}")

print("\n" + ("FALLARON: " + ", ".join(fallos) if fallos else "TODO OK"))
sys.exit(1 if fallos else 0)
