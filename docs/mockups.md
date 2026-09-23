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
| **Editor de Nodos** | Sistema de nodos con splitter/mixer + Buscador de Sonido |
| **Explorador de Presets** | Navegador Setlist › Banco › Preset |
| **Tempo** | Tabs Global/Scene/Preset, tap tempo funcional, slider |
| **Global EQ** | 5 bandas paramétricas sobre eje logarítmico |
| **Gig View** | Editor de asignación de pedalera A–H (distinto de Modo Stomp) |
| **Capturar Equipo** | Flujo para entrenar un `.nam` de tu equipo físico con NAM |
| **MIDI Out** | Mensajes MIDI salientes por pedal y pedal de expresión |

Las últimas dos surgieron de investigar Cortex Control (Neural DSP) — ver
`docs/investigacion-neural-dsp.md` para el detalle de esa investigación y qué se adoptó.

## Editor de Nodos

Reemplaza la primera versión de una sola fila por un **sistema de nodos real**, como The Grid de
Cortex Control: dos filas conectadas por nodos **S** (splitter, divide la señal) y **M** (mixer,
la vuelve a juntar). Fila principal: TS → COMP → AMP → CAB. Loop paralelo (tiempo/espacio): EQ →
CHORUS → ECHO → FREEVERB. La geometría de los conectores está calculada a mano (no aproximada)
para que las líneas lleguen exactas al centro de cada nodo.

Cada bloque, al seleccionarlo, muestra sus parámetros con:

- **Steppers `−` / `+`** junto a cada perilla (mismo patrón que el BPM de Cortex Control).
- **Botón de aleatorizar** (dados) por bloque: mueve sus parámetros con un jitter de hasta ±20%
  para explorar variaciones sin perder el carácter general — pensado para "buscar mejores
  sonidos" tocando, no solo mirando números.
- **Bypass** funcional.

**Buscador de Sonido** (panel derecho, no existe en Cortex Control — es propio de PedalSistema):
cinco estilos de partida (Blues, Rock, Metal, Clean, Ambient), cada uno con su propio set de
valores para los 8 bloques y qué unidades bypassear. Un botón "Sorprendeme" elige uno al azar.
Al aplicar un estilo, tres barras (Drive / Espacio / Brillo) resumen su carácter. La idea:
en vez de partir de cero perilla por perilla, el músico arranca de un punto ya tocable y ajusta
desde ahí.

**Sidebar de categorías** (panel izquierdo, agregado a partir de una captura real de Cortex
Control): rail de códigos cortos (OD, DIN, AMP, CAB, EQ, MOD, DLY, RVB) + lista del rubro
abierto, igual al Device List real que ya habíamos documentado en
`docs/guitarix-integracion.md`. Elegir un ítem lo carga en el bloque correspondiente de la
cadena — el tile de la grilla queda genérico, pero el panel de parámetros muestra el nombre
específico con una etiqueta "PROPIO". Las categorías donde Guitarix realmente acepta archivos
(overdrive, dinámica, amp, cab) tienen una sección "TUS CAPTURAS · models/nam" o "TUS IR ·
models/irs" — conecta directo con `docs/capturas-neuronales.md`: es el lugar de la interfaz
donde aparecerían los `.nam`/`.aidax`/`.wav` que el usuario copie a esas carpetas.

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
| Overdrive | `#FFA724` (ámbar) | ts9sim |
| Dinámica | `#8B93A8` (gris azulado) | compressor |
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
- **Corregido (22/09/2026, aplicado 23/09/2026):** el mockup usaba los ids `tubescreamer.*` en
  algunos rótulos — verificado contra un Guitarix real corriendo que la unidad correcta es
  `ts9sim` (los nombres de parámetro `.drive`/`.level`/`.tone` ya eran correctos, solo el id de
  unidad estaba mal). Corregido en `Editor.dc.html` (los tres knobs del bloque overdrive) y en
  `Stomp.dc.html` (la etiqueta del pedal y el mapeo interno a `<unidad>.on_off`). Vive en el
  scratchpad de la sesión, no en este repo — falta publicarlo (requiere aprobar el permiso desde
  la PC, ver conversación del 23/09/2026). `compressor` ya estaba bien en todos los mockups; la
  mención anterior de un `comp.*` incorrecto era imprecisa, no había ningún parámetro con ese
  prefijo, solo un id de categoría interno (`comp`) sin relación con nombres de parámetro RPC.
  El resto de ids citados (`echo.feedback`, `amp.stage1.gain`, `<unidad>.on_off`) ya están
  confirmados contra el motor real en `docs/guitarix-integracion.md`
  y `docs/guitarix-rpc-methods.md`.
