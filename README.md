# PedalSistema (OSPedal)

Sistema operativo Linux dedicado para procesamiento de audio en vivo. Reemplaza hardware como Quad Cortex/Helix en una notebook común. Open source, gratuito, pensado para músicos sin presupuesto.

## Stack técnico

- **OS:** Debian minimal + Linux kernel 6.12+ (PREEMPT_RT nativo)
- **Audio server:** PipeWire + JACK2 (latencia 1-3ms)
- **Motor DSP:** Guitarix fork (C++) controlado via RPC socket
- **Amp sim:** NAM-rs (Rust, SIMD AVX2+FMA)
- **Orquestación:** Python 3.11
- **GUI desktop:** PyQt6 (modo escenario)
- **Control remoto:** FastAPI + WebSocket + PWA (mobile/tablet)
- **Sync nube:** Supabase (fase 7)
- **Distribución:** ISO booteable USB (live-build Debian)

## Hardware soportado

Cualquier interfaz de audio y cualquier controlador/pedal MIDI **class-compliant** (estándar USB Audio/MIDI Class). No requiere drivers de fabricante: el kernel Linux los detecta automáticamente. La selección y configuración del dispositivo de audio y del controlador MIDI se hace desde el propio sistema (pantalla de configuración), no hardcodeada por modelo.

## Estructura del repositorio

```
pedal-sistema/
├── docs/     ← arquitectura, módulos, hardware-setup
├── os/       ← live-build scripts, config JACK/ALSA/kernel
├── engine/   ← audio_engine.py, midi_engine.py, rpc_client.py
├── presets/  ← preset_manager.py, bank_manager.py, schema JSON
├── server/   ← api.py (FastAPI), websocket.py
├── gui/      ← main_window.py, stage_view.py, chain_view.py
├── mobile/   ← index.html, app.js, manifest.json (PWA)
└── models/   ← /nam/ y /irs/ (gitignored, pesan mucho)
```

## Licencia

GPL-3.0
