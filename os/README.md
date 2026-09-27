# PedalSistema — el sistema operativo

El equipo arranca directo en la app: la **misma** que se usa desde la tablet o el celular, a
pantalla completa, con una pestaña **SYSTEM** extra que solo aparece en la pantalla del propio
equipo (conectar dispositivos con QR, audio, pedalera MIDI, archivos IR/NAM, Wi-Fi, estado,
actualizaciones, apagar).

## Instalar

Sobre un Debian 13 (trixie) recién instalado, con este repo copiado:

```
sudo ./os/instalar.sh                    # compila Arquitec DSP (fork de Guitarix 0.47)
sudo ./os/instalar.sh --guitarix-debian  # o usa el Guitarix 0.46 de Debian
sudo ./os/instalar.sh --sin-pantalla     # equipo sin monitor (solo tablet/celular)
```

Al reiniciar, arranca solo. Desde la tablet: `http://pedalsistema.local:8000/app/` o escaneando
el QR de SYSTEM › Connect a device.

## Qué corre

| Servicio | Qué hace |
|---|---|
| `pedalsistema-rendimiento` | CPU a máxima frecuencia (sin cortes a latencias bajas) |
| `pedalsistema-jack` | Servidor de audio con la interfaz/frecuencia/buffer de SYSTEM › Audio (`os/bin/arrancar-jack`) |
| `pedalsistema` | La app, los motores (un Guitarix por instrumento y tramo), mezcla y pedalera MIDI |
| `pedalsistema-kiosk` | La pantalla: `cage` + Chromium a pantalla completa, táctil y mouse (`os/bin/kiosk.sh`) |

- Todo corre como el usuario `pedal`, nunca como root. El grupo `audio` tiene tiempo real
  (`etc/security/limits.d`), y polkit le permite solo apagar/reiniciar, reiniciar sus propios
  servicios y manejar el Wi-Fi (`etc/polkit-1/rules.d`).
- La pantalla corre con `nice 10`: nunca le gana CPU al audio.
- Apagar, actualizar y cambiar la red solo se aceptan desde la pantalla del equipo (el servidor lo
  verifica); desde la red o internet responde 403.

## Estado

Escrito y revisado en la PC de desarrollo (WSL2): sintaxis de los servicios verificada con
`systemd-analyze verify`, el lanzador de JACK probado con `--dry-run`. **Falta probarlo en un
equipo real** (arranque, pantalla táctil, interfaz de audio): WSL2 no tiene pantalla ni placa de
sonido. El siguiente paso es armar la imagen booteable (USB) con esto adentro.
