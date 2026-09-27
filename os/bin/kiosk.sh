#!/bin/bash
# Pantalla del equipo: la misma app que el celular, a pantalla completa, sin barras.
# La lanza cage (compositor Wayland mínimo, una sola app) desde pedalsistema-kiosk.service.
#
# - Espera a que el servidor responda (arrancar el audio y los motores lleva unos segundos) y
#   mientras tanto no muestra un error de "no se puede conectar".
# - nice 10: la pantalla nunca le gana CPU al audio (docs/arquitectura.md: "la GUI no interfiere
#   con el audio").
# - Perfil propio del navegador en ~/.kiosk: sin "restaurar sesión", sin traducir, sin pellizcar.
# - Sin tráfico de fondo a Google (mensajería, componentes, sincronización): en un escenario no
#   sirve y le saca CPU y red al equipo.

URL="${PS_URL:-http://127.0.0.1:8000/app/}"
for _ in $(seq 1 120); do
  curl -s -m 2 -o /dev/null "http://127.0.0.1:8000/salud" && break
  sleep 1
done

exec nice -n 10 chromium \
  --kiosk "$URL" \
  --ozone-platform=wayland \
  --user-data-dir="$HOME/.kiosk" \
  --no-first-run \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-features=TranslateUI \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --touch-events=enabled \
  --check-for-update-interval=31536000 \
  --disable-background-networking \
  --disable-component-update \
  --disable-sync \
  --password-store=basic
