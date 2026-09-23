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
    "banks": ["Rock", "Blues"],
}

recibidos = []          # todo lo que llego al servidor
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
                continue

            if metodo == "metodo_inexistente":
                resp = {"jsonrpc": "2.0", "id": str(msg["id"]),
                        "error": {"code": -32601, "message": "Method not found"}}
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
        check("bancos()", gx.bancos() == ["Rock", "Blues"])

        print("\n2. Parametros posicionales (nunca por nombre)")
        gx.presets("Rock")
        ultimo = recibidos[-1]
        check("params es array", isinstance(ultimo["params"], list),
              f"-> {ultimo['params']}")

        print("\n3. Notificaciones sin round-trip")
        antes = len(recibidos)
        gx.set_preset("Rock", "Crunch")
        time.sleep(0.2)
        env = recibidos[antes]
        check("setpreset sin id", "id" not in env)
        check("setpreset params", env["params"] == ["Rock", "Crunch"])

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

    parar.set()
    print("\n" + ("FALLARON: " + ", ".join(fallos) if fallos else "TODO OK"))
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
