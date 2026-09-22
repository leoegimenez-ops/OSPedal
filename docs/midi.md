# Control MIDI

## Soporte genérico, sin modelos hardcodeados

El sistema funciona con **cualquier controlador MIDI class-compliant**: no hay nada específico
de una marca o modelo de pedalera. El usuario asocia sus propios controles desde el equipo, con
MIDI learn o editando el mapa en JSON.

Esto responde al requisito de que la pedalera se configure en el propio sistema, igual que la
interfaz de audio.

## Separación de capas

```
bytes del puerto  →  ParserMidi  →  MensajeMidi  →  MapaMidi  →  Accion  →  ControladorEscenario  →  RPC
      (ALSA)          (puro)                         (puro)                    (estado)              (motor)
```

`engine/midi_engine.py` es **puro**: no toca ALSA, ni sockets, ni archivos. Recibe bytes y
devuelve acciones. El backend que lee el puerto MIDI real se implementa aparte y es
reemplazable.

No es una separación de adorno: significa que toda la lógica difícil —el parseo del protocolo y
el ruteo de acciones— se prueba sin hardware, sin Linux y sin sonido. Lo único que queda por
verificar con una pedalera en la mano es la lectura del puerto, que son unas pocas líneas.

## Qué resuelve el parser

El protocolo MIDI tiene tres detalles que rompen las implementaciones ingenuas, y los tres pasan
de verdad con pedaleras reales:

**Running status.** Un mensaje puede omitir el byte de estado y reusar el del mensaje anterior,
para ahorrar ancho de banda. Un parser que espera un byte de estado por mensaje pierde todos los
siguientes.

**Mensajes de tiempo real intercalados.** Un MIDI Clock (`0xF8`) puede caer justo entre los dos
bytes de datos de un Control Change. No invalida el mensaje: hay que procesarlo aparte y seguir.

**Mensajes partidos entre lecturas.** El flujo llega por bloques arbitrarios, así que un mensaje
puede quedar a mitad entre dos lecturas del puerto. El parser es incremental y mantiene el
estado entre llamadas.

Además:

- Un **Note On con velocity 0 es un Note Off** por convención del estándar, y las pedaleras lo
  usan constantemente.
- **Program Change y Presión de Canal llevan un solo byte de datos**, no dos. Confundirlo
  desincroniza todo el flujo posterior.
- Los **canales se numeran 1 a 16**, como los ven los músicos, no 0 a 15 como viajan por el
  cable. La conversión se hace una sola vez, en el parser.

## Acciones disponibles

| Acción | Parámetro | Qué hace |
|---|---|---|
| `cambiar_preset` | índice 0-255 | Carga un preset por índice absoluto |
| `preset_en_banco` | posición 0-7 | Carga un preset del banco que se está mirando |
| `preset_siguiente` / `preset_anterior` | — | Navega salteando posiciones vacías |
| `banco_siguiente` / `banco_anterior` | — | Cambia el banco visible, **sin cambiar el sonido** |
| `toggle_stomp` | número 0-7 | Prende/apaga una unidad del rack |
| `escena` | índice | Aplica una escena del preset |
| `modo` | 0=preset 1=stomp 2=scene | Cambia el modo de operación |
| `afinador` | — | Activa el afinador |
| `tap_tempo` | — | Marca el tempo con el pie |

## Dos decisiones de comportamiento en vivo

**Subir de banco no cambia el sonido.** Es navegación: el banco visible cambia, pero recién
suena cuando se elige un preset del banco nuevo. Es como funcionan los equipos de piso, y por
una buena razón: cambiar el sonido mientras se busca el próximo preset sería un accidente en
pleno tema.

**Soltar el pedal no dispara la acción de nuevo.** Un footswitch momentáneo manda valor 127 al
pisar y 0 al soltar. Sin un umbral, cada pisada ejecutaría la acción dos veces —y un toggle de
stomp volvería a su estado original al instante. El campo `valor_minimo` (por defecto 1) filtra
el mensaje de soltado; los Note Off se descartan por el mismo motivo.

## Program Change directo

Muchas pedaleras mandan Program Change para elegir preset. Con `programa_directo` activado (por
defecto), cualquier PC selecciona el preset de ese índice sin necesidad de declarar 128
asignaciones a mano. Se puede desactivar si se prefiere mapear todo explícitamente.

Program Change llega hasta 127; para alcanzar los 256 presets hace falta Bank Select (CC 0 y
32), que todavía no está implementado.

## MIDI learn

Es lo que hace viable el soporte genérico: el usuario elige la acción, pisa el pedal, y queda
asociado. No hace falta saber qué CC manda cada switch.

```python
mensajes = parser.alimentar(bytes_del_puerto)
mapa.aprender(mensajes[0], Accion.TOGGLE_STOMP, parametro=0)
mapa.guardar("mapa-midi.json")
```

Aprender el mismo control dos veces reemplaza la asignación en vez de duplicarla. Si el mensaje
capturado es un Note Off, se registra el Note On correspondiente, porque la acción va asociada a
la pisada y no al soltado. Con `omni=True` la asignación responde en cualquier canal.

Guitarix además tiene su propio MIDI learn para mapear parámetros continuos —un pedal de
expresión al volumen, por ejemplo— vía `midi_set_config_mode`. Son complementarios: el nuestro
mapea acciones del sistema, el de Guitarix mapea parámetros de audio.

## Formato del mapa

Ver `engine/ejemplo-mapa-midi.json`.

```json
{
  "version": 1,
  "nombre": "Pedalera genérica de 4 switches",
  "canal": 0,
  "programa_directo": true,
  "asignaciones": [
    { "tipo": "control_change", "numero": 80, "accion": "toggle_stomp", "parametro": 0 }
  ]
}
```

`canal` en 0 significa omni (responde en cualquier canal). Cada asignación acepta también su
propio `canal` y un `valor_minimo`.

## Uso

```python
from engine.midi_engine import ParserMidi, MapaMidi
from engine.controlador import ControladorEscenario
from engine.rpc_client import GuitarixRPC
from presets.preset_manager import Setlist

parser = ParserMidi()
mapa = MapaMidi.cargar("engine/ejemplo-mapa-midi.json")
setlist = Setlist.cargar("presets/ejemplo-setlist.json")

with GuitarixRPC() as gx:
    control = ControladorEscenario(setlist, gx)
    while True:
        for mensaje in parser.alimentar(leer_del_puerto_midi()):
            accion = mapa.resolver(mensaje)
            if accion:
                print(control.ejecutar(*accion))   # el texto va al display
```

`leer_del_puerto_midi()` es lo único que falta: el backend ALSA, pendiente de tener Linux.
