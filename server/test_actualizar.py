"""Pruebas de punta a punta de las actualizaciones, con repos de git reales en carpetas temporales:

- un "GitHub" (repo bare), la copia del "equipo" y una copia de "trabajo" donde se marcan versiones;
- una app falsa que responde /sistema/version con la versión que tiene el equipo, y que NO arranca
  (error 500) si la versión está rota a propósito;
- el actualizador real (os/bin/actualizar) y los endpoints reales de server/sistema.py.

Comprueba: actualizar a una versión buena; vuelta atrás automática con una versión rota; no tocar
un equipo con archivos modificados; el canal estable nunca ofrece bajar de versión; y la
actualización sin internet con un paquete de pendrive.

Se ejecuta: .venv/bin/python -m server.test_actualizar
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

fallos = []


def check(nombre, ok, detalle=""):
    print(f"  {'OK  ' if ok else 'FALLA'}  {nombre}{'  ' + detalle if detalle else ''}")
    if not ok:
        fallos.append(nombre)


RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
ACTUALIZADOR = RAIZ_PROYECTO / "os" / "bin" / "actualizar"
tmp = Path(tempfile.mkdtemp(prefix="actualizar_test_"))
origen, equipo, trabajo = tmp / "github.git", tmp / "equipo", tmp / "trabajo"


def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {args}: {r.stderr}")
    return r.stdout.strip()


def version_marcada(tag, contenido):
    (trabajo / "estado.txt").write_text(contenido)
    git(trabajo, "add", "-A")
    git(trabajo, "commit", "-q", "-m", f"version {tag}")
    if tag:
        git(trabajo, "tag", tag)


subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origen)], check=True)
subprocess.run(["git", "clone", "-q", str(origen), str(trabajo)], check=True, capture_output=True)
git(trabajo, "config", "user.email", "test@test")
git(trabajo, "config", "user.name", "test")
for sub in ("server", "engine"):
    (trabajo / sub).mkdir()
    (trabajo / sub / "requirements.txt").write_text("")
(trabajo / ".gitignore").write_text("config/\n")
version_marcada("v0.1.0", "ok")
version_marcada("v0.2.0", "ok, version 2")
version_marcada("v0.3.0", "ROTO")          # esta versión no arranca
git(trabajo, "push", "-q", "origin", "main", "--tags")
subprocess.run(["git", "clone", "-q", str(origen), str(equipo)], check=True, capture_output=True)
git(equipo, "checkout", "-q", "--detach", "v0.1.0")


class AppFalsa(BaseHTTPRequestHandler):
    """Hace de la app instalada: responde con la versión del equipo, o no arranca si está rota."""
    def do_GET(self):  # noqa: N802
        if "ROTO" in (equipo / "estado.txt").read_text():
            self.send_response(500); self.end_headers(); return
        cuerpo = json.dumps({"commit": git(equipo, "rev-parse", "--short", "HEAD")}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *_):
        pass


servidor = HTTPServer(("127.0.0.1", 0), AppFalsa)
threading.Thread(target=servidor.serve_forever, daemon=True).start()
ESTADO = tmp / "config" / "actualizacion.json"
ENTORNO = {**os.environ, "PS_RAIZ": str(equipo), "PS_URL_SALUD": f"http://127.0.0.1:{servidor.server_port}/",
           "PS_CMD_REINICIO": "true", "PS_ESPERA": "6", "PS_SIN_POST": "1",
           "PS_ESTADO_ACTUALIZACION": str(ESTADO)}


def actualizar_a(destino):
    r = subprocess.run([sys.executable, str(ACTUALIZADOR), "--destino", destino], env=ENTORNO,
                       capture_output=True, text=True, timeout=120)
    return r.returncode, json.loads(ESTADO.read_text())


print("\n1. Actualizar a una version buena")
rc, est = actualizar_a("v0.2.0")
check("termina bien y queda en v0.2.0", rc == 0 and est["estado"] == "ok"
      and git(equipo, "describe", "--tags") == "v0.2.0", f"-> rc={rc} {est.get('estado')} {est.get('motivo')}")

print("\n2. Version rota: vuelve sola a la anterior")
rc, est = actualizar_a("v0.3.0")
check("detecta que no arranca y vuelve a v0.2.0", rc == 1 and est["estado"] == "revertida"
      and git(equipo, "describe", "--tags") == "v0.2.0", f"-> rc={rc} {est.get('estado')} {git(equipo, 'describe', '--tags')}")
check("deja escrito el motivo", "didn't start" in est.get("motivo", ""), f"-> {est.get('motivo')}")
check("el paso a paso queda registrado", any("Going back" in p["texto"] for p in est["pasos"]))

print("\n3. Archivos del programa modificados en el equipo: no actualiza")
(equipo / "estado.txt").write_text("tocado a mano")
rc, est = actualizar_a("v0.1.0")
check("no toca nada y lo explica", rc == 1 and "modified" in est.get("motivo", "")
      and (equipo / "estado.txt").read_text() == "tocado a mano", f"-> {est.get('motivo')}")
git(equipo, "checkout", "-q", "--", "estado.txt")
(equipo / "config").mkdir(exist_ok=True)
(equipo / "config" / "equipo.json").write_text("{}")         # datos del usuario (fuera de git)
rc, est = actualizar_a("v0.1.0")
check("los datos del usuario (config/) no cuentan como modificacion ni se tocan",
      rc == 0 and (equipo / "config" / "equipo.json").read_text() == "{}", f"-> {est.get('motivo')}")

print("\n4. Endpoints de SYSTEM > Update (canal estable / desarrollo)")
os.environ["PS_RAIZ_REPO"] = str(equipo)
os.environ["PS_ESTADO_ACTUALIZACION"] = str(ESTADO)
os.environ["PS_CONFIG"] = str(tmp / "config" / "equipo.json")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server import sistema  # noqa: E402

app = FastAPI()
app.include_router(sistema.router)
cli = TestClient(app)
git(equipo, "checkout", "-q", "--detach", "v0.2.0")
r = cli.post("/sistema/buscar_actualizacion").json()
check("estable en v0.2.0: ofrece la ultima marcada (v0.3.0) con su lista de cambios",
      r["hay"] and r["destino"] == "v0.3.0" and r["novedades"] == ["version v0.3.0"], f"-> {r}")
version_marcada("", "ok, trabajo sin marcar")
git(trabajo, "push", "-q", "origin", "main")
cli.post("/sistema/canal", json={"canal": "desarrollo"})
r = cli.post("/sistema/buscar_actualizacion").json()
check("desarrollo: ofrece lo ultimo de main", r["hay"] and r["destino"] == "origin/main" and r["cantidad"] == 2, f"-> {r}")
git(equipo, "checkout", "-q", "--detach", "origin/main")
cli.post("/sistema/canal", json={"canal": "estable"})
r = cli.post("/sistema/buscar_actualizacion").json()
check("volver a estable estando adelante: NO ofrece bajar de version", r["hay"] is False, f"-> {r}")
v = cli.get("/sistema/version").json()
check("version instalada y canal", v["canal"] == "estable" and v["version"].startswith("v0.3.0-1-g"), f"-> {v}")
r = cli.post("/sistema/actualizar", json={"destino": "v9.9.9"})
check("version inexistente: 400", r.status_code == 400)
r = cli.post("/sistema/actualizar", json={"destino": "v0.2.0"}, headers={"Cf-Connecting-Ip": "1.2.3.4"})
check("desde internet: 403", r.status_code == 403)

print("\n5. Sin internet: paquete de pendrive")
git(equipo, "checkout", "-q", "--detach", "v0.2.0")
git(equipo, "remote", "set-url", "origin", "/no/hay/internet")
version_marcada("v0.4.0", "ok, version 4")
paquete = tmp / "PedalSistema-v0.4.0.bundle"
r = subprocess.run(["bash", str(RAIZ_PROYECTO / "os" / "bin" / "crear-paquete-usb"), "v0.4.0", str(paquete)],
                   cwd=trabajo, capture_output=True, text=True,
                   env={**os.environ, "GIT_DIR": str(trabajo / ".git")})
check("crear el paquete", paquete.exists(), f"-> {r.stdout} {r.stderr}")
r = cli.post("/sistema/buscar_actualizacion")
check("sin internet, buscar da un error claro", r.status_code in (502, 504), f"-> {r.status_code}")
r = cli.post("/sistema/actualizacion_usb", content=paquete.read_bytes())
check("el paquete trae la v0.4.0", r.status_code == 200 and r.json()["destino"] == "v0.4.0", f"-> {r.text[:200]}")
r = cli.post("/sistema/actualizacion_usb", content=b"cualquier cosa")
check("un archivo que no es un paquete: 400", r.status_code == 400)
rc, est = actualizar_a("v0.4.0")
check("y se instala con el mismo actualizador", rc == 0 and git(equipo, "describe", "--tags") == "v0.4.0",
      f"-> {est.get('estado')} {est.get('motivo')}")

servidor.shutdown()
print("\n" + ("FALLARON: " + ", ".join(fallos) if fallos else "TODO OK"))
sys.exit(1 if fallos else 0)
