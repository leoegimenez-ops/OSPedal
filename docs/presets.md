# Sistema de presets

## La decisión: quién es dueño de qué

Guitarix ya tiene su propio sistema de bancos y presets (`banks`, `presets`, `setpreset`,
`bank_insert_new`…). Había dos caminos posibles: delegarle todo el almacenamiento, o mantener un
formato propio. **Mantenemos formato propio**, con este reparto:

| | Fuente de verdad | Qué guarda |
|---|---|---|
| **Setlist JSON** (nuestra) | PedalSistema | Estructura de la performance: qué presets hay, en qué orden, qué pedal hace qué, tempo y notas por tema, escenas |
| **Guitarix** | Motor DSP | Estado de audio: valores de los parámetros de amplificador y efectos |

Razones:

1. **Guitarix no modela lo que necesitamos.** No tiene setlists, ni escenas, ni asignación de
   stomps por preset, ni tempo por tema. Esos conceptos son la identidad del producto (el modelo
   Preset / Stomp / Scene del Quad Cortex) y no existen en su formato.
2. **El sync a la nube necesita un formato portable** (Fase 7). Un JSON propio versionado se
   sincroniza, se versiona y se migra; el formato interno de Guitarix no.
3. **La pre-carga en RAM exige tener los valores nosotros.** El requisito de cambiar preset sin
   gap de audio se cumple teniendo el snapshot en memoria, no pidiéndoselo al motor.
4. **Desacopla del motor.** Si algún día se reemplaza o forkea Guitarix, las setlists de los
   usuarios siguen siendo válidas.

Un preset nuestro puede **referenciar** un preset de Guitarix como estado base (campo
`guitarix`) y encima aplicar su propio snapshot de parámetros. También puede no referenciar
ninguno y partir del estado actual del motor.

## Cómo se aplica un preset

Todo el cambio son **dos notificaciones sin round-trip**:

1. `setpreset <banco> <preset>` — solo si el preset referencia uno de Guitarix.
2. Un único `set` con todo junto: parámetros, estados de stomp y escena.

Los stomps no necesitan llamadas aparte: el on/off de una unidad del rack es un parámetro común
llamado `<unidad>.on_off` (verificado en `gx_pluginloader.cpp:333`), así que viaja en el mismo
`set`. Como ambos mensajes van por el mismo socket TCP, el orden está garantizado, y como
ninguno espera respuesta, el cambio de preset no paga latencia de ida y vuelta.

Detalle relevante: los parámetros booleanos de Guitarix se leen con `getInt()`
(`jsonrpc.cpp:1027`), así que se envían como `1`/`0`. La conversión la hace `pares_rpc()`.

## Jerarquía e índices

```
Setlist › Banco (máx. 32) › Preset (máx. 8)  =  256 presets
```

El índice plano es `banco * 8 + posición`, que es como numera los presets una pedalera MIDI.
**Los índices no son consecutivos si un banco está incompleto**: con un banco de 3 presets, el
siguiente banco empieza en el índice 8, no en el 3. Es deliberado — mantiene estable la relación
entre número de programa MIDI y posición física, así que agregar un preset a un banco no
desplaza los de los demás bancos ni rompe una pedalera ya configurada.

## Escenas

Una escena pisa parámetros del preset sin cambiar de preset, lo que permite variaciones
instantáneas dentro de un mismo tema (estrofa / estribillo). Precedencia, de menor a mayor:

```
parámetros del preset  →  estados de stomp  →  parámetros de la escena
```

La escena gana por ser la variación más específica. Está en el esquema desde ahora aunque el
modo Scene sea de la v2 (Fase 8), para no tener que migrar setlists después.

## Validación

El esquema formal está en `presets/schema.json` (JSON Schema 2020-12). Sirve como contrato de
intercambio para la PWA, el sync a la nube y los editores.

La validación en runtime está implementada aparte, en `presets/preset_manager.py`, **sin
dependencias externas**. Dos motivos: un equipo de escenario no debería fallar al arrancar por
una librería faltante, y los errores indican la ruta exacta del campo:

```
setlist.bancos[0].presets[1].tempo_bpm: debe estar entre 20 y 300
```

En CI conviene además validar los archivos contra `schema.json` con la librería `jsonschema`,
para verificar que ambas definiciones no se desincronicen.

## Guardado atómico

`Setlist.guardar()` escribe a un archivo temporal y después lo reemplaza. En un equipo que
arranca desde pendrive y puede quedarse sin luz en pleno show, un guardado a medias dejaría la
setlist truncada. El reemplazo es atómico: o está la versión vieja o la nueva, nunca una rota.

## Uso

```python
from presets.preset_manager import Setlist, aplicar
from engine.rpc_client import GuitarixRPC

setlist = Setlist.cargar("presets/ejemplo-setlist.json")   # toda en RAM

with GuitarixRPC() as gx:
    aplicar(setlist.preset_por_indice(0), gx)              # por índice MIDI
    aplicar(setlist.preset(0, 1), gx)                      # por banco y posición
    aplicar(setlist.preset(0, 0), gx, escena="Estribillo") # con escena
```
