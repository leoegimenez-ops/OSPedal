#!/bin/bash
# Después de cambiar de versión (lo corre os/bin/actualizar, como root, con el código NUEVO ya
# puesto). Deja el sistema como lo necesita esa versión. Se puede correr de nuevo sin romper nada.
#
#   - Servicios, permisos, límites de tiempo real: si cambiaron, se reinstalan.
#   - Paquetes de Debian (os/paquetes.txt): instala los que falten.
#   - Motor (os/MOTOR_VERSION): si esta versión pide otro commit de Arquitec DSP, lo compila.
#     Tarda (varios minutos); el actualizador espera.
#
# PS_RAIZ: dónde está el programa (default /opt/pedalsistema).
set -euo pipefail
RAIZ="${PS_RAIZ:-/opt/pedalsistema}"
ESTADO_DIR=/var/lib/pedalsistema
REPO_MOTOR=https://github.com/egimenez-bot/arquitec-dsp.git
mkdir -p "$ESTADO_DIR"

# 1. Servicios y configuración del sistema
cambiado=0
copiar() {   # copiar ORIGEN DESTINO_DIR  (solo si difiere)
  local destino="$2/$(basename "$1")"
  if ! cmp -s "$1" "$destino"; then
    install -m 644 "$1" "$destino"
    cambiado=1
    echo "actualizado: $destino"
  fi
}
for u in "$RAIZ"/os/systemd/*.service; do copiar "$u" /etc/systemd/system; done
copiar "$RAIZ/os/etc/security/limits.d/95-pedalsistema-audio.conf" /etc/security/limits.d
copiar "$RAIZ/os/etc/polkit-1/rules.d/50-pedalsistema.rules" /etc/polkit-1/rules.d
copiar "$RAIZ/os/etc/pam.d/pedalsistema-kiosk" /etc/pam.d
chmod +x "$RAIZ"/os/bin/* "$RAIZ"/os/*.sh
if [ "$cambiado" = 1 ]; then
  systemctl daemon-reload
fi

# 2. Paquetes que falten (sin los de pantalla si el equipo se instaló sin pantalla)
faltan=()
while read -r p; do
  p="${p%%#*}"; p="$(echo "$p" | xargs)"
  [ -z "$p" ] && continue
  if [ -f "$ESTADO_DIR/sin-pantalla" ] && [[ "$p" =~ ^(cage|chromium|seatd)$ ]]; then continue; fi
  dpkg -s "$p" >/dev/null 2>&1 || faltan+=("$p")
done < "$RAIZ/os/paquetes.txt"
if [ "${#faltan[@]}" -gt 0 ]; then
  echo "instalando: ${faltan[*]}"
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${faltan[@]}"
fi

# 3. Motor
pedido="$(tr -d '[:space:]' < "$RAIZ/os/MOTOR_VERSION")"
instalado="$(cat "$ESTADO_DIR/motor-version" 2>/dev/null || true)"
if [ -f "$ESTADO_DIR/motor-debian" ]; then
  echo "motor: Guitarix de Debian (no se compila)"
elif [ "$pedido" != "$instalado" ]; then
  echo "motor: compilando Arquitec DSP $pedido (antes: ${instalado:-ninguno})"
  mkdir -p /usr/local/src
  [ -d /usr/local/src/arquitec-dsp/.git ] || git clone "$REPO_MOTOR" /usr/local/src/arquitec-dsp
  cd /usr/local/src/arquitec-dsp
  git fetch --quiet origin
  git checkout --quiet --detach "$pedido"
  cd trunk
  ./waf configure --prefix=/usr --includeresampler --includeconvolver --optimization
  ./waf build -j"$(nproc)"
  ./waf install
  echo "$pedido" > "$ESTADO_DIR/motor-version"
fi
echo "post-actualización: listo"
