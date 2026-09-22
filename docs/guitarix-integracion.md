# Integración con Guitarix

Todo lo de este documento está verificado contra el código fuente de
[brummer10/guitarix](https://github.com/brummer10/guitarix), no contra documentación externa.
Las referencias apuntan a archivos y líneas del repo original.

## Por qué Guitarix

Guitarix cubre tres requisitos del proyecto sin desarrollo adicional:

1. **Modo headless real** (`-N`), pensado explícitamente para equipos dedicados sin pantalla.
2. **Servidor JSON-RPC sobre TCP**, que es exactamente la capa de control que necesita
   `engine/rpc_client.py`. No hace falta pasar por MIDI ni DBus para controlarlo.
3. **Carga nativa de modelos NAM** (`*.nam`), RTNeural (`*.json`) y `*.aidax`, además de
   impulse responses para simulación de gabinete.

Licencia GPL-3.0, compatible con la del proyecto.

## Arranque del motor

```bash
guitarix -N -p 7000
```

| Opción | Corta | Descripción |
|---|---|---|
| `--nogui` | `-N` | Arranca sin interfaz gráfica |
| `--rpcport PORT` | `-p` | Servidor JSON-RPC escuchando en ese puerto |
| `--rpchost ADDR` | `-H` | Dirección de escucha del servidor RPC |

El puerto por defecto es **7000** (`trunk/src/gx_head/gui/gx_main.cpp:742-744`). Internamente
`RPCPORT_DEFAULT` es el valor centinela `-2` y `RPCPORT_NONE` es `-1` para deshabilitar el
servidor (`trunk/src/headers/gx_system.h:357-358`).

## Protocolo

**JSON-RPC 2.0 sobre socket TCP plano, delimitado por salto de línea.** Cada mensaje es un
objeto JSON en una sola línea terminada en `\n` (`trunk/src/gx_head/engine/jsonrpc.cpp:1341`).
No hay handshake, ni headers HTTP, ni framing por longitud.

### Restricción importante: parámetros solo posicionales

Los parámetros **deben** ir como array JSON. Pasarlos como objeto con nombres devuelve el error
`-32000 "by-name parameters not implemented"` (`jsonrpc.cpp:1241-1242`). Esto es una desviación
respecto del estándar JSON-RPC 2.0 y es la causa de error más probable al escribir un cliente.

### Llamada con respuesta

Si el mensaje incluye `id`, el servidor responde:

```json
{"jsonrpc":"2.0","method":"getversion","params":[],"id":1}
{"jsonrpc":"2.0","id":1,"result":"0.46.0"}
```

### Notificación sin respuesta

Si el mensaje **no** incluye `id`, se ejecuta como notificación y no hay respuesta
(`jsonrpc.cpp:1263-1265`). Es el modo correcto para comandos de tiempo real como cambio de
preset, donde esperar un round-trip agregaría latencia innecesaria:

```json
{"jsonrpc":"2.0","method":"setpreset","params":["Rock","Crunch"]}
```

Cada método tiene un flag `has_result` que define si admite respuesta; está en la tabla de
`docs/guitarix-rpc-methods.md`.

## Suscripción a eventos

El servidor puede empujar notificaciones al cliente. Primero hay que suscribirse con `listen`,
pasando uno de estos tokens (`jsonrpc.cpp:265-283`):

| Token | Cubre |
|---|---|
| `all` | Todos los eventos |
| `preset` | Cambio de preset activo |
| `state` | Cambio de estado del motor |
| `freq` | Frecuencia del afinador |
| `display` | Valores de display y estado de display |
| `tuner` | Selección del afinador |
| `presetlist_changed` | Alta/baja/reordenamiento de presets |
| `logger` | Mensajes de log |
| `midi` | Cambios de mapeo y de valor MIDI |
| `param` | Cambio de cualquier parámetro |
| `plugins_changed` | Alta/baja de plugins |
| `misc` | Mensajes varios |
| `units_changed` | Cambio en el orden de las unidades del rack |

```json
{"jsonrpc":"2.0","method":"listen","params":["preset"]}
```

Los eventos que el servidor emite llegan como notificaciones JSON-RPC (sin `id`) con estos
nombres de método: `set`, `preset_changed`, `state_changed`, `presetlist_changed`,
`plugins_changed`, `rack_units_changed`, `midi_changed`, `midi_value_changed`, `tuner_changed`,
`show_tuner`, `display_bank_preset`, `set_display_state`, `impresp_list`, `message`,
`server_shutdown`.

Esto es lo que hace viable el control remoto en tiempo real: la PWA mobile y la GUI PyQt6 pueden
mantenerse sincronizadas con el estado del motor sin hacer polling.

## Descubrimiento en red (Avahi / mDNS)

Guitarix incluye registro y descubrimiento por Avahi (`trunk/src/headers/avahi_register.h`,
`trunk/src/gx_head/gui/avahi_discover.cpp`). El motor puede anunciarse en la red local, así que
la PWA de control remoto puede encontrar el equipo automáticamente en vez de pedirle al usuario
que escriba una IP. Relevante para la Fase 5.

## WebUI de referencia

El repo trae en `trunk/webui/` una interfaz web completa que ya habla este mismo protocolo. Usa
`websockify` como proxy WebSocket→TCP:

```bash
python -m websockify.websocketproxy --web=. '*':8000 localhost:7000
```

Sirve como implementación de referencia para `server/websocket.py`. Nuestro diseño con FastAPI
puede hacer de puente directamente, sin `websockify`, hablando el socket TCP desde Python.

## Decisión pendiente: NAM-rs vs. carga nativa

Guitarix ya carga modelos `.nam` por sí solo. Antes de integrar
[nam-rs](https://github.com/fabiohl/nam-rs) como motor separado, hay que verificar en Fase 2 si
aporta algo sobre el loader nativo (control fino de SIMD, menor latencia de inferencia) o si
conviene simplificar el stack y apoyarse solo en Guitarix. Mantener un solo motor de audio
reduce superficie de fallo y consumo de CPU.

## Compilación

```bash
git clone https://github.com/brummer10/guitarix.git
cd guitarix && git submodule update --init --recursive
cd trunk
./waf configure --prefix=/usr --includeresampler --includeconvolver --optimization
./waf build && sudo ./waf install
```

Build system: WAF. Dependencias en Debian:

```
gperf intltool libgtk-3-dev libgtkmm-3.0-dev libjack-dev liblilv-dev lv2-dev
libfftw3-dev libsndfile1-dev libboost-dev libboost-system-dev libboost-thread-dev python3
```

Las dependencias de GTK son necesarias para compilar aunque el binario se use en modo headless.
Para la ISO mínima conviene evaluar compilar en una etapa de build separada e instalar solo el
binario y sus librerías de runtime.
