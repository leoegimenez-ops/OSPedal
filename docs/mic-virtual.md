# Micrófono virtual: posición, distancia y tipo

Mockup en vivo: el bloque **CAB** del Editor de Nodos ya tiene POSITION, DISTANCE y el selector
de tipo de mic. Seleccionalo y bajá al panel de parámetros —
**https://claude.ai/artifact/5sz1WM6dMB9PVdtNgD3Enw**. La vista previa ("graves +Xdb · corte de
agudos en Yhz") usa el mismo cálculo que `engine/mic_virtual.py` (espejado en JS en el mockup,
mismos números). Cargar una IR propia (categoría GABINETE → TUS IR) deshabilita POSITION y
DISTANCE automáticamente, igual que en Cortex Control.

## Lo que tiene Cortex Control (verificado en el manual oficial)

El bloque **Cab** de Cortex Control —distinto del bloque **IR Loader**— simula un micrófono
posicionable frente a un parlante virtual:

- **POSITION** y **DISTANCE**: perillas continuas, también arrastrables con el mouse sobre un
  gráfico 2D del parlante ("Microphones' position can also be controlled by dragging the
  microphones to the desired spot with the mouse").
- **MIC**: combo box para elegir el modelo de micrófono simulado (el manual muestra ejemplos
  reales: *Dynamic 57*, *Ribbon 160*).
- Hasta **dos micrófonos simultáneos**, cada uno con su propia posición/distancia, mezclables.
- PHASE, HPF, LPF, OUTPUT VOLUME.

Un detalle que el propio manual aclara y que es clave para entender el diseño: **"POSITION and
DISTANCE knobs are disabled when loading custom IR files"**. El modelado de micrófono solo existe
para el Cab *simulado* de fábrica. Al cargar una IR de terceros se pasa al bloque **IR Loader**,
mucho más simple (LEVEL, HI/LOW PASS, PAN, DELAY, mezcla de reverb de sala) — sin posición ni
distancia, porque esa información ya quedó fija en el archivo en el momento de la captura.

## Lo que tiene Guitarix: nada

Verificado en el código fuente (`gx_convolver.h`, `gx_jconv_settings.h`): el convolver de
Guitarix es un motor de convolución de IR estática con una ventana de edición del archivo
(delay, offset, length, corrección de ganancia, selección de canal L/R/suma) — herramientas para
*recortar* una IR ya grabada, no para simular la posición de un micrófono virtual. No hay ningún
parámetro de posición, distancia ni tipo de micrófono en el motor.

## La decisión: construir un modelo propio

Dos caminos posibles, con costos muy distintos:

1. **Simulación acústica 3D completa**: modelar el patrón de radiación real del parlante
   (direccional, depende de la frecuencia) y el patrón polar del micrófono en el espacio. Es
   correcto en el sentido pleno, pero es un proyecto de DSP en sí mismo — semanas de trabajo,
   necesita datos de radiación de parlantes reales.
2. **Aproximación por EQ** (elegido acá): en vez de simular la física, se aproxima el *efecto*
   perceptual con un par de filtros dirigidos por posición/distancia/tipo de mic. Mucho más
   barato de construir, reutiliza el bloque EQ que el motor ya tiene, y es exactamente el tipo de
   compromiso razonable para un v1 — se puede reemplazar después por algo más sofisticado sin
   tocar el resto del sistema, porque la interfaz (`calcular()`) no depende de cómo se implemente
   por dentro.

## Los tres hechos físicos en los que se apoya

No son números inventados — cada uno tiene una fuente:

1. **Posición centro→borde del cono apaga los agudos progresivamente.** Consistente entre
   múltiples fuentes de audio profesional sobre mic'ing de gabinetes: apuntar al centro del
   dust cap da el tono más brillante y agresivo; moverse hacia el borde oscurece y engrosa la
   mitad, de forma gradual, no como un interruptor.
2. **Proximity effect**: boost de graves cuando el mic está cerca de la fuente, de hasta ~16dB
   por debajo de 100Hz. Es fuerte en cardioide y muy fuerte en cinta ("ribbon microphones are the
   most sensitive [to proximity effect]"), y casi inexistente en omnidireccional. Cae rápido con
   la distancia — es un efecto de cercanía extrema (pulgadas), no algo que decaiga linealmente en
   metros.
3. **Ley del inverso del cuadrado**: -6dB de nivel por cada duplicación de distancia en campo
   lejano. Deliberadamente **no** se usa esto para bajar el volumen automáticamente — ver más
   abajo por qué.

## Por qué DISTANCIA no toca el volumen

Sería un error de interfaz: el usuario ya tiene un knob LEVEL para el volumen. Si DISTANCIA
*también* bajara el volumen, mover esa perilla buscando un cambio de carácter tonal haría que el
sonido se apague de forma confusa, sin que sea evidente por qué. En el modelo, DISTANCIA solo
cambia el carácter (menos graves de proximidad, un poco más de mezcla de sala), nunca el nivel
general — mismo criterio de diseño que ya tiene Cortex Control (LEVEL y DISTANCE son controles
independientes).

## El modelo: `engine/mic_virtual.py`

```python
from engine.mic_virtual import calcular, aplicar

calcular(posicion=0.3, distancia=0.1, tipo="cinta")
# {'tipo_mic': 'Cinta (figura de 8)', 'pasabajos_hz': 6100,
#  'graves_shelf_hz': 150, 'graves_shelf_db': 10.7, 'reverb_wet_sugerido': 0.015}

aplicar(rpc, posicion=0.3, distancia=0.1, tipo="cinta")   # empuja al motor por RPC
```

Tres tipos de mic, cada uno con su propio rango de brillo y de proximity effect, anclados en el
orden que documenta la física real (verificado con tests, no solo declarado):

| Tipo | Proximity effect máx. | Brillo en el centro del cono |
|---|---|---|
| Cinta (figura de 8) | 16 dB (el más fuerte) | 7 kHz (el más oscuro) |
| Dinámico (cardioide) | 10 dB | 9 kHz |
| Condensador (omni) | 3 dB (casi nulo) | 12 kHz (el más brillante) |

## El EQ real de Guitarix (verificado contra el motor, 22/09/2026)

WSL2 + Debian 13 ya permite compilar y correr Guitarix de verdad (ver `docs/guitarix-integracion.md`).
Con el motor corriendo, `queryunit eq` mostró la estructura real — y corrigió una suposición:

**Es de 4 bandas *peak* fijas, sin ningún tipo shelf.** Los parámetros reales son
`eq.peakN` (frecuencia, 20–22000 Hz), `eq.levelN` (ganancia, −50 a 50 dB) y `eq.bandwidthN`
(ancho), para N de 1 a 4. La banda 1 se llama "Sub" en la propia interfaz del motor — ya pensada
para graves — lo que la hace perfecta para el boost de proximidad.

`aplicar()` quedó corregido: usa `peak1`/`level1` para el boost de graves (ganancia directa en dB,
sin conversión) y aproxima el oscurecimiento por posición como un **recorte en la banda 4**
(`corte_agudos_db`, hasta −10dB) en vez de barrer una frecuencia de corte — no hay low-pass real
que mover con un EQ solo-peak.

**Verificado de punta a punta contra el motor real:**

```python
aplicar(gx, posicion=0.7, distancia=0.1, tipo="cinta")
# -> {'graves_shelf_hz': 150, 'graves_shelf_db': 10.7, 'corte_agudos_hz': 6000, 'corte_agudos_db': -7.0, ...}

gx.obtener('eq.peak1', 'eq.level1', 'eq.peak4', 'eq.level4')
# -> {'eq.peak1': 150, 'eq.level1': 10.7, 'eq.peak4': 6000, 'eq.level4': -7}
```

Coincide exacto: lo que calcula `calcular()` es lo que Guitarix confirma tener puesto.

## Qué está verificado y qué no

**Verificado con 22 tests** (`test_mic_virtual.py`): la función es monótona (moverse hacia el
borde siempre oscurece, nunca al revés; alejarse siempre reduce el proximity effect, nunca lo
aumenta), los límites son exactos en los extremos, el orden entre tipos de mic respeta la física
citada arriba, los valores fuera de rango se recortan sin romper, y `aplicar()` manda los
parámetros reales del motor (`eq.peak1/level1/peak4/level4`).

**Verificado además contra un Guitarix real corriendo** (no solo un mock): los parámetros
existen con esos nombres, aceptan estos valores, y se pueden leer de vuelta idénticos.

**Lo único que sigue sin poder verificarse:**

- **Que suene bien.** Esto es matemática internamente consistente y aplicada correctamente al
  motor, no un resultado afinado por oído. Eso requiere escuchar audio real saliendo de una
  interfaz real — WSL2 no tiene hardware de audio, así que esta prueba específica sigue esperando
  el hardware físico.

## Camino a futuro: morphing de múltiples IRs

Si en algún momento se consigue (o se graba) un set de IRs reales variando posición y distancia
de forma sistemática, un camino más fiel que la aproximación por EQ sería interpolar/crossfadear
entre las IRs más cercanas al punto pedido, en vez de aproximar el efecto con filtros. Es un
proyecto más grande (necesita datos de captura reales, no solo matemática), pero la interfaz
pública de este módulo (`calcular()`) está pensada para no tener que cambiar del lado de quien la
llama si el día de mañana se reemplaza la implementación interna por eso.
