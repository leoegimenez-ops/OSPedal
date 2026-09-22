# Mockups de interfaz

Artifact interactivo (Play para navegar, los controles funcionan de verdad):
**https://claude.ai/artifact/5sz1WM6dMB9PVdtNgD3Enw**

## Pantallas

| Pantalla | Qué muestra |
|---|---|
| Modo Preset | Vista de escenario: nombre del preset, banco, efectos activos |
| Modo Stomp | 8 pedales tocables, prenden/apagan de verdad |
| Modo Scene | Escenas del preset con el diff de parámetros que cada una aplica |
| Afinador | Pantalla completa, aguja de cents, las 6 cuerdas |
| Dispositivos | Selección de interfaz de audio y controlador MIDI, sin drivers |
| **Editor de Cadena** | Cómo se arma un preset: cadena de bloques + editor de parámetros |
| **Explorador de Presets** | Navegador Setlist › Banco › Preset |

Las últimas dos surgieron de investigar Cortex Control (Neural DSP) — ver
`docs/investigacion-neural-dsp.md` para el detalle de esa investigación y qué se adoptó.

## Identidad visual

- **Fondo**: casi negro (`#0D0D0F`), pensado para escenario oscuro.
- **Tipografía**: Archivo (interfaz) + IBM Plex Mono (datos técnicos: ids de parámetro, BPM, CPU).
- **Acento**: ámbar `#FFA724` por defecto, tweakable en cada artboard.
- **Verde de estado**: `#3DD68C` para latencia/conexión OK, reutilizado del "ACTIVE" verde que
  Cortex Control usa para selección — es un patrón común, no algo tomado de ellos puntualmente.

## Color por tipo de unidad de Guitarix

Inspirado en el patrón de Cortex Control (color fijo por categoría, consistente en toda la app),
con paleta propia:

| Categoría | Color | Unidades de ejemplo |
|---|---|---|
| Overdrive | `#FFA724` (ámbar) | tubescreamer |
| Dinámica | `#8B93A8` (gris azulado) | comp |
| Amplificador | `#FF6B5C` (rojo cálido) | amp |
| Gabinete | `#B98CFF` (violeta) | cab |
| Ecualizador | `#5AA9FF` (azul) | eq |
| Modulación | `#5FD9A4` (verde) | chorus |
| Delay | `#3DD8D0` (cian) | echo |
| Reverb | `#3DD68C` (verde azulado) | freeverb |

Estos colores están hardcodeados en `Editor.dc.html` como mockup. Cuando se implemente la GUI
real (Fase 4), conviene llevarlos a una constante compartida (`gui/paleta.py` o similar) para
que la app y cualquier documentación usen los mismos valores.

## Decisiones que quedan abiertas

- **Editor de Cadena** asume una sola fila de 8 unidades. Guitarix soporta rutas paralelas
  (splitter/mixer, como el propio Cortex Control) — el mockup no cubre ese caso todavía.
  `engine/rpc_client.py` ya puede leer `get_rack_unit_order`, así que el dato está disponible
  cuando se decida el diseño de rutas paralelas.
- Los ids de parámetro que aparecen en el Editor (`tubescreamer.drive`, `echo.feedback`, etc.)
  son plausibles pero no están verificados contra el motor real — a diferencia de
  `amp.stage1.gain` y `<unidad>.on_off`, que sí están confirmados en
  `docs/guitarix-integracion.md`. Falta correr `parameterlist` contra un Guitarix real para
  confirmar los nombres exactos de cada unidad.
