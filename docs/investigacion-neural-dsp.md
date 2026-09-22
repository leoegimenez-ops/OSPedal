# Investigación: Cortex Control (Neural DSP)

Neural DSP Technologies fabrica el **Quad Cortex**, el hardware que ya usábamos como comparable
en la visión del proyecto ("reemplaza hardware como Quad Cortex/Helix"). Su app de escritorio
para armar presets, **Cortex Control**, es la referencia de interacción más directa que existe
para "cómo se construye un preset" — que es justo la pieza que le faltaba a PedalSistema.

Fuente principal: [manual de usuario oficial de Cortex Control v1.2.0](https://downloads.neuraldsp.com/file/cortex-control-installers/v_1.2.0/Cortex%20Control%20v1.2.0.pdf)
(65 páginas, leído completo). Fuentes secundarias:
[neuraldsp.com/cortex-control](https://neuraldsp.com/cortex-control),
[manual del Quad Cortex](https://neuraldsp.com/manual/quad-cortex),
[anuncio en Sweetwater](https://www.sweetwater.com/insync/neural-dsp-desktop-editor-for-quad-cortex-announcement/),
[Guitar.com sobre la beta](https://guitar.com/news/neural-dsp-open-beta-cortex-control-desktop-editor/).

**Nota de propiedad intelectual**: lo que sigue documenta el *patrón de interacción* de un
producto de un tercero, con fines de referencia. Los mockups de PedalSistema no clonan su
interfaz — usan colores, tipografía, iconos y datos propios. Ver `docs/mockups.md`.

## Estructura general de la app

Dos secciones principales, alternables con tabs: **GRID** y **DIRECTORY**. Barra de utilidades
fija abajo: `TUNER | TEMPO | TAP | MIDI | GIG VIEW | CPU%`.

## The Grid: cómo arman un preset

Es una grilla de **4 filas × 8 slots** donde los bloques se arman de izquierda a derecha. Cada
slot vacío, al tocarlo, abre un **Device List** categorizado (Amp, Cab, Overdrive, Delay...) del
que se elige o arrastra un bloque.

Interacciones documentadas:

- **Click** en un bloque: lo selecciona y abre su editor de parámetros debajo de la grilla.
- **Doble click**: lo bypassea.
- **Click derecho**: menú contextual (reset a default, asignar pedal de expresión, copiar/pegar).
- **Arrastrar y soltar**: mueve un bloque a otro slot, o lo intercambia con el que esté ahí.
- Mover un bloque de la fila 1 a la 2 (o 3 a 4) crea automáticamente un camino de
  Splitter/Mixer para señal paralela.
- Los bloques de I/O se ponen en rojo si reciben señal por encima del pico máximo.

## Código de color por tipo de bloque

Este es el hallazgo más reutilizable: cada categoría de dispositivo tiene un color de borde
fijo, consistente en toda la app (la grilla, el medidor de CPU, el Device List). Permite
reconocer de un vistazo qué hace cada bloque sin leer la etiqueta.

| Categoría (Neural DSP) | Color observado |
|---|---|
| Amp | Rojo |
| Cab | Violeta |
| Overdrive | Naranja |
| Delay | Cian/turquesa |
| Neural Capture | Gris/blanco |

Los mockups de PedalSistema adoptan el **patrón**, no la paleta: ver la tabla de colores propia
en `docs/mockups.md`.

## Editor de parámetros

Aparece debajo de la grilla al seleccionar un bloque. Se adapta según el tipo:

- **Bloques simples** (delay, drive): hasta 10 parámetros en dos filas de 5, con knobs y
  switches. Los switches ON/OFF son cápsulas con un punto deslizante.
- **EQ paramétrico**: curva de frecuencia interactiva con nodos numerados arrastrables, más
  controles de TYPE/GAIN/FREQUENCY/Q por banda.
- **EQ gráfico**: barras/puntos por banda de frecuencia (9 bandas en el ejemplo del manual).
- Botón de **bypass** (⏻) arriba a la derecha del editor.
- Menú contextual (⋮) arriba a la izquierda: reset a default, fijar como default, asignar pedal
  de expresión, copiar/pegar el bloque.
- Cuando un bloque tiene varias versiones (Legacy/New), se cambia desde ese mismo menú.

## Preset Explorer y Directory: cómo se organizan los presets

Arriba de la grilla hay un **Preset Explorer** compacto: flechas ‹ › para navegar, nombre del
preset activo (en itálica si tiene cambios sin guardar, con `*`), botón de guardar, menú
contextual.

Tocar el nombre del preset abre el **Preset Browser**: un panel con buscador, lista de
**Setlists** (carpetas) a la izquierda, grilla de **Banks** numerados, y la lista de presets del
banco seleccionado a la derecha.

**Jerarquía**: Setlist → 32 Banks → 8 Presets = 256 presets por Setlist. **Esto coincide
exactamente con la jerarquía que ya habíamos definido** para PedalSistema (`presets/schema.json`,
`MAX_BANCOS = 32`, `PRESETS_POR_BANCO = 8`) — no es una casualidad: ambos productos compiten en
el mismo espacio (reemplazo de hardware de piso) y el estándar de facto en esa categoría (Quad
Cortex, Helix) es 8 presets por banco.

La sección **Directory** completa (fuera de la grilla) organiza todo lo guardado: Presets,
Neural Captures, Impulse Responses, cada uno con sus propias subcarpetas (Downloads, Cloud
Presets, Factory Presets, My Presets). Selección múltiple con contador (`4/256 selected`) y
acciones en lote (subir, bajar, me gusta, filtrar, copiar, borrar, ordenar, actualizar).

## Qué se adoptó para PedalSistema y qué no

**Adoptado** (patrón de interacción, ya validado por un producto competidor exitoso):

- Cadena de bloques en fila horizontal, click para seleccionar y editar, doble-click implícito
  para bypass.
- Color fijo por categoría de bloque, consistente en toda la app.
- Editor de parámetros como panel fijo debajo de la cadena, no como modal.
- Explorador con grilla de bancos + lista de presets del banco activo.
- Indicador de cambios sin guardar en itálica.

**No adoptado**:

- Su paleta de colores exacta, tipografía, iconografía — identidad visual propia de PedalSistema
  (ver `docs/mockups.md`).
- Neural Capture / Impulse Responses como conceptos — no existen en nuestro modelo, que usa
  unidades de Guitarix.
- Cortex Cloud / selección múltiple / Gig View — fuera de alcance por ahora; quedan como
  referencia para cuando se evalúen esas fases.

## Pendiente de decisión

Ninguno de los archivos de este manual quedó guardado en el repo (es material de un tercero,
solo para consulta). Si en el futuro hace falta releerlo, está en la URL de la fuente principal
arriba.
