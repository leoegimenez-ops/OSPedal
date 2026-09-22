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

### RPC: listar y recargar

Agregado a `engine/rpc_client.py`:

```python
gx.archivos("nam")                    # lista de modelos disponibles (get_file_list)
gx.directorios_impulse_response()     # directorios de IRs configurados (load_impresp_dirs)
gx.recargar_impulse_responses()       # re-escanea sin reiniciar el motor (reload_impresp_list)
```

Guitarix no vuelve a escanear la carpeta de IRs solo porque aparecieron archivos nuevos mientras
corre — hay que pedírselo explícitamente después de que el usuario copie modelos. Por eso existe
`recargar_impulse_responses()` como notificación separada.

**Nota de honestidad**: el nombre exacto de la categoría que espera `get_file_list` (si es
`"nam"`, `"aidax"`, algo distinto, o si hace falta un método específico por tipo) no está
verificado contra un Guitarix real todavía — está inferido del nombre del método y de que el
manual dice que el Device List "muestra los puertos organizados en categorías". Falta confirmarlo
cuando tengamos el motor corriendo. Los tres wrappers en sí (forma de la llamada, notificación vs.
respuesta) sí están probados contra un servidor simulado que respeta el protocolo real.

### Dónde aparece en la interfaz

En el Editor de Nodos (mockup), el bloque **CAB** ya tiene un parámetro `LEVEL` pero le falta el
selector del archivo IR en sí; el bloque **AMP** hoy es un amp simulado clásico de Guitarix, sin
opción de cargar un modelo `.nam` en su lugar. Son cambios de UI pendientes, no de arquitectura:
la data ya puede pedirse por RPC, falta el selector visual (una lista con `gx.archivos("nam")`,
similar al Explorador de Presets que ya existe).

### Lo que queda para más adelante

Un importador que hable directo con la API de Tone3000 (buscar, previsualizar, descargar sin salir
de PedalSistema) sería un salto de calidad importante, pero es trabajo de Fase 5+: implica diseño
de UI de búsqueda, manejo de red, y revisar los términos de uso de su API. Por ahora, copiar el
archivo a mano a `models/nam/` es el camino — simple, sin dependencias, y ya funciona con lo que
existe.
