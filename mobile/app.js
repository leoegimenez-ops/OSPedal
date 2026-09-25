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

/* Íconos propios (line-art original, no calcados de ningún producto comercial) + un color bien
 * distinto por categoría para que se note el contraste sobre fondo negro puro -- pedido
 * explícito el 25/09/2026, con capturas de Cortex Control como referencia de estilo (no de
 * arte: los glifos de acá son nuestros). "icono" es el contenido interno de un <svg
 * viewBox="0 0 24 24" fill="none" stroke="currentColor">. */
const ICONOS = {
  amp: '<rect x="4" y="8" width="16" height="8" rx="1.5"/><circle cx="8" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="16" cy="12" r="1.3"/>',
  cab: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="0.8" fill="currentColor"/>',
  neural: '<rect x="3" y="9" width="2" height="6"/><rect x="7" y="6" width="2" height="12"/><rect x="11" y="3" width="2" height="18"/><rect x="15" y="7" width="2" height="10"/><rect x="19" y="10" width="2" height="4"/>',
  overdrive: '<path d="M2.5 14h3l1.5-8 2 16 2-12 2 8 1.5-4h7"/>',
  echo: '<path d="M4 12a8 8 0 1 1 2.6 5.9"/><path d="M4 18.5v-5.5h5.5"/>',
  reverb: '<path d="M2.5 12a9.5 9.5 0 0 1 19 0"/><path d="M6 12a6 6 0 0 1 12 0"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/>',
  modulacion: '<path d="M2.5 12c1.4-4.2 2.8-4.2 4.2 0s2.8 4.2 4.2 0 2.8-4.2 4.2 0 2.8 4.2 4.2 0"/>',
  compresor: '<rect x="8.5" y="6" width="7" height="12" rx="1.5"/><path d="M3 12h4M17 12h4"/><path d="M6.5 9.5 3 12l3.5 2.5M17.5 9.5 21 12l-3.5 2.5"/>',
  eq: '<line x1="6.5" y1="3.5" x2="6.5" y2="20.5"/><circle cx="6.5" cy="9" r="2"/><line x1="12" y1="3.5" x2="12" y2="20.5"/><circle cx="12" cy="15.5" r="2"/><line x1="17.5" y1="3.5" x2="17.5" y2="20.5"/><circle cx="17.5" cy="7" r="2"/>',
  gate: '<path d="M4 12h4"/><path d="M9 5.5v13"/><path d="M15 5.5v13"/><path d="M16 12h4"/>',
  wah: '<path d="M2.5 16c2-.3 3-2 4-5.5S8.5 5 11 5s3.5 2.5 4.5 6 2 5.2 4 5.5"/>',
  escena: '<path d="M4 6.5h16v11H4z"/><path d="M4 6.5 12 12l8-5.5"/>',
  generico: '<circle cx="12" cy="12" r="3"/>',
};

const CATEGORIAS = [
  [/^amp/, "#FF6B5C", "amp"],
  [/^cab/, "#B98CFF", "cab"],
  [/^(nam|rtneural)/, "#E7E7EA", "neural"],
  [/^(ts9sim|fuzz)/, "#FFA724", "overdrive"],
  [/^echo/, "#3DD8D0", "echo"],
  [/^freeverb/, "#3DD68C", "reverb"],
  [/^chorus/, "#FF6FD8", "modulacion"],
  [/^compressor/, "#8B93A8", "compresor"],
  [/^eq/, "#5AA9FF", "eq"],
  [/^(noise_gate|abgate)/, "#FFE066", "gate"],
  [/wah/, "#7CE3A8", "wah"],
];

function categoria(id) {
  for (const [re, color, icono] of CATEGORIAS) if (re.test(id)) return { color, icono };
  return { color: "#4A4A55", icono: "generico" };
}
function colorNodo(id) { return categoria(id).color; }
function iconoSvg(clave, claseExtra) {
  return `<svg class="${claseExtra}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONOS[clave] || ICONOS.generico}</svg>`;
}

const LETRAS = ["A", "B", "C", "D", "E", "F", "G", "H"];
function letra(i) {
  return i < LETRAS.length ? LETRAS[i] : String.fromCharCode(65 + i); // I, J, ... si hiciera falta
}
// Colores para las escenas: no tienen "tipo" como una unidad del rack, así que se ciclan por
// posición -- da variedad visual sin inventarle una categoría que no existe en el modelo.
const COLORES_ESCENA = ["#FFA724", "#3DD8D0", "#B98CFF", "#3DD68C", "#FF6FD8", "#5AA9FF", "#FFE066", "#FF6B5C"];

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
    const cat = categoria(id);
    const nodo = document.createElement("button");
    nodo.className = "nodo" + (estadosOnOff[id] ? " encendido" : "") +
      (id === nodoSeleccionado ? " seleccionado" : "");
    nodo.style.setProperty("--nodo-color", cat.color);
    nodo.innerHTML = iconoSvg(cat.icono, "nodo-icono") +
      `<span class="nodo-etiqueta">${escapeHtml(id)}</span>`;
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

  // Grid A-H: cada escena ocupa el tile de su posición en la lista, con letra/color/ícono/
  // nombre -- pedido explícito el 25/09/2026, siguiendo el estilo de la pantalla STOMP de
  // Cortex Control que se compartió como referencia (no el contenido: las escenas acá son
  // variaciones de parámetros dentro de un preset, no unidades del rack -- por eso el ícono es
  // uno solo genérico de "escena", y el color se cicla por posición en vez de por tipo).
  const grid = document.createElement("div");
  grid.className = "escenas-grid";
  estadoLinea.escenas.forEach((nombre, i) => {
    const activa = nombre === estadoLinea.escena_activa;
    const color = COLORES_ESCENA[i % COLORES_ESCENA.length];
    const tile = document.createElement("button");
    tile.className = "escena-tile" + (activa ? " activa" : "");
    tile.style.setProperty("--escena-color", color);
    tile.innerHTML = `<span class="escena-letra">${letra(i)}</span>` +
      iconoSvg("escena", "escena-icono") +
      `<span class="escena-nombre">${escapeHtml(nombre)}</span>`;
    tile.addEventListener("click", () => ejecutarAccion("escena", i));
    grid.appendChild(tile);
  });
  $app.appendChild(grid);
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
