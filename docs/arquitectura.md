# Arquitectura

## Dispositivos de audio y MIDI

Decisión: el sistema **no** apunta a modelos específicos de interfaz de audio (ej. Scarlett, Tascam) ni de controlador MIDI (ej. pedal Wave). En su lugar:

- **Audio:** se apoya en el soporte nativo de ALSA para dispositivos USB Audio Class-compliant. Cualquier interfaz que cumpla el estándar funciona sin instalar drivers adicionales (a diferencia de Windows, donde cada fabricante requiere su propio driver).
- **MIDI:** mismo criterio con USB MIDI Class-compliant, vía ALSA/RtMidi. Cualquier controlador o pedal MIDI compatible con el estándar es reconocido automáticamente.
- **Configuración:** el propio sistema expone una pantalla (GUI PyQt6, módulo `gui/`) donde el usuario ve los dispositivos de audio y MIDI detectados y elige cuál usar. Esta selección se guarda como configuración del sistema (no hardcodeada).

Implicancia para `engine/`:
- `audio_engine.py` debe enumerar dispositivos ALSA/JACK disponibles en vez de asumir un dispositivo fijo. **Hecho (23/09/2026)**: enumera tarjetas ALSA (`aplay -l`/`arecord -l`) y puertos JACK (`jack_lsp -pt`, incluye frecuencia de muestreo y tamaño de buffer). La parte de JACK está verificada contra un `jackd` real corriendo con Guitarix conectado; la de ALSA usa el formato documentado de `alsa-utils` pero todavía no se probó contra una tarjeta física — WSL2 no tiene forma de exponer una. Ver el docstring del módulo.
- `midi_engine.py` debe enumerar puertos MIDI disponibles (ALSA seq) y permitir mapeo de mensajes MIDI (CC/PC/Note) configurable por el usuario, no atado a un pedal específico.

El mapeo MIDI no hace falta implementarlo desde cero: Guitarix expone un modo de aprendizaje
(`midi_set_config_mode` + `get_last_midi_control_value`) que asocia un control físico a un
parámetro con solo moverlo. Ver `docs/guitarix-rpc-methods.md`.

## Control del motor DSP

El motor se controla por **JSON-RPC 2.0 sobre socket TCP** (puerto 7000 por defecto), arrancando
Guitarix en modo headless con `guitarix -N -p 7000`. Implementado en `engine/rpc_client.py`.

Detalle completo del protocolo en `docs/guitarix-integracion.md` y lista de métodos en
`docs/guitarix-rpc-methods.md`.

Guitarix también puede anunciarse en la red local por Avahi/mDNS, lo que permite que la PWA de
control remoto descubra el equipo sin que el usuario tenga que escribir una IP (Fase 5).

## Jerarquía de datos

Setlist › Bank (32) › Preset (8) → 256 por setlist. Modos: Preset / Stomp / Scene (igual que Quad Cortex).

La setlist es la fuente de verdad de la estructura de la performance y Guitarix la del estado de
DSP. Formato propio en JSON (`presets/schema.json`), no delegado al sistema de bancos de
Guitarix, porque éste no modela setlists, escenas, stomps ni tempo por tema, y porque el sync a
la nube necesita un formato portable. Ver `docs/presets.md`.

## Separación de procesos

- GUI **no** interfiere con audio: procesos separados, prioridades distintas.
- Server WiFi/remoto invisible para audio (core separado, prioridad mínima).
- Mobile = control remoto únicamente (no procesa audio).
- Preset change = pre-carga en RAM (cero gap de audio).
- Modo escenario = deshabilita todo lo no crítico al arrancar.

## Recursos estimados (i5 8va gen, 8GB RAM)

- Audio engine: 35-45% CPU
- NAM inference: 15-20% CPU
- GUI PyQt6: 3-5% CPU
- WiFi server: <1% CPU
- RAM total sistema: ~600MB
- Latencia target: 1-3ms con JACK + kernel RT

## Fases de construcción

1. Entorno Linux + Guitarix headless + JACK + interfaz de audio genérica → validar latencia
2. Python RPC → Guitarix + NAM funcionando → validar sonido. Incluye decidir si se integra
   NAM-rs como motor separado o si alcanza con la carga nativa de `.nam` que ya trae Guitarix
3. Sistema presets/bancos JSON + soporte MIDI genérico
4. GUI PyQt6 escenario
5. FastAPI server + PWA mobile control remoto
6. ISO booteable Debian USB
7. Cloud sync Supabase
8. Dual Rig + Scene Mode + Looper (v2)
