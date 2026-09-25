/* PWA de control remoto -- PedalSistema / Arquitec DSP.
 *
 * Sin build step, sin framework: fetch() directo contra server/api.py, servido desde el mismo
 * origen (montado en /app), así que las rutas relativas funcionan igual atrás de un túnel
 * público que en local.
 *
 * Cuatro pestañas fijas abajo (pensada primero para horizontal, como un pedal real de piso):
 *  - NODOS: la cadena de efectos de una línea como fila de bloques -- pantalla principal.
 *    Tocar un bloque abre sus parámetros (queryunit) y su on/off. Reemplaza lo que en otros
 *    sistemas es una pantalla de "stomps" aparte: acá encender/apagar un efecto es prender su
 *    propio nodo, no una lista separada.
 *  - PRESETS: nombre del preset activo, navegación, afinador, tap tempo.
 *  - ESCENAS: variaciones dentro del preset activo.
 *  - ENVÍOS: las 5 mezclas de monitor (engine/mixer.py) -- gain/pan por fuente y por bus.
 *
 * NODOS/PRESETS/ESCENAS trabajan sobre una LÍNEA de instrumento (una instancia de Guitarix);
 * ENVÍOS trabaja sobre un BUS de mezcla. Por eso la tira de "contexto" arriba del contenido
 * muestra líneas o buses según la pestaña activa -- son dos conjuntos de datos distintos.
 */

const $app = document.getElementById("app");
const $contexto = document.getElementById("contexto");
const $tabsPrincipales = document.getElementById("tabs-principales");
const $dot = document.getElementById("dot-conexion");
const $txtEstado = document.getElementById("txt-estado");
const $txtCpu = document.getElementById("txt-cpu");

let tabPrincipal = "nodos";

let lineas = [];
let lineaActiva = null;

// -- Estado de NODOS ----------------------------------------------------------------------
let cadena = [];
let estadosOnOff = {};       // "unidad" -> bool
let nodoSeleccionado = null;
let parametrosNodo = [];

// -- Estado de PRESETS / ESCENAS -----------------------------------------------------------
let estadoLinea = null;

// -- Estado de ENVÍOS (mezcla) -------------------------------------------------------------
let matriz = null;
let busActivo = null;
const temporizadores = {};   // debounce: clave -> setTimeout id

const COLOR_POR_UNIDAD = [
  [/^amp/, "#FF6B5C"],
  [/^cab/, "#B98CFF"],
  [/^(nam|rtneural)/, "#C9C8C4"],
  [/^(ts9sim|fuzz)/, "#FFA724"],
  [/^echo/, "#3DD8D0"],
  [/^freeverb/, "#3DD68C"],
  [/^chorus/, "#5FD9A4"],
  [/^compressor/, "#8B93A8"],
  [/^eq/, "#5AA9FF"],
];
function colorNodo(id) {
  for (const [re, color] of COLOR_POR_UNIDAD) if (re.test(id)) return color;
  return "#4A4A55";
}

async function pedir(ruta, opciones) {
  const resp = await fetch(ruta, opciones);
  if (!resp.ok) {
    const cuerpo = await resp.json().catch(() => ({}));
    throw new Error(cuerpo.detail || `HTTP ${resp.status}`);
  }
  return resp.status === 204 ? null : resp.json();
}

// -- Pestaña principal ----------------------------------------------------------------------

for (const boton of document.querySelectorAll(".tab-principal")) {
  boton.addEventListener("click", () => cambiarTabPrincipal(boton.dataset.tab));
}

async function cambiarTabPrincipal(tab) {
  tabPrincipal = tab;
  for (const boton of document.querySelectorAll(".tab-principal")) {
    boton.classList.toggle("activo", boton.dataset.tab === tab);
  }
  $app.innerHTML = '<div class="cargando">Cargando…</div>';
  try {
    if (tab === "envios") {
      if (!matriz) await cargarMatriz();
    } else {
      if (!lineas.length) await cargarLineas();
      if (tab === "nodos") await cargarNodos();
      else await cargarEstadoLinea(lineaActiva);
    }
  } catch (e) {
    $app.innerHTML = `<div class="error-carga">No se pudo cargar: ${e.message}</div>`;
    return;
  }
  renderContexto();
  renderApp();
}

function renderContexto() {
  $contexto.innerHTML = "";
  $contexto.hidden = false;
  const items = tabPrincipal === "envios" ? matriz.buses : lineas;
  const activo = tabPrincipal === "envios" ? busActivo : lineaActiva;
  for (const item of items) {
    const chip = document.createElement("button");
    chip.className = "chip-contexto" + (item === activo ? " activo" : "");
    chip.textContent = item;
    chip.addEventListener("click", async () => {
      if (tabPrincipal === "envios") {
        busActivo = item;
      } else {
        lineaActiva = item;
        nodoSeleccionado = null;
        $app.innerHTML = '<div class="cargando">Cargando…</div>';
        try {
          if (tabPrincipal === "nodos") await cargarNodos();
          else await cargarEstadoLinea(lineaActiva);
        } catch (e) {
          $app.innerHTML = `<div class="error-carga">No se pudo cargar: ${e.message}</div>`;
          return;
        }
      }
      renderContexto();
      renderApp();
    });
    $contexto.appendChild(chip);
  }
}

function renderApp() {
  $app.innerHTML = "";
  $app.classList.remove("dos-columnas");
  if (tabPrincipal === "nodos") renderNodos();
  else if (tabPrincipal === "presets") renderPresets();
  else if (tabPrincipal === "escenas") renderEscenas();
  else renderEnvios();
}

async function cargarLineas() {
  lineas = await pedir("/lineas");
  if (!lineaActiva || !lineas.includes(lineaActiva)) lineaActiva = lineas[0];
}

// -- NODOS ------------------------------------------------------------------------------------

async function cargarNodos() {
  cadena = await pedir(`/lineas/${encodeURIComponent(lineaActiva)}/cadena`);
  estadosOnOff = {};
  if (cadena.length) {
    const nombres = cadena.map((u) => `${u}.on_off`).join(",");
    const valores = await pedir(`/lineas/${encodeURIComponent(lineaActiva)}/parametros?nombres=${encodeURIComponent(nombres)}`);
    for (const u of cadena) estadosOnOff[u] = !!valores[`${u}.on_off`];
  }
  if (nodoSeleccionado && !cadena.includes(nodoSeleccionado)) nodoSeleccionado = null;
}

function renderNodos() {
  if (!cadena.length) {
    $app.innerHTML = '<div class="cargando">Esta línea no tiene unidades en la cadena.</div>';
    return;
  }

  const fila = document.createElement("div");
  fila.className = "cadena";
  cadena.forEach((id, i) => {
    if (i > 0) {
      const conector = document.createElement("div");
      conector.className = "nodo-conector";
      fila.appendChild(conector);
    }
    const nodo = document.createElement("button");
    nodo.className = "nodo" + (estadosOnOff[id] ? " encendido" : "") +
      (id === nodoSeleccionado ? " seleccionado" : "");
    nodo.style.setProperty("--nodo-color", colorNodo(id));
    nodo.textContent = id;
    nodo.addEventListener("click", () => seleccionarNodo(id));
    fila.appendChild(nodo);
  });
  $app.appendChild(fila);

  if (nodoSeleccionado) {
    $app.appendChild(panelParametrosNodo());
  }
}

async function seleccionarNodo(id) {
  if (nodoSeleccionado === id) {
    nodoSeleccionado = null;
    renderApp();
    return;
  }
  nodoSeleccionado = id;
  try {
    const cuerpo = await pedir(`/lineas/${encodeURIComponent(lineaActiva)}/unidad/${encodeURIComponent(id)}`);
    parametrosNodo = cuerpo.parametros;
  } catch (e) {
    parametrosNodo = [];
  }
  renderApp();
}

function panelParametrosNodo() {
  const panel = document.createElement("div");
  panel.className = "panel-parametros";

  const titulo = document.createElement("div");
  titulo.className = "panel-titulo";
  titulo.innerHTML = `<span class="panel-titulo-nombre">${escapeHtml(nodoSeleccionado)}</span>`;
  const cerrar = document.createElement("button");
  cerrar.className = "btn-cerrar-panel";
  cerrar.textContent = "CERRAR";
  cerrar.addEventListener("click", () => { nodoSeleccionado = null; renderApp(); });
  titulo.appendChild(cerrar);
  panel.appendChild(titulo);

  if (!parametrosNodo.length) {
    const vacio = document.createElement("div");
    vacio.className = "mensaje-linea";
    vacio.textContent = "Sin parámetros controlables desde acá.";
    panel.appendChild(vacio);
    return panel;
  }

  for (const p of parametrosNodo) {
    if (p.tipo === "bool") {
      panel.appendChild(controlToggle(p));
    } else {
      panel.appendChild(controlSliderParametro(p));
    }
  }
  return panel;
}

function controlToggle(p) {
  const fila = document.createElement("div");
  fila.className = "control-fila";
  const label = document.createElement("span");
  label.className = "control-etiqueta";
  label.textContent = p.etiqueta;
  fila.appendChild(label);

  const boton = document.createElement("button");
  boton.className = "toggle" + (p.valor ? " activo" : "");
  boton.textContent = p.valor ? "ON" : "OFF";
  boton.addEventListener("click", async () => {
    const nuevo = !p.valor;
    p.valor = nuevo;
    boton.className = "toggle" + (nuevo ? " activo" : "");
    boton.textContent = nuevo ? "ON" : "OFF";
    if (p.nombre.endsWith(".on_off")) {
      estadosOnOff[nodoSeleccionado] = nuevo;
      const nodoEl = $app.querySelector(".nodo.seleccionado");
      if (nodoEl) nodoEl.classList.toggle("encendido", nuevo);
    }
    await enviarParametroLinea(p.nombre, nuevo ? 1 : 0);
  });
  fila.appendChild(boton);
  return fila;
}

function controlSliderParametro(p) {
  return controlSlider({
    etiqueta: p.etiqueta,
    valorInicial: p.valor,
    min: p.min, max: p.max, step: p.paso || (p.max - p.min) / 100 || 0.01,
    formatear: (v) => v.toFixed(2),
    clase: "",
    onCambio: (v) => enviarParametroLinea(p.nombre, v),
  });
}

function enviarParametroLinea(nombre, valor) {
  clearTimeout(temporizadores[nombre]);
  temporizadores[nombre] = setTimeout(async () => {
    try {
      await pedir(`/lineas/${encodeURIComponent(lineaActiva)}/parametros`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pares: { [nombre]: valor } }),
      });
    } catch (e) {
      marcarEstado(false, e.message);
    }
  }, 120);
}

// -- PRESETS / ESCENAS --------------------------------------------------------------------

async function cargarEstadoLinea(nombre) {
  estadoLinea = await pedir(`/lineas/${encodeURIComponent(nombre)}/estado`);
}

function metaLinea() {
  return `BANCO ${estadoLinea.banco_visible + 1} · POSICIÓN ${estadoLinea.posicion_activa + 1}` +
    (estadoLinea.tempo_bpm ? ` · ${estadoLinea.tempo_bpm} BPM` : "") +
    (estadoLinea.escena_activa ? ` · ESCENA ${estadoLinea.escena_activa}` : "");
}

function renderPresets() {
  const header = document.createElement("div");
  header.className = "preset-header";
  header.innerHTML = `<div class="preset-nombre">${escapeHtml(estadoLinea.preset)}</div>
    <div class="preset-meta">${metaLinea()}</div>`;
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
}

function renderEscenas() {
  const header = document.createElement("div");
  header.className = "preset-header";
  header.innerHTML = `<div class="preset-nombre">${escapeHtml(estadoLinea.preset)}</div>
    <div class="preset-meta">${metaLinea()}</div>`;
  $app.appendChild(header);

  if (!estadoLinea.escenas.length) {
    const vacio = document.createElement("div");
    vacio.className = "mensaje-linea";
    vacio.textContent = "Este preset no tiene escenas.";
    $app.appendChild(vacio);
    return;
  }

  const lista = document.createElement("div");
  lista.className = "lista-chips";
  estadoLinea.escenas.forEach((nombre, i) => {
    const chip = document.createElement("button");
    chip.className = "chip" + (nombre === estadoLinea.escena_activa ? " activo" : "");
    chip.textContent = nombre;
    chip.addEventListener("click", () => ejecutarAccion("escena", i));
    lista.appendChild(chip);
  });
  $app.appendChild(lista);
}

function botonAccion(etiqueta, accion, acento) {
  const boton = document.createElement("button");
  boton.className = "btn-accion" + (acento ? " acento" : "");
  boton.textContent = etiqueta;
  boton.addEventListener("click", () => ejecutarAccion(accion, null));
  return boton;
}

async function ejecutarAccion(accion, parametro) {
  try {
    const cuerpo = await pedir(`/lineas/${encodeURIComponent(lineaActiva)}/accion`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accion, parametro }),
    });
    estadoLinea = cuerpo;
    renderApp();
    const $m = document.getElementById("mensaje-linea");
    if ($m) $m.textContent = cuerpo.mensaje || "";
  } catch (e) {
    const $m = document.getElementById("mensaje-linea");
    if ($m) $m.textContent = e.message;
  }
}

// -- ENVÍOS (mezcla) ------------------------------------------------------------------------

async function cargarMatriz() {
  matriz = await pedir("/mezclador/matriz");
  if (!busActivo || !matriz.buses.includes(busActivo)) busActivo = matriz.buses[0];
}

function renderEnvios() {
  $app.classList.add("dos-columnas");
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
    etiqueta: "VOL", valorInicial: celda.ganancia, min: 0, max: 2, step: 0.01,
    formatear: (v) => v.toFixed(2), clase: "",
    onCambio: (v) => enviarCambioMezcla("ganancia", fuente, busActivo, v),
  }));
  tarjeta.appendChild(controlSlider({
    etiqueta: "PAN", valorInicial: celda.paneo, min: -1, max: 1, step: 0.01,
    formatear: formatearPaneo, clase: "paneo",
    onCambio: (v) => enviarCambioMezcla("paneo", fuente, busActivo, v),
  }));
  return tarjeta;
}

function formatearPaneo(v) {
  if (Math.abs(v) < 0.01) return "C";
  return Math.round(Math.abs(v) * 100) + (v < 0 ? "I" : "D");
}

function enviarCambioMezcla(campo, fuente, bus, valor) {
  matriz.matriz[fuente][bus][campo] = valor;
  const clave = `mezcla|${campo}|${fuente}|${bus}`;
  clearTimeout(temporizadores[clave]);
  temporizadores[clave] = setTimeout(async () => {
    const ruta = campo === "ganancia" ? "/mezclador/ganancia" : "/mezclador/paneo";
    try {
      await pedir(ruta, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fuente, bus, valor }),
      });
    } catch (e) {
      marcarEstado(false, e.message);
    }
  }, 120);
}

// -- Controles genéricos --------------------------------------------------------------------

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

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

// -- Barra de estado del motor (comun a las 4 pestañas) ------------------------------------

function marcarEstado(ok, texto) {
  $dot.className = "dot" + (ok ? " ok" : "");
  $txtEstado.textContent = texto;
}

async function actualizarEstadoMotor() {
  try {
    const datos = await pedir("/estado");
    marcarEstado(true, `Arquitec DSP ${Array.isArray(datos.version) ? datos.version[2] : datos.version}`);
    $txtCpu.textContent = `CPU ${Number(datos.carga_cpu).toFixed(1)}%`;
  } catch (e) {
    marcarEstado(false, "Sin conexión");
    $txtCpu.textContent = "";
  }
}

async function iniciar() {
  $dot.className = "dot espera";
  await cambiarTabPrincipal("nodos");
  actualizarEstadoMotor();
  setInterval(actualizarEstadoMotor, 5000);
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

iniciar();
