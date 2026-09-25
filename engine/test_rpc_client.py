"""Prueba del cliente RPC contra un servidor que emula el protocolo real de Guitarix.

Replica las particularidades verificadas en jsonrpc.cpp:
  - mensajes JSON delimitados por \n
  - sin `id` => notificacion, no se responde
  - parametros por nombre => error -32000
  - el id de respuesta siempre es string, aunque se lo pida como numero
    (verificado con socket crudo contra el motor real -- ver docs/mic-virtual.md
    y el fix en rpc_client.py). El mock lo reproduce a proposito: es lo que
    hubiera atrapado el bug de comparacion de tipos en llamar() antes de
    corregirlo.

Se ejecuta como modulo (python -m engine.test_rpc_client) para que el
import relativo funcione igual en Windows y en Linux/WSL2.
"""
import json
import socket
import threading
import time

from engine.rpc_client import GuitarixRPC, GuitarixError

RESULTADOS = {
    "getversion": "0.46.0",
    "getstate": "running",
    "jack_cpu_load": 12.5,
    # Formato real de `banks` (verificado contra 0.47.0).
    "banks": [{"name": "Rock", "mutable": 1, "type": "file", "presets": ["Crunch", "Lead"]},
              {"name": "Blues", "mutable": 1, "type": "file", "presets": []}],
}

recibidos = []          # todo lo que llego al servidor
rack_orden = ["ampstack"]   # estado del rack, mutado por insert_rack_unit/remove_rack_unit
PUERTO = 17000


def servidor(listo, parar):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", PUERTO))
    srv.listen(1)
    listo.set()
    conn, _ = srv.accept()
    buf = b""
    while not parar.is_set():
        try:
            conn.settimeout(0.3)
            trozo = conn.recv(4096)
        except socket.timeout:
            continue
        if not trozo:
            break
        buf += trozo
        while b"\n" in buf:
            linea, buf = buf.split(b"\n", 1)
            msg = json.loads(linea.decode())
            recibidos.append(msg)
            metodo = msg.get("method")
            params = msg.get("params")

            # Guitarix rechaza parametros por nombre
            if isinstance(params, dict):
                resp = {"jsonrpc": "2.0", "id": str(msg.get("id")),
                        "error": {"code": -32000,
                                  "message": "by-name parameters not implemented"}}
                conn.sendall(json.dumps(resp).encode() + b"\n")
                continue

            if "id" not in msg:
                # notificacion: no se responde.
                # Al recibir `listen` empujamos un evento, como hace el motor real.
                if metodo == "listen":
                    ev = {"jsonrpc": "2.0", "method": "preset_changed",
                          "params": ["Rock", "Crunch"]}
                    conn.sendall(json.dumps(ev).encode() + b"\n")
                elif metodo == "insert_rack_unit":
                    unidad = params[0]
                    if unidad not in rack_orden:
                        rack_orden.append(unidad)
                elif metodo == "remove_rack_unit":
                    unidad = params[0]
                    if unidad in rack_orden:
                        rack_orden.remove(unidad)
                continue

            if metodo == "metodo_inexistente":
                resp = {"jsonrpc": "2.0", "id": str(msg["id"]),
                        "error": {"code": -32601, "message": "Method not found"}}
            elif metodo == "get_rack_unit_order":
                resp = {"jsonrpc": "2.0", "id": str(msg["id"]), "result": list(rack_orden)}
            else:
                # Guitarix real siempre devuelve el id como string, aunque
                # se lo mande como numero -- verificado con socket crudo.
                # Reproducirlo aca es lo que hubiera atrapado el bug de
                # comparacion de tipos en llamar().
                resp = {"jsonrpc": "2.0", "id": str(msg["id"]),
                        "result": RESULTADOS.get(metodo)}
            conn.sendall(json.dumps(resp).encode() + b"\n")
    conn.close()
    srv.close()


def main():
    listo, parar = threading.Event(), threading.Event()
    hilo = threading.Thread(target=servidor, args=(listo, parar), daemon=True)
    hilo.start()
    listo.wait(5)

    fallos = []

    def check(nombre, ok, detalle=""):
        print(f"  {'OK  ' if ok else 'FALLA'}  {nombre}{'  ' + detalle if detalle else ''}")
        if not ok:
            fallos.append(nombre)

    with GuitarixRPC("127.0.0.1", PUERTO, timeout=5.0) as gx:
        print("\n1. Llamadas con resultado")
        check("version()", gx.version() == "0.46.0")
        check("estado()", gx.estado() == "running")
        check("carga_cpu()", gx.carga_cpu() == 12.5)
        check("bancos()", [b["name"] for b in gx.bancos()] == ["Rock", "Blues"])

        print("\n2. Parametros posicionales (nunca por nombre)")
        gx.presets("Rock")
        ultimo = recibidos[-1]
        check("params es array", isinstance(ultimo["params"], list),
              f"-> {ultimo['params']}")

        print("\n3. Notificaciones sin round-trip")
        antes = len(recibidos)
        gx.set_preset("Rock", "Crunch")
        time.sleep(0.2)
        env = [m for m in recibidos[antes:] if m.get("method") == "setpreset"][-1]
        check("setpreset sin id", "id" not in env)
        check("setpreset params", env["params"] == ["Rock", "Crunch"])

        print("\n3b. Preset inexistente: NO se manda (Guitarix hace segfault con eso)")
        for banco, preset in [("Factory", "Clean"), ("Rock", "NoExiste")]:
            antes = len(recibidos)
            try:
                gx.set_preset(banco, preset)
                check(f"ValueError con {banco}/{preset}", False)
            except ValueError:
                check(f"ValueError con {banco}/{preset}", True)
            time.sleep(0.1)
            check(f"{banco}/{preset} nunca llega al motor",
                  not any(m.get("method") == "setpreset" for m in recibidos[antes:]))

        print("\n4. Eventos del motor")
        gx.suscribir("preset")
        time.sleep(0.3)
        eventos = list(gx.eventos(timeout=1.0))
        check("recibe preset_changed",
              any(e.get("method") == "preset_changed" for e in eventos),
              f"-> {len(eventos)} evento(s)")

        print("\n5. Token invalido rechazado en cliente")
        try:
            gx.suscribir("token_que_no_existe")
            check("ValueError", False)
        except ValueError:
            check("ValueError", True)

        print("\n6. Error del servidor")
        try:
            gx.llamar("metodo_inexistente")
            check("GuitarixError", False)
        except GuitarixError as e:
            check("GuitarixError", e.codigo == -32601, f"-> {e}")

        print("\n7. Notificacion intercalada no se pierde")
        # Llega un evento mientras esperamos un resultado: debe quedar encolado.
        gx.suscribir("preset")          # el server empuja preset_changed
        v = gx.version()                # ...y aca pedimos un resultado
        check("resultado correcto", v == "0.46.0")
        pendientes = list(gx.eventos(timeout=0.5))
        check("evento encolado",
              any(e.get("method") == "preset_changed" for e in pendientes),
              f"-> {len(pendientes)} pendiente(s)")

        print("\n8. cargar_nam() deja el modelo sonando, no solo cargado")
        # Verificado contra un motor real (23/09/2026): loadpath/flist solos no alcanzan, hace
        # falta ademas insertar la unidad en la cadena del rack. Este mock reproduce ese estado
        # (rack_orden) para que el test agarre una regresion si cargar_nam() deja de hacerlo.
        gx.cargar_nam("/una/carpeta", ranura="nam")
        time.sleep(0.1)
        check("nam quedo en la cadena del rack", "nam" in rack_orden, f"-> {rack_orden}")
        ultimo_on_off = [c for c in recibidos
                          if c.get("method") == "set" and c.get("params") and c["params"][0] == "nam.on_off"]
        check("prende nam.on_off", ultimo_on_off and ultimo_on_off[-1]["params"] == ["nam.on_off", 1],
              f"-> {ultimo_on_off}")

        print("\n9. cargar_nam() es idempotente: no duplica la unidad en el rack")
        gx.cargar_nam("/una/carpeta", ranura="nam")
        time.sleep(0.1)
        check("sigue habiendo una sola 'nam'", rack_orden.count("nam") == 1, f"-> {rack_orden}")

        print("\n10. Llamadas simultaneas desde varios hilos (como los endpoints de FastAPI)")
        # Bug real (25/09/2026): la PWA pide /estado y /grid en paralelo, los dos hilos
        # compartian el socket sin lock y uno se leia la respuesta del otro -> timeout -> 500.
        esperado = {"version": "0.46.0", "estado": "running", "carga_cpu": 12.5}
        errores = []

        def martillar():
            try:
                for _ in range(25):
                    for metodo, valor in esperado.items():
                        r = getattr(gx, metodo)()
                        if r != valor:
                            errores.append(f"{metodo} -> {r!r}")
            except Exception as exc:  # noqa: BLE001 -- se reporta como fallo del test
                errores.append(repr(exc))

        hilos = [threading.Thread(target=martillar) for _ in range(8)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(30)
        check("600 llamadas concurrentes, todas con su propia respuesta", not errores,
              f"-> {errores[:3]}")

    parar.set()
    print("\n" + ("FALLARON: " + ", ".join(fallos) if fallos else "TODO OK"))
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
