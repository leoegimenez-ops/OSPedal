"""Parseo de la salida de nmcli (server/red.py), con salidas con la forma real de NetworkManager
(`nmcli -t` = campos separados por ':' con los ':' internos escapados). Sin red ni nmcli.

Se ejecuta: python -m server.test_red
"""
import sys

from server.red import dividir_terso, parsear_dispositivos, parsear_redes

fallos = []


def check(nombre, ok, detalle=""):
    print(f"  {'OK  ' if ok else 'FALLA'}  {nombre}{'  ' + detalle if detalle else ''}")
    if not ok:
        fallos.append(nombre)


print("\n1. Campos tersos")
check("dos puntos escapados en un SSID", dividir_terso(r" :Bar\:Sala 2:70:WPA2") == [" ", "Bar:Sala 2", "70", "WPA2"])

print("\n2. Redes Wi-Fi")
salida = "\n".join([
    "*:Casa:82:WPA2",
    " :Casa:40:WPA2",          # la misma red en otro canal, peor señal
    " :Bar\\:Sala 2:70:WPA1 WPA2",
    " :Libre:55:",
    " ::30:WPA2",              # oculta
])
redes = parsear_redes(salida)
check("conectada primero, sin duplicados ni ocultas",
      [r["ssid"] for r in redes] == ["Casa", "Bar:Sala 2", "Libre"], f"-> {redes}")
check("señal y seguridad", redes[0]["conectada"] and redes[0]["senal"] == 82 and redes[1]["segura"]
      and not redes[2]["segura"])

print("\n3. Dispositivos")
disp = parsear_dispositivos("wlan0:wifi:connected:Casa\neth0:ethernet:unavailable:--\nlo:loopback:unmanaged:--")
check("wifi y cable, sin loopback", disp == [
    {"dispositivo": "wlan0", "tipo": "wifi", "estado": "connected", "conexion": "Casa"},
    {"dispositivo": "eth0", "tipo": "ethernet", "estado": "unavailable", "conexion": ""},
], f"-> {disp}")

print("\n" + ("FALLARON: " + ", ".join(fallos) if fallos else "TODO OK"))
sys.exit(1 if fallos else 0)
