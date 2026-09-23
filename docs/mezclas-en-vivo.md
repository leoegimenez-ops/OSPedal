# Mezclas en vivo: varias líneas de instrumento, varios monitores

## El pedido

Usar PedalSistema para una banda en vivo, no solo para un músico: hasta 4 líneas de instrumento
(2 guitarras, bajo, voz) sonando en simultáneo, cada una con su propia cadena de efectos, y 5
mezclas internas distintas — una de monitor por integrante (4) y una para PA/público.

## Decisión: N instancias de Guitarix, no un motor multitrack nuevo

Cada línea de instrumento es su propia instancia headless de Guitarix (`guitarix -N -p <puerto>`),
cada una un cliente JACK independiente con su propia cadena de efectos. Confirmado en vivo
(23/09/2026, WSL2 + Ryzen 5 5600G) que **esto no es lo que limita la CPU**: dos instancias
simultáneas + JACK usan ~2-3% de CPU combinado sin modelado neuronal. Ver detalle de la medición
de NAM en `docs/capturas-neuronales.md` — la conclusión ahí quedó abierta, no cerrada.

**No hace falta Dual Rig** para este pedido: cada guitarra usa un preset a la vez (instantáneo,
sin gap — ya construido), no dos tonos mezclados en simultáneo. Eso simplifica mucho: entra en el
modelo existente de `presets/` sin cambios.

## El mezclador: `engine/mixer.py`

JACK por sí solo resuelve el *ruteo* (conectar la salida de una instancia de Guitarix a donde
haga falta) pero no ofrece ganancia por conexión — conectar dos fuentes al mismo puerto las suma a
volumen unidad, sin forma de balancear. Hacía falta un cliente JACK propio con una matriz de
ganancia fuente×bus. Eso es `MezcladorJack`.

```python
from engine.mixer import MezcladorJack

with MezcladorJack(["guitarra1", "guitarra2", "bajo", "voz"],
                    ["monitor1", "monitor2", "monitor3", "monitor4", "pa"]) as m:
    m.conectar_entrada("guitarra1", "gx_head_amp:out_0")   # instancia real de Guitarix
    m.conectar_salida("pa", "system:playback_1")            # salida física
    m.fijar_ganancia("bajo", "monitor1", 0.6)                # el monitor del guitarrista 1
                                                              # quiere menos bajo
```

Verificado en vivo, extremo a extremo, contra un `jackd` real (23/09/2026):

- Un cliente sintético escribiendo una señal constante conocida, conectado a través del
  mezclador, con la salida leída por un tercer cliente — confirma que la suma ponderada llega
  correcta por los puertos JACK reales, no solo en la función pura (`engine/test_mixer.py`).
- Conectado a la instancia real de Guitarix (`gx_head_amp:out_0`) — confirma que el ruteo funciona
  contra el motor real, no solo contra un cliente de prueba.
- Cambiar una ganancia en caliente (sin reconectar puertos) se refleja en el siguiente buffer.

### Lo que se simplificó a propósito

- **Buses mono, no estéreo.** Encaja con "todos con in-ear/wedge mono" — es la config más simple
  y la más común para monitores de banda. Un bus estéreo es extender `MezcladorJack` para
  registrar 2 puertos por bus en vez de 1; no hace falta rediseñar nada si hace falta después.
- **Sin lock en la matriz de ganancia.** Se lee dentro del callback de audio de JACK; se confía en
  que la asignación de un `float` a una clave de `dict` es atómica bajo el GIL. Es una
  simplificación consciente, documentada en el docstring del módulo — si en la práctica causa
  clicks al cambiar ganancia, el siguiente paso es doble buffer con swap atómico.
- **La conexión JACK (`conectar_entrada`/`conectar_salida`) es manual**, no hay todavía un mapeo
  automático "guitarra 1 = este puerto físico". Eso es trabajo de GUI/configuración (Fase 4), no
  del mezclador en sí.

## Control remoto: `server/api.py`

`GET /mezclador/matriz` y `POST /mezclador/ganancia` (ver docstring de `server/api.py`) exponen la
matriz por HTTP — es lo que cada integrante controlaría desde su celular para ajustar su propio
monitor, reusando el mismo patrón que ya usan `/estado`/`/preset`/`/parametros`. Probado en vivo
con curl contra un servidor real, y con tests contra un mezclador falso
(`server/test_api.py`) para que corran sin necesitar JACK.

Variables de entorno: `MIXER_FUENTES`, `MIXER_BUSES` (listas separadas por coma) — default 4
líneas / 5 buses, pero configurable sin tocar código para una formación distinta.

## Lo que queda abierto (ver también `docs/capturas-neuronales.md` y la conversación completa)

1. **¿Cuánta CPU cuesta NAM de verdad?** Medido casi sin diferencia (~1%) contra el motor real,
   pero en un entorno (WSL2, backend `dummy`, sin scheduling de tiempo real) que puede no ser
   representativo. Sin esto confirmado no se puede asegurar que 2 guitarras con NAM + bajo + voz
   entren cómodas en una sola máquina.
2. **La interfaz Tascam US-1800 puede no ser compatible.** No es USB Audio Class-compliant; sin
   driver conocido en Linux, sin driver oficial más allá de Windows 7. Bloquea probar (1) con
   audio real y bloquea la salida física de los 5 buses. Ver la conversación del 23/09/2026 para
   las fuentes.
3. **Entrega del monitor por celular/tablet** (mencionada como alternativa a salida analógica) es
   un problema de audio en tiempo real por WiFi, no de control — mucho más exigente en latencia
   que lo que ya construimos en `server/api.py` (pensado para comandos, no para streaming de
   audio). No hay diseño todavía; queda para cuando (1) y (2) estén resueltos.
4. **Mapeo automático de puertos físicos ↔ fuentes/buses** — hoy es manual vía
   `conectar_entrada`/`conectar_salida`. Depende de qué interfaz termine siendo viable (punto 2).
