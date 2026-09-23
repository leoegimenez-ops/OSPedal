# Referencia de métodos JSON-RPC de Guitarix

Extraído de `trunk/src/gx_head/engine/jsonrpc_methods.gperf_tmpl` del repo
[brummer10/guitarix](https://github.com/brummer10/guitarix). Es la lista autoritativa: ese
archivo es la fuente desde la que se genera la tabla de despacho del servidor.

La columna **Resultado** corresponde al flag `has_result`:

- **Sí** → el método devuelve un valor. Llamar con `id` y esperar respuesta.
- **No** → no devuelve nada. Llamar como notificación (sin `id`), sin round-trip.

Recordatorio: los parámetros van siempre como **array posicional**, nunca como objeto con
nombres. Ver `docs/guitarix-integracion.md`.

## Servidor

| Método | Resultado | Uso |
|---|---|---|
| `getversion` | Sí | Versión del motor. Útil como health check de la conexión |
| `shutdown` | No | Apaga el motor |
| `listen` | No | Suscribe a un grupo de eventos |
| `unlisten` | No | Cancela la suscripción |

## Motor

| Método | Resultado | Uso |
|---|---|---|
| `getstate` | Sí | Estado del motor |
| `setstate` | No | Cambia el estado del motor |
| `jack_cpu_load` | Sí | Carga de CPU de JACK. Clave para el monitor de rendimiento |
| `set_jack_insert` | No | Configura el insert de JACK |

## Parámetros

El modelo de datos de Guitarix es un mapa de parámetros con identificadores tipo
`amp.stage1.gain`. Todo control de efectos pasa por acá.

| Método | Resultado | Uso |
|---|---|---|
| `get` | Sí | Lee el valor de uno o más parámetros |
| `set` | No | Escribe parámetros. Es la llamada caliente del sistema |
| `parameterlist` | Sí | Lista completa de parámetros |
| `get_parameter` | Sí | Definición de un parámetro |
| `get_parameter_value` | Sí | Valor de un parámetro |
| `desc` | Sí | Descripción/metadatos de parámetros |
| `list` | Sí | Listado de parámetros |
| `insert_param` | No | Inserta un parámetro |
| `get_updates` | No | Solicita actualizaciones |

## Bancos y presets

Mapea directo sobre la jerarquía Setlist › Bank › Preset del proyecto.

| Método | Resultado | Uso |
|---|---|---|
| `banks` | Sí | Lista de bancos. **Forma real confirmada contra el motor (23/09/2026)**: no es una lista de nombres — es una lista de objetos `{"name", "mutable", "type", "presets"}`, con `presets` ya como lista de nombres de preset incluida ahí mismo (no hace falta un `presets(banco)` aparte si ya se tiene el resultado de `banks`). Ver `server/api.py`. |
| `setpreset` | No | Cambia el preset activo. Llamada crítica del pedal |
| `create_default_scratch_preset` | No | Crea preset temporal por defecto |
| `sendcc` | No | Envía un control change |
| `bank_insert_content` | Sí | Inserta contenido en un banco |
| `bank_insert_new` | Sí | Crea un banco nuevo |
| `get_bank` | Sí | Datos de un banco |
| `rename_bank` | Sí | Renombra un banco |
| `bank_remove` | Sí | Elimina un banco |
| `bank_get_contents` | Sí | Contenido de un banco |
| `bank_reorder` | No | Reordena bancos |
| `bank_check_reparse` | Sí | Reparsea bancos si cambiaron en disco |
| `bank_get_filename` | Sí | Ruta del archivo de un banco |
| `bank_set_flag` | No | Marca flags de banco |
| `convert_preset` | Sí | Convierte formato de preset |
| `bank_save` | No | Guarda el banco |
| `pf_save` | No | Guarda archivo de preset |
| `save_current` | No | Guarda el preset actual |
| `save_preset` | No | Guarda un preset |
| `presets` | Sí | Presets de un banco |
| `rename_preset` | Sí | Renombra un preset |
| `reorder_preset` | No | Reordena presets |
| `erase_preset` | No | Borra un preset |
| `pf_append` | No | Agrega preset al final |
| `pf_insert_before` | No | Inserta preset antes de otro |
| `pf_insert_after` | No | Inserta preset después de otro |

## Presets de unidad

| Método | Resultado | Uso |
|---|---|---|
| `plugin_preset_list_load` | Sí | Carga presets de un plugin |
| `plugin_preset_list_sync_set` | No | Sincroniza y aplica |
| `plugin_preset_list_set` | No | Aplica un preset de plugin |
| `plugin_preset_list_save` | No | Guarda preset de plugin |
| `plugin_preset_list_remove` | No | Elimina preset de plugin |

## Plugins y rack

Acá se arma la cadena de efectos: qué unidades están activas y en qué orden.

| Método | Resultado | Uso |
|---|---|---|
| `pluginlist` | Sí | Lista de plugins disponibles |
| `plugin_load_ui` | Sí | Definición de UI de un plugin |
| `get_rack_unit_order` | Sí | Orden actual de la cadena |
| `get_file_list` | Sí | Archivos disponibles (modelos NAM, IRs) |
| `insert_rack_unit` | No | Agrega una unidad a la cadena |
| `remove_rack_unit` | No | Quita una unidad de la cadena |
| `queryunit` | Sí | Consulta una unidad |

## Controlador MIDI

Soporta el mapeo genérico de cualquier pedalera o controlador class-compliant.

| Método | Resultado | Uso |
|---|---|---|
| `get_midi_controller_map` | Sí | Mapa CC → parámetro |
| `midi_size` | Sí | Cantidad de mapeos |
| `midi_deleteParameter` | No | Borra un mapeo |
| `midi_modifyCurrent` | No | Modifica el mapeo actual |
| `midi_get_config_mode` | Sí | Estado del modo aprendizaje |
| `midi_set_config_mode` | No | Activa modo aprendizaje (MIDI learn) |
| `midi_set_current_control` | No | Fija el control en edición |
| `set_midi_channel` | No | Canal MIDI |
| `request_midi_value_update` | No | Pide refresco de valores |
| `get_last_midi_control_value` | Sí | Último valor recibido |
| `set_last_midi_control_value` | No | Fija el último valor |
| `get_midi_feedback` | Sí | Estado del feedback MIDI |
| `set_midi_feedback` | No | Activa feedback MIDI hacia la pedalera |

`midi_set_config_mode` + `get_last_midi_control_value` es la base para implementar MIDI learn en
la GUI: el usuario mueve un control de su pedalera y el sistema lo asocia automáticamente, sin
necesidad de conocer el modelo del dispositivo.

## Afinador

| Método | Resultado | Uso |
|---|---|---|
| `get_tuning` | Sí | Afinación detectada |
| `get_tuner_freq` | Sí | Frecuencia detectada |
| `get_tuner_note` | Sí | Nota detectada |
| `switch_tuner` | No | Activa/desactiva el afinador |
| `tuner_used_for_display` | No | Afinador para display |
| `tuner_used_by_midi` | No | Afinador vía MIDI |

## Osciloscopio

| Método | Resultado | Uso |
|---|---|---|
| `set_oscilloscope_mul_buffer` | No | Configura el buffer |
| `get_oscilloscope_mul_buffer` | Sí | Lee el buffer |

## Convolver (impulse responses)

| Método | Resultado | Uso |
|---|---|---|
| `reload_impresp_list` | No | Recarga la lista de IRs |
| `load_impresp_dirs` | Sí | Directorios de IRs |
| `read_audio` | Sí | Lee un archivo de audio |

## LADSPA

| Método | Resultado | Uso |
|---|---|---|
| `load_ladspalist` | Sí | Carga la lista de plugins LADSPA |
| `save_ladspalist` | No | Guarda la lista |
| `ladspaloader_update_plugins` | Sí | Actualiza plugins |

## Control directo desde la guitarra

Permite cambiar presets tocando notas en la guitarra, sin tocar el pedal.

| Método | Resultado | Uso |
|---|---|---|
| `get_tuner_switcher_active` | Sí | Estado del switcher |
| `tuner_switcher_activate` | No | Activa |
| `tuner_switcher_deactivate` | No | Desactiva |
| `tuner_switcher_toggle` | No | Alterna |
