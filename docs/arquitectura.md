# Arquitectura

## Dispositivos de audio y MIDI

Decisión: el sistema **no** apunta a modelos específicos de interfaz de audio (ej. Scarlett, Tascam) ni de controlador MIDI (ej. pedal Wave). En su lugar:

- **Audio:** se apoya en el soporte nativo de ALSA para dispositivos USB Audio Class-compliant. Cualquier interfaz que cumpla el estándar funciona sin instalar drivers adicionales (a diferencia de Windows, donde cada fabricante requiere su propio driver).
- **MIDI:** mismo criterio con USB MIDI Class-compliant, vía ALSA/RtMidi. Cualquier controlador o pedal MIDI compatible con el estándar es reconocido automáticamente.
- **Configuración:** el propio sistema expone una pantalla (GUI PyQt6, módulo `gui/`) donde el usuario ve los dispositivos de audio y MIDI detectados y elige cuál usar. Esta selección se guarda como configuración del sistema (no hardcodeada).

Implicancia para `engine/`:
- `audio_engine.py` debe enumerar dispositivos ALSA/JACK disponibles en vez de asumir un dispositivo fijo.
- `midi_engine.py` debe enumerar puertos MIDI disponibles (ALSA seq) y permitir mapeo de mensajes MIDI (CC/PC/Note) configurable por el usuario, no atado a un pedal específico.

## Jerarquía de datos

Setlist › Bank (32) › Preset (8) → 256 por setlist. Modos: Preset / Stomp / Scene (igual que Quad Cortex).

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
2. Python RPC → Guitarix + NAM funcionando → validar sonido
3. Sistema presets/bancos JSON + soporte MIDI genérico
4. GUI PyQt6 escenario
5. FastAPI server + PWA mobile control remoto
6. ISO booteable Debian USB
7. Cloud sync Supabase
8. Dual Rig + Scene Mode + Looper (v2)
