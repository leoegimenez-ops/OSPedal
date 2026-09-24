/* PWA de control remoto -- PedalSistema.
 *
 * Sin build step, sin framework: fetch() directo contra server/api.py, servido desde el mismo
 * origen (montado en /app dentro de la misma app de FastAPI), así que las rutas relativas
 * ("/estado", "/mezclador/matriz", "/lineas/...") funcionan igual en local que atrás de un
 * túnel público.
 *
 * Dos modos, elegidos arriba (MEZCLA / PRESET):
 *  - MEZCLA: las 5 mezclas de monitor -- gain/pan por fuente y por bus (engine/mixer.py).
 *  - PRESET: control de performance por línea de instrumento -- cambiar de preset, pisar
 *    stomps, cambiar de escena, tap tempo (engine/controlador.py, vía /lineas/*).
 * Cada línea de instrumento (guitarra1, guitarra2, bajo, voz) es su propia instancia de
 * Guitarix con su propia setlist -- por eso PRESET tiene su propio selector de línea, separado
 * del selector de bus de MEZCLA (son dos conjuntos de tabs distintos, con el mismo look).
 */

const $app = document.getElementById("app");
const $tabs = document.getElementById("tabs");
const $dot = document.getElementById("dot-conexion");
const $txtEstado = document.getElementById("txt-estado");
const $txtCpu = document.getElementById("txt-cpu");
const $btnModoMezcla = document.getElementById("btn-modo-mezcla");
const $btnModoPreset = document.getElementById("btn-modo-preset");

let modo = "mezcla";

// -- Estado de MEZCLA -----------------------------------------------------------------
let matriz = null;
let busActivo = null;
const temporizadores = {};   // debounce por control: clave "campo|fuente|bus" -> setTimeout id

// -- Estado de PRESET -------------------------------------------------------------------
let lineas = [];
let lineaActiva = null;
let estadoLinea = null;

async function cargarMatriz() {
  const resp = await fetch("/mezclador/matriz");
  if (!resp.ok) {
    const cuerpo = await resp.json().catch(() => ({}));
    throw new Error(cuerpo.detail || `HTTP ${resp.status}`);
  }
  matriz = await resp.json();
  if (!busActivo || !matriz.buses.includes(busActivo)) {
    busActivo = matriz.buses[0];
  }
}

async function cargarLineas() {
  const resp = await fetch("/lineas");
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  lineas = await resp.json();
  if (!lineaActiva || !lineas.includes(lineaActiva)) {
    lineaActiva = lineas[0];
  }
}

async function cargarEstadoLinea(nombre) {
  const resp = await fetch(`/lineas/${encodeURIComponent(nombre)}/estado`);
  if (!resp.ok) {
    const cuerpo = await resp.json().catch(() => ({}));
    throw new Error(cuerpo.detail || `HTTP ${resp.status}`);
  }
  estadoLinea = await resp.json();
}

// -- Cambio de modo ---------------------------------------------------------------------

async function cambiarModo(nuevo) {
  modo = nuevo;
  $btnModoMezcla.classList.toggle("activo", modo === "mezcla");
  $btnModoPreset.classList.toggle("activo", modo === "preset");
  $app.innerHTML = '<div class="cargando">Cargando…</div>';
  try {
    if (modo === "mezcla") {
      if (!matriz) await cargarMatriz();
    } else {
      if (!lineas.length) await cargarLineas();
      await cargarEstadoLinea(lineaActiva);
    }
  } catch (e) {
    $app.innerHTML = `<div class="error-carga">No se pudo cargar: ${e.message}</div>`;
    return;
  }
  renderTabs();
  renderApp();
}

$btnModoMezcla.addEventListener("click", () => cambiarModo("mezcla"));
$btnModoPreset.addEventListener("click", () => cambiarModo("preset"));

// -- Tabs (buses en modo mezcla, lineas en modo preset) ----------------------------------

function renderTabs() {
  $tabs.innerHTML = "";
  $tabs.hidden = false;
  const items = modo === "mezcla" ? matriz.buses : lineas;
  const activo = modo === "mezcla" ? busActivo : lineaActiva;
  for (const item of items) {
    const boton = document.createElement("button");
    boton.className = "tab" + (item === activo ? " activo" : "");
    boton.textContent = item;
    boton.addEventListener("click", async () => {
      if (modo === "mezcla") {
        busActivo = item;
        renderTabs();
        renderApp();
      } else {
        lineaActiva = item;
        renderTabs();
        $app.innerHTML = '<div class="cargando">Cargando…</div>';
        try {
          await cargarEstadoLinea(lineaActiva);
        } catch (e) {
          $app.innerHTML = `<div class="error-carga">No se pudo cargar: ${e.message}</div>`;
          return;
        }
        renderApp();
      }
    });
    $tabs.appendChild(boton);
  }
}

function renderApp() {
  $app.innerHTML = "";
  if (modo === "mezcla") renderBus(); else renderLinea();
}

// -- Modo MEZCLA --------------------------------------------------------------------------

function renderBus() {
  const modoBus = matriz.modo_bus[busActivo];

  const titulo = document.createElement("div");
  titulo.className = "bus-titulo";
  titulo.textContent = busActivo;
  $app.appendChild(titulo);

  const subtitulo = document.createElement("div");
  subtitulo.className = "bus-subtitulo";
  subtitulo.textContent = modoBus === "estereo" ? "Salida estéreo" : "Salida mono";
  $app.appendChild(subtitulo);

  for (const fuente of matriz.fuentes) {
    $app.appendChild(tarjetaFuente(fuente));
  }
}

function tarjetaFuente(fuente) {
  const celda = matriz.matriz[fuente][busActivo];
  const tarjeta = document.createElement("div");
  tarjeta.className = "fuente";

  const nombre = document.createElement("div");
  nombre.className = "fuente-nombre";
  nombre.textContent = fuente;
  tarjeta.appendChild(nombre);

  tarjeta.appendChild(controlSlider({
    etiqueta: "VOL",
    valorInicial: celda.ganancia,
    min: 0, max: 2, step: 0.01,
    formatear: (v) => v.toFixed(2),
    clase: "",
    onCambio: (v) => enviarCambioMezcla("ganancia", fuente, busActivo, v),
  }));

  tarjeta.appendChild(controlSlider({
    etiqueta: "PAN",
    valorInicial: celda.paneo,
    min: -1, max: 1, step: 0.01,
    formatear: formatearPaneo,
    clase: "paneo",
    onCambio: (v) => enviarCambioMezcla("paneo", fuente, busActivo, v),
  }));

  return tarjeta;
}

function formatearPaneo(v) {
  if (Math.abs(v) < 0.01) return "C";
  const lado = v < 0 ? "I" : "D";
  return Math.round(Math.abs(v) * 100) + lado;
}

function controlSlider({ etiqueta, valorInicial, min, max, step, formatear, clase, onCambio }) {
  const fila = document.createElement("div");
  fila.className = "control-fila";

  const label = document.createElement("span");
  label.className = "control-etiqueta";
  label.textContent = etiqueta;
  fila.appendChild(label);

  const input = document.createElement("input");
  input.type = "range";
  if (clase) input.className = clase;
  input.min = String(min);
  input.max = String(max);
  input.step = String(step);
  input.value = String(valorInicial);
  fila.appendChild(input);

  const valorTxt = document.createElement("span");
  valorTxt.className = "control-valor";
  valorTxt.textContent = formatear(valorInicial);
  fila.appendChild(valorTxt);

  input.addEventListener("input", () => {
    const v = parseFloat(input.value);
    valorTxt.textContent = formatear(v);
    onCambio(v);
  });

  return fila;
}

function enviarCambioMezcla(campo, fuente, bus, valor) {
  // Guarda el valor mas nuevo en la matriz local para que un re-render (otro control tocado
  // en la misma tarjeta) no pise este cambio con el valor viejo.
  matriz.matriz[fuente][bus][campo] = valor;

  const clave = `${campo}|${fuente}|${bus}`;
  clearTimeout(temporizadores[clave]);
  temporizadores[clave] = setTimeout(async () => {
    const ruta = campo === "ganancia" ? "/mezclador/ganancia" : "/mezclador/paneo";
    try {
      const resp = await fetch(ruta, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fuente, bus, valor }),
      });
      if (!resp.ok) {
        const cuerpo = await resp.json().catch(() => ({}));
        marcarEstado(false, cuerpo.detail || `HTTP ${resp.status}`);
      }
    } catch (e) {
      marcarEstado(false, "Sin conexión");
    }
  }, 120);
}

// -- Modo PRESET --------------------------------------------------------------------------

function renderLinea() {
  const header = document.createElement("div");
  header.className = "preset-header";
  header.innerHTML = `
    <div class="preset-nombre">${escapeHtml(estadoLinea.preset)}</div>
    <div class="preset-meta">BANCO ${estadoLinea.banco_visible + 1} · POSICIÓN ${estadoLinea.posicion_activa + 1}
      ${estadoLinea.tempo_bpm ? " · " + estadoLinea.tempo_bpm + " BPM" : ""}
      ${estadoLinea.escena_activa ? " · ESCENA " + escapeHtml(estadoLinea.escena_activa) : ""}</div>
  `;
  $app.appendChild(header);

  const mensaje = document.createElement("div");
  mensaje.className = "mensaje-linea";
  mensaje.id = "mensaje-linea";
  $app.appendChild(mensaje);

  const filaNav = document.createElement("div");
  filaNav.className = "fila-botones";
  filaNav.appendChild(botonAccion("ANTERIOR", "preset_anterior"));
  filaNav.appendChild(botonAccion("SIGUIENTE", "preset_siguiente"));
  $app.appendChild(filaNav);

  const filaExtra = document.createElement("div");
  filaExtra.className = "fila-botones";
  filaExtra.appendChild(botonAccion("AFINADOR", "afinador"));
  filaExtra.appendChild(botonAccion("TAP TEMPO", "tap_tempo", true));
  $app.appendChild(filaExtra);

  if (estadoLinea.stomps.length) {
    const tituloStomps = document.createElement("div");
    tituloStomps.className = "seccion-titulo";
    tituloStomps.textContent = "Stomps";
    $app.appendChild(tituloStomps);

    const listaStomps = document.createElement("div");
    listaStomps.className = "lista-toggle";
    estadoLinea.stomps.forEach((s, i) => {
      const chip = document.createElement("button");
      chip.className = "chip" + (s.activo ? " activo" : "");
      chip.textContent = s.etiqueta;
      chip.addEventListener("click", () => ejecutarAccion("toggle_stomp", i));
      listaStomps.appendChild(chip);
    });
    $app.appendChild(listaStomps);
  }

  if (estadoLinea.escenas.length) {
    const tituloEscenas = document.createElement("div");
    tituloEscenas.className = "seccion-titulo";
    tituloEscenas.textContent = "Escenas";
    $app.appendChild(tituloEscenas);

    const listaEscenas = document.createElement("div");
    listaEscenas.className = "lista-toggle";
    estadoLinea.escenas.forEach((nombre, i) => {
      const chip = document.createElement("button");
      chip.className = "chip" + (nombre === estadoLinea.escena_activa ? " escena-activa" : "");
      chip.textContent = nombre;
      chip.addEventListener("click", () => ejecutarAccion("escena", i));
      listaEscenas.appendChild(chip);
    });
    $app.appendChild(listaEscenas);
  }
}

function botonAccion(etiqueta, accion, acento) {
  const boton = document.createElement("button");
  boton.className = "btn-accion" + (acento ? " acento" : "");
  boton.textContent = etiqueta;
  boton.addEventListener("click", () => ejecutarAccion(accion, null));
  return boton;
}

async function ejecutarAccion(accion, parametro) {
  const $mensaje = document.getElementById("mensaje-linea");
  try {
    const resp = await fetch(`/lineas/${encodeURIComponent(lineaActiva)}/accion`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accion, parametro }),
    });
    const cuerpo = await resp.json();
    if (!resp.ok) {
      if ($mensaje) $mensaje.textContent = cuerpo.detail || `HTTP ${resp.status}`;
      return;
    }
    estadoLinea = cuerpo;
    renderApp();
    const $m2 = document.getElementById("mensaje-linea");
    if ($m2) $m2.textContent = cuerpo.mensaje || "";
  } catch (e) {
    if ($mensaje) $mensaje.textContent = "Sin conexión";
  }
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

// -- Barra de estado del motor (comun a los dos modos) -------------------------------------

function marcarEstado(ok, texto) {
  $dot.className = "dot" + (ok ? " ok" : "");
  $txtEstado.textContent = texto;
}

async function actualizarEstadoMotor() {
  try {
    const resp = await fetch("/estado");
    if (!resp.ok) {
      marcarEstado(false, "Motor desconectado");
      $txtCpu.textContent = "";
      return;
    }
    const datos = await resp.json();
    // "Arquitec DSP" es el nombre de marca cara al usuario -- el motor real (Guitarix) se
    // documenta en docs/guitarix-integracion.md, no en el texto que ve el musico.
    marcarEstado(true, `Arquitec DSP ${Array.isArray(datos.version) ? datos.version[2] : datos.version}`);
    $txtCpu.textContent = `CPU ${Number(datos.carga_cpu).toFixed(1)}%`;
  } catch (e) {
    marcarEstado(false, "Sin conexión");
    $txtCpu.textContent = "";
  }
}

async function iniciar() {
  $dot.className = "dot espera";
  await cambiarModo("mezcla");
  actualizarEstadoMotor();
  setInterval(actualizarEstadoMotor, 5000);
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

iniciar();
