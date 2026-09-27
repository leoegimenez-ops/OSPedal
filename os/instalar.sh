#!/bin/bash
# Convierte un Debian 13 (trixie) recién instalado en PedalSistema.
#
#   sudo ./os/instalar.sh                 # compila Arquitec DSP (fork de Guitarix 0.47)
#   sudo ./os/instalar.sh --guitarix-debian   # usa el Guitarix 0.46 de Debian (más rápido)
#   sudo ./os/instalar.sh --sin-pantalla      # equipo sin monitor: solo tablet/celular
#   sudo ./os/instalar.sh --motor-generico    # motor para cualquier PC x86-64 (lo usa la imagen USB)
#
# Qué hace (se puede correr de nuevo sin romper nada):
#   1. Paquetes: audio (JACK), pantalla (cage + Chromium), red (NetworkManager + avahi), etc.
#   2. Usuario "pedal" (grupos audio/video/input/netdev) -- la app nunca corre como root.
#   3. La app en /opt/pedalsistema (copia de este repo) con su entorno Python.
#   4. El motor: Arquitec DSP compilado del fork, o el Guitarix de Debian.
#   5. Servicios: audio, app, pantalla y CPU en rendimiento; tiempo real para el grupo audio;
#      permisos justos (polkit) para apagar, reiniciar y manejar el Wi-Fi desde la pantalla.
#   6. Nombre en la red: pedalsistema.local (la tablet entra sin saber la IP).
set -euo pipefail

DESTINO=/opt/pedalsistema
USUARIO=pedal
REPO_APP=https://github.com/leoegimenez-ops/OSPedal.git
ORIGEN="$(cd "$(dirname "$0")/.." && pwd)"
MOTOR_DEBIAN=0
MOTOR_GENERICO=
PANTALLA=1
for arg in "$@"; do
  case "$arg" in
    --guitarix-debian) MOTOR_DEBIAN=1 ;;
    --sin-pantalla) PANTALLA=0 ;;
    --motor-generico) MOTOR_GENERICO=1 ;;
    *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
  esac
done
[ "$(id -u)" = 0 ] || { echo "Correr como administrador: sudo $0" >&2; exit 1; }
grep -q 'VERSION_CODENAME=trixie' /etc/os-release || echo "Aviso: probado en Debian 13 (trixie)."
paso() { echo; echo "==> $*"; }

paso "1/6 Paquetes"
export DEBIAN_FRONTEND=noninteractive
apt-get update
# La misma lista que usa la actualización (os/post-actualizacion.sh): no se desincronizan.
mapfile -t PAQUETES < <(sed 's/#.*//' "$ORIGEN/os/paquetes.txt" | xargs -n1)
if [ "$PANTALLA" = 0 ]; then
  mapfile -t PAQUETES < <(printf '%s\n' "${PAQUETES[@]}" | grep -vxE 'cage|chromium|seatd')
fi
[ "$MOTOR_DEBIAN" = 1 ] && PAQUETES+=(guitarix)
apt-get install -y --no-install-recommends "${PAQUETES[@]}"
mkdir -p /var/lib/pedalsistema
[ "$PANTALLA" = 0 ] && touch /var/lib/pedalsistema/sin-pantalla
[ "$MOTOR_DEBIAN" = 1 ] && touch /var/lib/pedalsistema/motor-debian

paso "2/6 Usuario $USUARIO"
if ! id "$USUARIO" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$USUARIO"
  passwd --delete "$USUARIO" >/dev/null     # sin clave: entra solo en la pantalla del equipo
fi
for g in audio video input render netdev plugdev; do
  getent group "$g" >/dev/null && usermod -aG "$g" "$USUARIO"
done

paso "3/6 La app en $DESTINO"
mkdir -p "$DESTINO"
if [ -d "$ORIGEN/.git" ]; then
  # Con el historial de git: es lo que permite actualizar y volver atrás (SYSTEM > Update).
  rsync -a --delete --exclude '.venv' --exclude 'config/' --exclude 'presets/setlists/' \
        --exclude 'models/nam/*' --exclude 'models/irs/*' --exclude 'models/aidax/*' \
        --exclude 'models/.cargados/' "$ORIGEN"/ "$DESTINO"/
else
  echo "Esta copia no tiene historial de git: se clona desde GitHub para poder actualizar."
  [ -d "$DESTINO/.git" ] || git clone "$REPO_APP" "$DESTINO"
fi
git -C "$DESTINO" remote set-url origin "$REPO_APP" 2>/dev/null || true
chown -R "$USUARIO:$USUARIO" "$DESTINO"
runuser -u "$USUARIO" -- python3 -m venv "$DESTINO/.venv"
runuser -u "$USUARIO" -- "$DESTINO/.venv/bin/pip" install -q -r "$DESTINO/server/requirements.txt" \
                                                       -r "$DESTINO/engine/requirements.txt"
chmod +x "$DESTINO/os/bin/"*

paso "4/6 Motor de audio"
if [ "$MOTOR_DEBIAN" = 1 ]; then
  echo "Guitarix de Debian: $(guitarix --version 2>/dev/null | head -1 || echo instalado)"
elif [ "$(cat /var/lib/pedalsistema/motor-version 2>/dev/null)" = "$(tr -d '[:space:]' < "$DESTINO/os/MOTOR_VERSION")" ]; then
  echo "Arquitec DSP ya instalado en la versión pedida."
else
  # La versión exacta del motor con la que se probó esta versión de la app (os/MOTOR_VERSION).
  PS_RAIZ="$DESTINO" "$DESTINO/os/bin/compilar-motor" ${MOTOR_GENERICO:+--generico}
fi

paso "5/6 Servicios, tiempo real y permisos"
install -m 644 "$DESTINO"/os/systemd/*.service /etc/systemd/system/
install -m 644 "$DESTINO/os/etc/security/limits.d/95-pedalsistema-audio.conf" /etc/security/limits.d/
install -m 644 "$DESTINO/os/etc/polkit-1/rules.d/50-pedalsistema.rules" /etc/polkit-1/rules.d/
install -m 644 "$DESTINO/os/etc/pam.d/pedalsistema-kiosk" /etc/pam.d/
systemctl daemon-reload 2>/dev/null || true    # armando la imagen (chroot) no hay systemd corriendo
systemctl enable pedalsistema-rendimiento.service pedalsistema-jack.service pedalsistema.service \
                 NetworkManager.service avahi-daemon.service
if [ "$PANTALLA" = 1 ]; then
  systemctl enable seatd.service pedalsistema-kiosk.service
  systemctl disable getty@tty1.service 2>/dev/null || true
  systemctl set-default graphical.target
else
  systemctl disable pedalsistema-kiosk.service 2>/dev/null || true
fi

paso "6/6 Nombre en la red"
hostnamectl set-hostname pedalsistema 2>/dev/null || echo pedalsistema > /etc/hostname
grep -q 'pedalsistema' /etc/hosts || echo "127.0.1.1 pedalsistema" >> /etc/hosts

paso "Verificando"
# Lo imprescindible para que el equipo suene. Mejor fallar acá con un mensaje claro que en el
# escenario con un servicio reiniciándose sin parar (pasó: la compilación del motor desinstaló jackd2).
faltan=()
for c in jackd guitarix; do command -v "$c" >/dev/null || faltan+=("$c"); done
[ "$PANTALLA" = 1 ] && for c in cage chromium; do command -v "$c" >/dev/null || faltan+=("$c"); done
[ -x "$DESTINO/.venv/bin/uvicorn" ] || faltan+=("$DESTINO/.venv/bin/uvicorn")
runuser -u "$USUARIO" -- "$DESTINO/.venv/bin/python" -c "import numpy, jack, fastapi" 2>/dev/null ||
  faltan+=("módulos de Python (numpy, jack, fastapi)")
if [ "${#faltan[@]}" -gt 0 ]; then
  echo "FALTA: ${faltan[*]}" >&2
  exit 1
fi
echo "OK: jackd, motor, app$([ "$PANTALLA" = 1 ] && echo ", pantalla")"

echo
echo "Listo. Reiniciá el equipo: arranca solo en la app."
echo "Desde la tablet o el celular (misma red): http://pedalsistema.local:8000/app/"
