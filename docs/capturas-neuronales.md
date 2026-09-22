# Capturas neuronales: qué formatos existen y cuáles podemos usar

## Dos ecosistemas que no tienen nada que ver entre sí

A pesar de que ambos se llaman "captura" o "modelado neuronal", son tecnologías separadas con
implicancias muy distintas para el proyecto.

### El ecosistema abierto: lo que la comunidad comparte de verdad

| Formato | Qué es | Licencia | ¿Sirve para pedales? |
|---|---|---|---|
| **`.nam`** | [Neural Amp Modeler](https://github.com/sdatkinson/neural-amp-modeler) — JSON con arquitectura (WaveNet/LSTM/Linear), pesos y metadatos | Código abierto, permisiva | Sí — el campo `gear_type` incluye explícitamente `"pedal"` y `"pedal_amp"`, no solo `"amp"` |
| **`.aidax`** | Formato de [AIDA-X](https://github.com/AidaDSP/AIDA-X), sobre RTNeural | **GPL-3.0** — la misma licencia de Guitarix y de este proyecto | Sí, amps y pedales |
| **`.wav`** | Impulse Response (IR) para simulación de cabina | Audio plano, sin licencia de modelo | No aplica (cabinas, no pedales) |

Se comparten gratis en volumen en **[Tone3000](https://www.tone3000.com/)** (antes ToneHunt):
más de 11.000 modelos de amps y pedales, más de 3.400 IRs, subidos por la comunidad.

**Guitarix ya carga `.nam` y `.aidax` nativamente** — confirmado en `docs/guitarix-integracion.md`
al investigar el motor por primera vez. No hace falta escribir ningún parser ni motor de
inferencia propio.

### El ecosistema cerrado: lo que NO podemos usar

| Producto | Por qué no sirve |
|---|---|
| **Neural Capture** (Quad Cortex, Neural DSP) | Propietario. La versión 2 ni siquiera guarda el archivo localmente: entrena en Cortex Cloud y queda atado a la cuenta del usuario. En los foros oficiales hay pedidos explícitos de soporte para `.nam` en el Quad Cortex que Neural DSP no atendió — es una limitación de negocio, no técnica. |
| **Tonex** (IK Multimedia) | Mismo patrón: formato `.tonex` propio, ecosistema cerrado (ToneNET), sin exportación a formatos abiertos conocida. |

No hay conversión posible de estos formatos a `.nam`/`.aidax` sin acceso a herramientas internas
de esas empresas. No es un problema técnico que se pueda resolver con más trabajo: es una
decisión comercial deliberada de mantener el ecosistema cerrado.

**La conclusión práctica:** lo que circula gratis y en masa en internet es, casi en su totalidad,
`.nam`. Es el estándar de facto de la comunidad justamente porque es abierto. Lo que está atado a
hardware específico es, por diseño, lo que no circula.

## Cómo se integra en PedalSistema

Nada de esto requiere motor nuevo — Guitarix ya sabe inferir estos modelos. Lo que hace falta es
la integración del lado de nuestro sistema: dónde viven los archivos y cómo se listan.

### Estructura de directorios

```
models/
├── nam/     ← modelos .nam (gitignored, pesan mucho)
├── aidax/   ← modelos .aidax (gitignored)
└── irs/     ← impulse responses .wav (gitignored)
```

`models/aidax/` es nuevo — antes solo existían `nam/` e `irs/`. El usuario copia los archivos
descargados de Tone3000 directamente a la carpeta que corresponda; no hay paso de instalación.

### El mecanismo real, verificado en el código fuente del motor

Esta sección reemplaza lo que había escrito la primera vez, que era una suposición razonable
(`get_file_list`) pero no la mecánica real. Fui a `gx_neural_plugins.h/.cpp` y `gx_engine.cpp` a
confirmarlo.

**`NeuralAmp` y `RtNeural` no son una propiedad del bloque "amp"** — son unidades de rack propias,
con nombre de instancia fijo (`gx_engine.cpp:310-315`):

| Ranura | Formato | Uso |
|---|---|---|
| `nam` | `.nam` | Instancia principal |
| `snam` | `.nam` | Segunda instancia |
| `mnam` | `.nam` | Modo A/B (blend entre dos modelos) |
| `rtneural` | `.json` / `.aidax` | Instancia principal |
| `srtneural` | `.json` / `.aidax` | Segunda instancia |
| `mrtneural` | `.json` / `.aidax` | Modo A/B |

Cada una expone dos parámetros de texto/número normales — **no hay ningún método RPC dedicado**,
se cargan con el mismo `set` que cualquier otro parámetro:

- **`<ranura>.loadpath`** (string): carpeta a escanear. Al cambiar, Guitarix dispara un rescan
  interno (`create_nam_filelist()` / `create_rtneural_filelist()`) y arma una lista de hasta 126
  archivos que matchean el sufijo exacto (`.nam`, o `.json`/`.aidax` para RTNeural).
- **`<ranura>.flist`** (número): índice dentro de esa lista. `0` es siempre `"None"`; los archivos
  ocupan del `1` en adelante, **en el orden que los devuelve el sistema de archivos — no
  alfabético, no garantizado**.

`loadpath` arranca vacío: no hay una carpeta fija de Guitarix que haya que descubrir o respetar.
Apuntarlo a nuestro propio `models/nam/` es una decisión nuestra, no una convención ajena.

```python
gx.cargar_nam("/ruta/absoluta/a/una/subcarpeta/con/un/solo/archivo.nam")
gx.cargar_rtneural("/ruta/a/carpeta", ranura="srtneural")   # segunda instancia
```

**La estrategia contra el orden no garantizado**: en vez de listar la carpeta completa y adivinar
en qué posición quedó el archivo que queremos, `cargar_nam`/`cargar_rtneural` apuntan `loadpath` a
una carpeta que contiene **un solo archivo** (o un symlink a él) y usan siempre `flist=1`. Es
determinista sin depender de leer de vuelta el orden interno de Guitarix. La organización de esas
sub-carpetas curadas (una por captura, o un symlink temporal armado al cargar un preset) queda
para cuando se diseñe el gestor de archivos — la llamada RPC en sí ya funciona.

Verificado con un servidor simulado: la secuencia manda `<ranura>.loadpath` y después
`<ranura>.flist`, ambos como notificaciones (sin esperar respuesta), con los nombres de parámetro
exactos del código fuente.

### Lo que sigue sin verificar

Las **impulse responses de cabina (`.wav`)** usan un subsistema distinto (`load_impresp_dirs`,
`reload_impresp_list`, en `gx_convolver.h`/`.cpp`) que todavía no revisé con el mismo nivel de
detalle — no sé si sigue el mismo patrón `loadpath`+`flist` o algo distinto. Queda pendiente para
la próxima vez que se toque el bloque CAB.

`gx.archivos()` (que llama a `get_file_list`) se deja en el cliente pero **no se debe usar para
cargar capturas** — no es el mecanismo real, ver arriba. Puede servir para otra cosa que todavía
no identifiqué.

### Dónde aparece en la interfaz

En el Editor de Nodos (mockup), el sidebar de categorías ya tiene la sección "TUS CAPTURAS" para
AMP y OVERDRIVE con nombres de archivo de ejemplo. Elegir un ítem ahí es, en el sistema real, el
punto donde se dispararía `cargar_nam()`/`cargar_rtneural()` con la ruta correspondiente.

### Lo que queda para más adelante

Un importador que hable directo con la API de Tone3000 (buscar, previsualizar, descargar sin salir
de PedalSistema) sería un salto de calidad importante, pero es trabajo de Fase 5+: implica diseño
de UI de búsqueda, manejo de red, y revisar los términos de uso de su API. Por ahora, copiar el
archivo a mano a `models/nam/` es el camino — simple, sin dependencias, y ya funciona con lo que
existe.
