# PedalSistema — el sistema operativo

El equipo arranca directo en la app: la **misma** que se usa desde la tablet o el celular, a
pantalla completa, con una pestaña **SYSTEM** extra que solo aparece en la pantalla del propio
equipo (conectar dispositivos con QR, audio, pedalera MIDI, archivos IR/NAM, Wi-Fi, estado,
actualizaciones, apagar).

## Pendrive booteable (la forma recomendada)

**Armar la imagen** (en Debian 13 o WSL2 con Debian 13, con `live-build`; ~40 min la primera vez):

```
sudo os/imagen/armar-imagen        # deja imagen-usb/PedalSistema-<versión>.iso (+ .sha256)
```

Usa el último commit del repo. Adentro corre el mismo `os/instalar.sh`, con el motor compilado
**genérico** (corre en cualquier PC x86-64 de 64 bits; al actualizar el motor en el equipo, se
recompila optimizado para ese procesador).

**Grabarla desde Windows con [Rufus](https://rufus.ie)** (versión portable, no se instala):

1. Elegir el pendrive y la ISO.
2. **Persistent partition size**: todo lo que se pueda (ej. 8 GB o más). Ahí se guardan presets,
   setlists, configuración, archivos IR/NAM y las actualizaciones. **Sin esa partición el equipo
   arranca igual pero olvida todo al apagarse** (la app lo avisa con una franja roja fija).
3. Si Rufus pregunta, modo **ISO** (no DD).

**Arrancar:** conectar el pendrive, encender y elegir el pendrive en el menú de arranque de la PC
(F12, F11, F8 o Esc según la marca). Arranca solo en la app. BIOS y UEFI; con Secure Boot
activado puede no arrancar: desactivarlo en el BIOS.

## Instalar sobre un Debian ya instalado

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
sonido.

**Imagen USB, probada en QEMU** (`os/imagen/probar-en-qemu`, procesador tipo Core 2 sin
SSE4.2/AVX, 2 GB): arranca sola por el menú de BIOS y de UEFI, la app y los motores andan en esa
CPU, JACK arranca con la placa HDA, guarda y recupera lo guardado tras apagar y prender, avisa
cuando el pendrive no tiene persistencia, y la pantalla muestra la app. **Falta probarla en un
equipo real** (placa de audio, pantalla táctil, Wi-Fi, latencia).
