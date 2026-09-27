#!/bin/bash
# Convierte un Debian 13 (trixie) recién instalado en PedalSistema.
#
#   sudo ./os/instalar.sh                 # compila Arquitec DSP (fork de Guitarix 0.47)
#   sudo ./os/instalar.sh --guitarix-debian   # usa el Guitarix 0.46 de Debian (más rápido)
#   sudo ./os/instalar.sh --sin-pantalla      # equipo sin monitor: solo tablet/celular
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
REPO_MOTOR=https://github.com/egimenez-bot/arquitec-dsp.git
ORIGEN="$(cd "$(dirname "$0")/.." && pwd)"
MOTOR_DEBIAN=0
PANTALLA=1
for arg in "$@"; do
  case "$arg" in
    --guitarix-debian) MOTOR_DEBIAN=1 ;;
    --sin-pantalla) PANTALLA=0 ;;
    *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
  esac
done
[ "$(id -u)" = 0 ] || { echo "Correr como administrador: sudo $0" >&2; exit 1; }
grep -q 'VERSION_CODENAME=trixie' /etc/os-release || echo "Aviso: probado en Debian 13 (trixie)."
paso() { echo; echo "==> $*"; }

paso "1/6 Paquetes"
export DEBIAN_FRONTEND=noninteractive
apt-get update
PAQUETES=(jackd2 alsa-utils python3-venv python3-pip git curl rsync network-manager avahi-daemon
          polkitd dbus fonts-inter)
[ "$PANTALLA" = 1 ] && PAQUETES+=(cage chromium seatd)
[ "$MOTOR_DEBIAN" = 1 ] && PAQUETES+=(guitarix)
apt-get install -y --no-install-recommends "${PAQUETES[@]}"

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
rsync -a --delete --exclude '.venv' --exclude 'config/' --exclude 'presets/setlists/' \
      --exclude 'models/nam/*' --exclude 'models/irs/*' --exclude 'models/aidax/*' \
      "$ORIGEN"/ "$DESTINO"/
chown -R "$USUARIO:$USUARIO" "$DESTINO"
sudo -u "$USUARIO" python3 -m venv "$DESTINO/.venv"
sudo -u "$USUARIO" "$DESTINO/.venv/bin/pip" install -q -r "$DESTINO/server/requirements.txt" \
                                                       -r "$DESTINO/engine/requirements.txt"
chmod +x "$DESTINO/os/bin/"*

paso "4/6 Motor de audio"
if [ "$MOTOR_DEBIAN" = 1 ]; then
  echo "Guitarix de Debian: $(guitarix --version 2>/dev/null | head -1 || echo instalado)"
elif command -v guitarix >/dev/null && guitarix --version 2>/dev/null | grep -q '0\.47'; then
  echo "Arquitec DSP ya instalado."
else
  # Fuentes de Debian para traer las dependencias de compilación de Guitarix.
  if [ -f /etc/apt/sources.list.d/debian.sources ] && ! grep -q 'deb-src' /etc/apt/sources.list.d/debian.sources; then
    sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/debian.sources
    apt-get update
  fi
  apt-get build-dep -y guitarix
  mkdir -p /usr/local/src
  [ -d /usr/local/src/arquitec-dsp ] || git clone --depth 1 "$REPO_MOTOR" /usr/local/src/arquitec-dsp
  cd /usr/local/src/arquitec-dsp/trunk
  # Mismas opciones con las que se compiló y verificó en desarrollo (build/config.log).
  ./waf configure --prefix=/usr --includeresampler --includeconvolver --optimization
  ./waf build -j"$(nproc)"
  ./waf install
  cd - >/dev/null
fi

paso "5/6 Servicios, tiempo real y permisos"
install -m 644 "$DESTINO"/os/systemd/*.service /etc/systemd/system/
install -m 644 "$DESTINO/os/etc/security/limits.d/95-pedalsistema-audio.conf" /etc/security/limits.d/
install -m 644 "$DESTINO/os/etc/polkit-1/rules.d/50-pedalsistema.rules" /etc/polkit-1/rules.d/
install -m 644 "$DESTINO/os/etc/pam.d/pedalsistema-kiosk" /etc/pam.d/
systemctl daemon-reload
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
hostnamectl set-hostname pedalsistema
grep -q 'pedalsistema' /etc/hosts || echo "127.0.1.1 pedalsistema" >> /etc/hosts

echo
echo "Listo. Reiniciá el equipo: arranca solo en la app."
echo "Desde la tablet o el celular (misma red): http://pedalsistema.local:8000/app/"
