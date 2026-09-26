"use strict";
/* Arquitec DSP -- control remoto (tablet / celular) de PedalSistema.
 *
 * Réplica del layout de Cortex Control acordada con el usuario el 25/09/2026:
 *  - GRID: un instrumento por pantalla. Las dos filas son las dos cadenas REALES del motor, en
 *    serie: In -> fila mono -> "Row 2" -> fila estéreo -> Out 1/2. Tocar un bloque abre el panel
 *    de perillas abajo; "+" abre la grilla de categorías y después los modelos.
 *  - PRESETS: los 8 presets del banco como tiles 1A-1H.
 *  - GIG: grilla A-H con modo STOMP (efectos on/off) o SCENE (escenas, "+" crea una nueva).
 *  - SENDS: consola con fader vertical + perilla de paneo por instrumento, un bus a la vez.
 * Sin framework ni build: fetch() contra server/api.py, servido en el mismo origen (/app).
 */

const $ = (id) => document.getElementById(id);
const $contenido = $("contenido");
const $panel = $("panel-bloque");
const $velo = $("velo");
const $popover = $("popover");
const $selector = $("selector");
const $aviso = $("aviso");

const LETRAS = "ABCDEFGH".split("");
const ETIQUETA_LINEA = { guitarra1: "GTR 1", guitarra2: "GTR 2", bajo: "BASS", voz: "VOX" };
const ETIQUETA_BUS = { monitor1: "MON 1", monitor2: "MON 2", monitor3: "MON 3", monitor4: "MON 4", pa: "PA" };
const etiquetaLinea = (l) => ETIQUETA_LINEA[l] || String(l).toUpperCase();
const etiquetaBus = (b) => ETIQUETA_BUS[b] || String(b).toUpperCase();

/* Íconos propios, trazo blanco sobre cuadrado negro con borde de color -- mismo estilo que la
 * leyenda de referencia, dibujo nuestro. viewBox 24x24. */
const CATEGORIAS = {
  amp:        { nombre: "Amp",            color: "#EF4444", icono: '<rect x="3" y="6.5" width="18" height="11" rx="2"/><path d="M6.5 10.5h11M6.5 13.5h11"/>' },
  neural:     { nombre: "Neural Capture", color: "#F4F4F5", icono: '<circle cx="12" cy="12" r="8"/><path d="M8 6.5h8M5.5 9.3h13M4.2 12h15.6M5.5 14.7h13M8 17.5h8"/>' },
  cab:        { nombre: "Cab",            color: "#7C3AED", icono: '<circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="1.7"/><circle cx="4.5" cy="4.5" r=".9" class="relleno"/><circle cx="19.5" cy="4.5" r=".9" class="relleno"/><circle cx="4.5" cy="19.5" r=".9" class="relleno"/><circle cx="19.5" cy="19.5" r=".9" class="relleno"/>' },
  ir:         { nombre: "IR Loader",      color: "#A5B4FC", icono: '<path d="M4 12h1.5M6.5 6v12M10 9v6M13.5 4v16M17 9.5v5M20 11v2"/>' },
  overdrive:  { nombre: "Overdrive",      color: "#F97316", icono: '<path d="M3 13c3.2-10 6.2-10 9-1s5.8 9 9-1"/>' },
  compressor: { nombre: "Compressor",     color: "#22C55E", icono: '<path d="M3.5 12.5c1.6-3.5 3.3-3.5 5 0s3.4 3.5 5 0 3.4-3.5 5 0 1.8 2 2 1.5"/><path d="M12 2.5v4.5M10.2 5.3 12 7l1.8-1.7M12 21.5V17M10.2 18.7 12 17l1.8 1.7"/>' },
  eq:         { nombre: "EQ",             color: "#3B82F6", icono: '<path d="M6 4v16M12 4v16M18 4v16"/><rect x="4" y="12.5" width="4" height="3" rx="1" class="relleno"/><rect x="10" y="6.5" width="4" height="3" rx="1" class="relleno"/><rect x="16" y="14.5" width="4" height="3" rx="1" class="relleno"/>' },
  filter:     { nombre: "Filter",         color: "#7DD3FC", icono: '<path d="M3 8h9.5c2.5 0 3.5 2 4.5 5l2.5 6"/>' },
  wah:        { nombre: "Wah",            color: "#D4D4D8", icono: '<rect x="7" y="3" width="10" height="18" rx="2.5"/><rect x="9.5" y="6" width="5" height="8.5" rx="1.2"/>' },
  pitch:      { nombre: "Pitch",          color: "#EAB308", icono: '<path d="M3 17h5.5c3.5 0 3-10 7-10H21"/>' },
  modulation: { nombre: "Modulation",     color: "#6366F1", icono: '<path d="M3 12c1.5-5.5 3-5.5 4.5 0s3 5.5 4.5 0 3-5.5 4.5 0 3 5.5 4.5 0"/>' },
  delay:      { nombre: "Delay",          color: "#14B8A6", icono: '<circle cx="6.5" cy="12" r="3"/><path d="M12.5 7.5a6.5 6.5 0 0 1 0 9"/><path d="M16.5 4.5a10.5 10.5 0 0 1 0 15" opacity=".5"/>' },
  reverb:     { nombre: "Reverb",         color: "#22D3EE", icono: '<path d="M12 3.5l8 4v9l-8 4-8-4v-9z"/><path d="M4 7.5l8 4 8-4M12 11.5v9"/>' },
  looper:     { nombre: "Looper",         color: "#EC4899", icono: '<circle cx="7" cy="11" r="3.5"/><circle cx="17" cy="11" r="3.5"/><path d="M7 14.5h10M9 18.5h6"/>' },
  utility:    { nombre: "Utility",        color: "#71717A", icono: '<path d="M5 19 9.5 5M5 19l8-11.5M5 19l11.5-6.5M5 19l13-1.5"/>' },
};
const ICONO_ESCENA = '<path d="M12 3.5 21 8l-9 4.5L3 8z"/><path d="M3 12l9 4.5 9-4.5M3 16l9 4.5 9-4.5"/>';
const ICONO_MAS = '<path d="M12 5v14M5 12h14"/>';
const COLORES_ESCENA = ["#F97316", "#38BDF8", "#22C55E", "#EF4444", "#14B8A6", "#8B5CF6", "#EAB308", "#EC4899"];

const svg = (interior, vb = "0 0 24 24") => `<svg viewBox="${vb}">${interior}</svg>`;
const cat = (c) => CATEGORIAS[c] || CATEGORIAS.utility;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

const estado = {
  tab: "grid",
  lineas: [],
  linea: null,
  linea_estado: null,
  grid: null,
  seleccion: null,        // { id, estereo }
  parametros: [],         // del bloque seleccionado
  gigModo: "stomp",
  matriz: null,
  bus: null,
  motor: null,            // última respuesta de /estado, para el menú
};

// -- Utilidades ----------------------------------------------------------------------------

// Identifica a esta pantalla ante el servidor: los avisos de /sync que ella misma provocó se
// ignoran (ya los tiene aplicados).
const ID_CLIENTE = Math.random().toString(36).slice(2, 10);

async function api(ruta, cuerpo) {
  const opciones = cuerpo === undefined ? { headers: { "X-Cliente": ID_CLIENTE } } : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Cliente": ID_CLIENTE },
    body: JSON.stringify(cuerpo),
  };
  const resp = await fetch(ruta, opciones);
  const datos = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(datos.detail || `HTTP ${resp.status}`);
  return datos;
}
const rutaLinea = () => `/lineas/${encodeURIComponent(estado.linea)}`;

let tAviso = null;
function aviso(texto, esError = false) {
  $aviso.textContent = texto;
  $aviso.className = "aviso" + (esError ? " error" : "");
  $aviso.hidden = false;
  clearTimeout(tAviso);
  tAviso = setTimeout(() => { $aviso.hidden = true; }, 2200);
}

const temporizadores = {};
function diferir(clave, fn, ms = 90) {
  clearTimeout(temporizadores[clave]);
  temporizadores[clave] = setTimeout(fn, ms);
}

const limitar = (v, a, b) => Math.min(b, Math.max(a, v));

function nuevo(tag, clase, html) {
  const el = document.createElement(tag);
  if (clase) el.className = clase;
  if (html !== undefined) el.innerHTML = html;
  return el;
}

// -- Carga de datos --------------------------------------------------------------------------

async function cargarLinea() {
  const [e, g] = await Promise.all([api(`${rutaLinea()}/estado`), api(`${rutaLinea()}/grid`)]);
  estado.linea_estado = e;
  estado.grid = g;
  if (estado.seleccion && !unidadSeleccionada()) estado.seleccion = null;
}

async function recargarGrid() {
  estado.grid = await api(`${rutaLinea()}/grid`);
  if (estado.seleccion && !unidadSeleccionada()) estado.seleccion = null;
  if (estado.seleccion) await cargarParametros();
}

async function cargarParametros() {
  const s = estado.seleccion;
  // Ids calificados por línea ("a/ts9sim"): la barra es parte de la ruta, no se codifica.
  const ruta = s.id.split("/").map(encodeURIComponent).join("/");
  const r = await api(`${rutaLinea()}/unidad/${ruta}`);
  estado.parametros = r.parametros;
}

function itemsGrid() {
  const g = estado.grid;
  return g ? [...(g.principal || []), ...(g.paralela || [])] : [];
}

function unidadSeleccionada() {
  const s = estado.seleccion;
  if (!s) return null;
  return itemsGrid().find((x) => x.id === s.id) || null;
}

/* `textoAviso(estadoNuevo)` arma el aviso en inglés -- los mensajes del controlador vienen en
 * castellano (son los del display de la pedalera), la app es en inglés. */
async function accion(nombre, parametro = null, textoAviso = null) {
  try {
    const r = await api(`${rutaLinea()}/accion`, { accion: nombre, parametro });
    estado.linea_estado = r;
    await recargarGrid().catch(() => {});
    render();
    if (r.advertencia) aviso(`Base preset not found in engine — applied the rest`, true);
    else if (textoAviso) aviso(textoAviso(r));
  } catch (e) {
    aviso(e.message, true);
  }
}

async function cambiarLinea(linea) {
  estado.linea = linea;
  estado.seleccion = null;
  estado.linea_estado = null;
  estado.grid = null;
  render();
  try {
    await cargarLinea();
  } catch (e) {
    mostrarErrorLinea(e.message);
    return;
  }
  render();
}

// -- Render general ----------------------------------------------------------------------------

function render() {
  // La barra superior (preset, 💾, ⋮, escenas) va solo en GRID -- pedido del usuario 25/09:
  // en las demás pestañas estorba y en el celular horizontal les robaba la altura.
  document.body.dataset.tab = estado.tab;
  renderCabecera();
  for (const b of document.querySelectorAll(".tab")) b.classList.toggle("activo", b.dataset.tab === estado.tab);
  if (estado.tab === "grid") renderGrid();
  else if (estado.tab === "presets") renderPresets();
  else if (estado.tab === "gig") renderGig();
  else renderSends();
  renderPanel();
}

function renderCabecera() {
  const e = estado.linea_estado;
  $("cab-codigo").textContent = e ? `${e.banco_activo + 1}${LETRAS[e.posicion_activa] || ""}` : "–";
  $("cab-preset").textContent = e ? e.preset : (estado.linea ? etiquetaLinea(estado.linea) : "Loading…");
  const cont = $("cab-escenas");
  cont.innerHTML = "";
  if (!e) return;
  e.escenas.forEach((nombre, i) => {
    const b = nuevo("button", "letra-escena" + (nombre === e.escena_activa ? " activa" : ""), LETRAS[i] || "?");
    b.type = "button";
    b.title = nombre;
    b.addEventListener("click", () => accion("escena", i));
    cont.appendChild(b);
  });
}

/* Motor de la línea caído o sin arrancar: se reintenta solo cada 3 s mientras sigamos en esa
 * línea, así la pantalla vuelve sola cuando el motor vuelve -- sin tener que recargar. */
let tReintento = null;
function mostrarErrorLinea(mensaje) {
  const linea = estado.linea;
  clearTimeout(tReintento);
  tReintento = setTimeout(async () => {
    if (estado.linea !== linea || estado.linea_estado) return;
    try {
      await cargarLinea();
      render();
    } catch (e) {
      if (estado.linea === linea) mostrarErrorLinea(e.message);
    }
  }, 3000);
  $contenido.innerHTML = "";
  const caja = nuevo("div", "mensaje-centro error");
  const interior = nuevo("div");
  interior.appendChild(nuevo("div", "", `${esc(etiquetaLinea(estado.linea))} engine offline — retrying…`));
  interior.appendChild(nuevo("div", "tile-nota", esc(mensaje)));
  const opciones = nuevo("div", "segmentado");
  opciones.style.marginTop = "14px";
  for (const l of estado.lineas) {
    const b = nuevo("button", l === estado.linea ? "activo" : "", esc(etiquetaLinea(l)));
    b.addEventListener("click", () => cambiarLinea(l));
    opciones.appendChild(b);
  }
  interior.appendChild(opciones);
  caja.appendChild(interior);
  $contenido.appendChild(caja);
}

// -- GRID ----------------------------------------------------------------------------------
//
// Como Cortex: una fila por línea.
//   fila principal: In → [bloques] ◆SPLIT [línea A] ◆MERGE [después] + → Out
//   fila paralela:  sin paralelo, un punto ● para arrastrar a la fila de arriba (crea el SPLIT);
//                   con paralelo, la línea B cuelga del SPLIT y vuelve en el MERGE.
// Por dentro cada tramo es un motor aparte (engine/disposicion.py); la app solo manda la
// disposición nueva (/grid/disponer) y el servidor mueve los bloques entre motores.

const ICONO_SPLIT = '<path d="M3 12h6"/><path d="M9 12c3 0 4-5 7-5h5M9 12c3 0 4 5 7 5h5"/>';
const ICONO_MERGE = '<path d="M3 7h5c3 0 4 5 7 5M3 17h5c3 0 4-5 7-5"/><path d="M15 12h6"/>';

function renderGrid() {
  $contenido.innerHTML = "";
  const g = estado.grid;
  if (!g) {
    $contenido.appendChild(nuevo("div", "mensaje-centro", "Loading…"));
    return;
  }
  const scroll = nuevo("div", "grid-scroll");
  const lienzo = nuevo("div", "grid-lienzo");
  const lineas = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  lineas.classList.add("grid-lineas");
  lienzo.appendChild(lineas);

  // Fila principal
  const f1 = nuevo("div", "fila fila-principal");
  const inBtn = nuevo("button", "extremo in", `In<small>${esc(etiquetaLinea(estado.linea))}</small>`);
  inBtn.type = "button";
  inBtn.addEventListener("click", () => menuInstrumento(inBtn));
  f1.appendChild(inBtn);
  for (const it of g.principal || []) f1.appendChild(crearItemGrid(it));
  if (g.split) {
    // Espaciador antes del MERGE para que la línea B (abajo) nunca pase más allá del MERGE.
    const merge = f1.querySelector('[data-id="@merge"]');
    f1.insertBefore(nuevo("div", "separador-a"), merge);
  }
  const mas1 = nuevo("button", "bloque mas", svg(ICONO_MAS));
  mas1.type = "button";
  mas1.title = g.split ? "Add block after the merge" : "Add block";
  mas1.addEventListener("click", () => abrirSelector(g.split ? "post" : "pre"));
  f1.appendChild(mas1);
  f1.appendChild(nuevo("div", "fila-relleno"));
  f1.appendChild(nuevo("div", "extremo solo-texto", "Out<small>1/2</small>"));
  lienzo.appendChild(f1);

  // Fila paralela
  const f2 = nuevo("div", "fila fila-paralela");
  if (g.split) {
    f2.appendChild(nuevo("div", "separador-b"));
    for (const it of g.paralela || []) f2.appendChild(crearItemGrid(it));
    const mas2 = nuevo("button", "bloque mas", svg(ICONO_MAS));
    mas2.type = "button";
    mas2.title = "Add block to line B";
    mas2.addEventListener("click", () => abrirSelector("b"));
    f2.appendChild(mas2);
  } else {
    const punto = nuevo("button", "punto-split", "");
    punto.type = "button";
    punto.title = "Drag onto the row above to create a parallel line";
    habilitarPuntoSplit(punto, f1);
    f2.append(punto, nuevo("div", "pista-split", "Drag ● onto the row above to split the signal"));
  }
  lienzo.appendChild(f2);

  scroll.appendChild(lienzo);
  $contenido.appendChild(scroll);
  requestAnimationFrame(() => {
    if (g.split) alinearParalela(f1, f2);
    dibujarLineas(lienzo, lineas, f1, f2, g.split);
  });
}

function crearItemGrid(it) {
  const sel = estado.seleccion && estado.seleccion.id === it.id;
  if (it.tipo === "split" || it.tipo === "merge") {
    const n = nuevo("button", "nodo-ruteo" + (sel ? " seleccionado" : ""),
      svg(it.tipo === "split" ? ICONO_SPLIT : ICONO_MERGE));
    n.type = "button";
    n.title = it.tipo === "split" ? "Split (tap: A/B balance)" : "Merge (tap: level, pan, phase)";
    n.dataset.id = it.id;
    const menu = () => abrirPopover(n, [{ texto: "Remove parallel line", accion: quitarLinea }]);
    habilitarArrastre(n, () => seleccionarBloque(it.id), menu, { soloPrincipal: true });
    n.addEventListener("contextmenu", (ev) => { ev.preventDefault(); menu(); });
    return n;
  }
  const b = nuevo("button", "bloque" + (it.encendido ? "" : " apagado") + (sel ? " seleccionado" : ""),
    svg(cat(it.categoria).icono));
  b.type = "button";
  b.title = it.nombre;
  b.dataset.id = it.id;
  b.style.setProperty("--color", cat(it.categoria).color);
  if (it.pie !== null && it.pie !== undefined) b.appendChild(nuevo("span", "insignia-pie", LETRAS[it.pie]));
  habilitarArrastre(b, () => seleccionarBloque(it.id), () => menuStomp(b, it), {});
  b.addEventListener("contextmenu", (ev) => { ev.preventDefault(); menuStomp(b, it); });
  return b;
}

/* La línea B arranca justo debajo del SPLIT, y el tramo A se estira (espaciador) hasta que el
 * MERGE quede a la derecha del final de B: así las líneas nunca se cruzan. */
function alinearParalela(f1, f2) {
  const split = f1.querySelector('[data-id="@split"]');
  const merge = f1.querySelector('[data-id="@merge"]');
  const sepB = f2.querySelector(".separador-b");
  const sepA = f1.querySelector(".separador-a");
  if (!split || !merge || !sepB || !sepA) return;
  const hueco = parseFloat(getComputedStyle(f2).columnGap || getComputedStyle(f2).gap) || 0;
  const r2 = f2.getBoundingClientRect();
  const rs = split.getBoundingClientRect();
  sepB.style.width = `${Math.max(0, rs.right - r2.left - hueco)}px`;
  const finB = f2.querySelector(".bloque.mas").getBoundingClientRect().right;
  const rm = merge.getBoundingClientRect();
  sepA.style.width = `${Math.max(0, finB + hueco - rm.left)}px`;
}

/* Líneas de conexión, medidas de los elementos reales. Los bloques tapan la línea con su fondo. */
function dibujarLineas(lienzo, svgEl, f1, f2, conSplit) {
  const base = lienzo.getBoundingClientRect();
  const w = lienzo.scrollWidth;
  const h = lienzo.scrollHeight;
  svgEl.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svgEl.setAttribute("width", w);
  svgEl.setAttribute("height", h);
  const centro = (el) => {
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2 - base.left, y: r.top + r.height / 2 - base.top, r };
  };
  const ex = f1.querySelectorAll(".extremo");
  const a = centro(ex[0]);
  const z = centro(ex[ex.length - 1]);
  let html = `<line x1="${a.r.right - base.left}" y1="${a.y}" x2="${z.r.left - base.left}" y2="${a.y}"/>`;
  if (conSplit) {
    const s = centro(f1.querySelector('[data-id="@split"]'));
    const m = centro(f1.querySelector('[data-id="@merge"]'));
    const y2 = centro(f2.querySelector(".bloque.mas")).y;
    const r = 10;
    html += `<path d="M${s.x} ${s.y} V${y2 - r} Q${s.x} ${y2} ${s.x + r} ${y2} H${m.x - r} ` +
      `Q${m.x} ${y2} ${m.x} ${y2 - r} V${m.y}"/>`;
  } else {
    const p = centro(f2.querySelector(".punto-split"));
    html += `<line class="tenue" x1="${p.x}" y1="${p.y}" x2="${p.x + 70}" y2="${p.y}"/>`;
  }
  svgEl.innerHTML = html;
}

/* El punto ● de la fila vacía: arrastrarlo y soltarlo en la fila de arriba, entre dos bloques,
 * crea la línea paralela ahí (SPLIT) y la junta al final (MERGE) -- como Cortex. */
function habilitarPuntoSplit(punto, f1) {
  punto.addEventListener("pointerdown", (ev) => {
    if (ev.button > 0) return;
    ev.preventDefault();
    const fantasma = nuevo("div", "punto-split fantasma-punto");
    document.body.appendChild(fantasma);
    const marca = nuevo("div", "marca-insercion");
    const mover = (e) => {
      fantasma.style.left = `${e.clientX - 9}px`;
      fantasma.style.top = `${e.clientY - 9}px`;
      const r1 = f1.getBoundingClientRect();
      const encima = e.clientY > r1.top - 30 && e.clientY < r1.bottom + 20;
      marca.remove();
      if (encima) {
        const destino = [...f1.querySelectorAll("[data-id]")].find((b) => {
          const r = b.getBoundingClientRect();
          return e.clientX < r.left + r.width / 2;
        });
        f1.insertBefore(marca, destino || f1.querySelector(".bloque.mas"));
      }
    };
    const soltar = async (e) => {
      removeEventListener("pointermove", mover);
      removeEventListener("pointerup", soltar);
      removeEventListener("pointercancel", soltar);
      fantasma.remove();
      if (!marca.parentNode || e.type === "pointercancel") { marca.remove(); return; }
      const ids = [...f1.children].filter((c) => c.dataset && (c.dataset.id || c === marca))
        .map((c) => (c === marca ? "@split" : c.dataset.id));
      marca.remove();
      await disponer([...ids, "@merge"], [], "Creating the parallel line… (first time takes a few seconds)");
    };
    mover(ev);
    addEventListener("pointermove", mover);
    addEventListener("pointerup", soltar);
    addEventListener("pointercancel", soltar);
  });
}

async function disponer(principal, paralela, avisoEspera = null) {
  let t = null;
  if (avisoEspera) t = setTimeout(() => aviso(avisoEspera), 400);
  try {
    const r = await api(`${rutaLinea()}/grid/disponer`, { principal, paralela });
    estado.grid = r;
    if (r.avisos && r.avisos.length) aviso(r.avisos[0]);
    else aviso(avisoEspera ? "Parallel line created" : "Order changed");
  } catch (e) {
    aviso(e.message, true);
  } finally {
    clearTimeout(t);
  }
  if (estado.seleccion && !unidadSeleccionada()) estado.seleccion = null;
  render();
}

async function quitarLinea() {
  try {
    estado.grid = await api(`${rutaLinea()}/grid/quitar_linea`, {});
    estado.seleccion = null;
    render();
    aviso("Parallel line removed");
  } catch (e) {
    aviso(e.message, true);
  }
}

/* Arrastrar para reordenar, dentro de una fila o entre las dos líneas. Un toque corto
 * selecciona (abre perillas); si el dedo se mueve más de 8 px, el bloque se levanta: un
 * "fantasma" sigue al dedo y el original queda como hueco que se corre entre los demás. Al
 * soltar se manda la disposición nueva al servidor: el cambio suena, no es solo visual.
 * SPLIT y MERGE se arrastran igual, pero solo dentro de la fila principal. */
function habilitarArrastre(el, alTocar, alMantener, { soloPrincipal = false } = {}) {
  let inicio = null;
  let fantasma = null;
  let dispInicial = null;
  let tMantener = null;
  const MANTENER_MS = 500;   // mantener apretado sin mover = menú (stomp A-H / quitar línea)

  const disposicionActual = () => {
    const f1 = document.querySelector(".fila-principal");
    const f2 = document.querySelector(".fila-paralela");
    const ids = (f) => (f ? [...f.querySelectorAll("[data-id]")].map((b) => b.dataset.id) : []);
    return { principal: ids(f1), paralela: ids(f2) };
  };

  // Eventos en `window`, no setPointerCapture: mover el bloque en el DOM (para correr el hueco)
  // le hace perder la captura al navegador y el arrastre quedaba colgado a mitad de camino.
  const alMover = (ev) => mover(ev);
  const alSoltar = (ev) => terminar(ev, false);
  const alCancelar = (ev) => terminar(ev, true);

  el.addEventListener("pointerdown", (ev) => {
    if (ev.button > 0) return;
    inicio = { x: ev.clientX, y: ev.clientY, id: ev.pointerId };
    addEventListener("pointermove", alMover);
    addEventListener("pointerup", alSoltar);
    addEventListener("pointercancel", alCancelar);
    clearTimeout(tMantener);
    if (alMantener && ev.pointerType !== "mouse") {   // con mouse está el clic derecho
      tMantener = setTimeout(() => {
        if (!inicio || fantasma) return;
        soltarEscuchas();
        inicio = null;
        if (navigator.vibrate) navigator.vibrate(15);
        alMantener();
      }, MANTENER_MS);
    }
  });

  function soltarEscuchas() {
    clearTimeout(tMantener);
    removeEventListener("pointermove", alMover);
    removeEventListener("pointerup", alSoltar);
    removeEventListener("pointercancel", alCancelar);
  }

  function filaBajo(y) {
    const f1 = document.querySelector(".fila-principal");
    const f2 = document.querySelector(".fila-paralela");
    if (soloPrincipal || !estado.grid.split || !f2) return f1;
    const r1 = f1.getBoundingClientRect();
    const r2 = f2.getBoundingClientRect();
    return Math.abs(y - (r1.top + r1.height / 2)) <= Math.abs(y - (r2.top + r2.height / 2)) ? f1 : f2;
  }

  function mover(ev) {
    if (!inicio || ev.pointerId !== inicio.id) return;
    const dx = ev.clientX - inicio.x;
    const dy = ev.clientY - inicio.y;
    if (!fantasma) {
      if (Math.hypot(dx, dy) < 8) return;
      clearTimeout(tMantener);
      dispInicial = disposicionActual();
      const r = el.getBoundingClientRect();
      fantasma = el.cloneNode(true);
      fantasma.classList.add("fantasma");
      fantasma.style.width = `${r.width}px`;
      fantasma.style.height = `${r.height}px`;
      fantasma.style.left = `${r.left}px`;
      fantasma.style.top = `${r.top}px`;
      document.body.appendChild(fantasma);
      el.classList.add("hueco-arrastre");
    }
    fantasma.style.transform = `translate(${dx}px, ${dy}px) scale(1.08)`;
    const fila = filaBajo(ev.clientY);
    // ¿Delante de qué elemento cae? El primero cuyo centro queda a la derecha del dedo.
    const otros = [...fila.querySelectorAll("[data-id]")].filter((b) => b !== el);
    const destino = otros.find((b) => {
      const r = b.getBoundingClientRect();
      return ev.clientX < r.left + r.width / 2;
    });
    let referencia = destino || fila.querySelector(".bloque.mas");
    if (referencia && referencia.previousElementSibling && referencia.previousElementSibling.classList.contains("separador-a")) {
      referencia = referencia.previousElementSibling;    // no meterse entre el espaciador y el MERGE
    }
    if (referencia && el.nextElementSibling !== referencia) fila.insertBefore(el, referencia);
    const scroll = fila.closest(".grid-scroll");
    if (scroll) {
      const rs = scroll.getBoundingClientRect();
      if (ev.clientX < rs.left + 40) scroll.scrollLeft -= 12;
      else if (ev.clientX > rs.right - 40) scroll.scrollLeft += 12;
    }
  }

  async function terminar(ev, cancelado) {
    if (!inicio || ev.pointerId !== inicio.id) return;
    inicio = null;
    soltarEscuchas();
    if (!fantasma) {
      if (!cancelado) alTocar();
      return;
    }
    fantasma.remove();
    fantasma = null;
    el.classList.remove("hueco-arrastre");
    const disp = disposicionActual();
    if (cancelado || JSON.stringify(disp) === JSON.stringify(dispInicial)) {
      renderGrid();
      return;
    }
    await disponer(disp.principal, disp.paralela);
  }
}

async function seleccionarBloque(id) {
  if (estado.seleccion && estado.seleccion.id === id) {
    estado.seleccion = null;
    render();
    return;
  }
  estado.seleccion = { id };
  estado.parametros = [];
  render();
  try {
    await cargarParametros();
  } catch (e) {
    aviso(e.message, true);
  }
  renderPanel();
}

// -- Panel del bloque (perillas) ------------------------------------------------------------

function renderPanel() {
  const u = estado.tab === "grid" ? unidadSeleccionada() : null;
  if (!u) {
    $panel.hidden = true;
    $panel.innerHTML = "";
    return;
  }
  const esRuteo = u.tipo === "split" || u.tipo === "merge";
  const c = esRuteo
    ? { nombre: "Parallel lines", color: "#E4E4E7", icono: u.tipo === "split" ? ICONO_SPLIT : ICONO_MERGE }
    : cat(u.categoria);
  $panel.hidden = false;
  $panel.innerHTML = "";
  $panel.style.setProperty("--color", c.color);

  const nombre = esRuteo ? (u.tipo === "split" ? "Split" : "Merge") : u.nombre;
  const linea = esRuteo ? "" : ` · ${NOMBRE_TRAMO[u.tramo] || ""}`;
  const info = nuevo("div", "panel-info");
  info.appendChild(nuevo("div", "panel-cabeza",
    `<div class="icono-mini" style="--color:${c.color}">${svg(c.icono)}</div>` +
    `<div class="panel-textos"><div class="panel-nombre">${esc(nombre)}</div>` +
    `<div class="panel-cat">${esc(c.nombre)}${esRuteo ? "" : ` · ${u.estereo ? "Stereo" : "Mono"}`}${esc(linea)}</div></div>`));

  const acciones = nuevo("div", "panel-acciones");
  let onoff = null;
  if (esRuteo) {
    const quitarL = nuevo("button", "pildora peligro", "REMOVE LINE");
    quitarL.addEventListener("click", quitarLinea);
    acciones.append(quitarL);
  } else {
    onoff = nuevo("button", "pildora" + (u.encendido ? " on" : ""), u.encendido ? "ON" : "BYPASS");
    onoff.addEventListener("click", () => fijarEncendido(u, !u.encendido));
    const quitar = nuevo("button", "pildora peligro", "REMOVE");
    quitar.addEventListener("click", () => quitarBloque(u));
    acciones.append(onoff, quitar);
  }
  info.appendChild(acciones);
  const esc_ = escenaActiva();
  if (esc_) {
    // Como Cortex: con una escena activa, lo que se toque queda propio de esa escena.
    const aviso_ = nuevo("div", "panel-escena", `Editing scene <b>${LETRAS[esc_.indice]}</b> · ${esc(esc_.nombre)}`);
    aviso_.style.setProperty("--escena", esc_.color);
    info.appendChild(aviso_);
    const onoffParam = estado.parametros.find((p) => p.nombre === `${u.id}.on_off`);
    if (onoff && onoffParam && onoffParam.de_escena) marcarDeEscena(onoff, onoffParam);
  }
  $panel.appendChild(info);

  const perillas = nuevo("div", "panel-perillas");
  const controles = estado.parametros.filter((p) => !p.nombre.endsWith(".on_off"));
  if (!controles.length) {
    perillas.appendChild(nuevo("div", "vacio", estado.parametros.length ? "No adjustable parameters." : "Loading…"));
  }
  for (const p of controles) {
    let control = null;
    if (p.tipo === "bool") {
      control = crearInterruptor(p, c.color);
    } else if (p.min !== null && p.max !== null) {
      control = crearPerilla({
        valor: Number(p.valor), min: p.min, max: p.max, etiqueta: etiquetaLegible(p.etiqueta), color: c.color,
        // Balance y paneos del SPLIT/MERGE: arco desde el centro; niveles del MERGE en dB.
        bipolar: /^(split\.balance|merge\.pan_)/.test(p.nombre),
        formatear: (v) => (/^merge\.nivel_/.test(p.nombre) ? formatoDb(v)
          : /^(split\.balance|merge\.pan_)/.test(p.nombre) ? formatoBalance(v, p.nombre)
            : formatoValor(v, p.min, p.max)),
        onCambio: (v) => {
          p.valor = v;
          enviarParametro(p.nombre, v);
          if (escenaActiva() && !p.de_escena) { p.de_escena = true; marcarDeEscena(control, p); }
        },
      });
    }
    if (!control) continue;
    if (p.de_escena) marcarDeEscena(control, p);
    perillas.appendChild(control);
  }
  $panel.appendChild(perillas);
}

function formatoBalance(v, nombre) {
  if (Math.abs(v) < 0.01) return nombre === "split.balance" ? "A = B" : "C";
  const pct = Math.round(Math.abs(v) * 100);
  if (nombre === "split.balance") return v < 0 ? `A +${pct}%` : `B +${pct}%`;
  return `${pct}${v < 0 ? "L" : "R"}`;
}

function escenaActiva() {
  const e = estado.linea_estado;
  if (!e || !e.escena_activa) return null;
  const indice = e.escenas.indexOf(e.escena_activa);
  if (indice < 0) return null;
  return { nombre: e.escena_activa, indice, color: COLORES_ESCENA[indice % COLORES_ESCENA.length] };
}

/* Perilla con valor propio de la escena: toma el color de la escena y ofrece ↺ (volver al
 * valor del preset). */
function marcarDeEscena(el, p) {
  const e = escenaActiva();
  if (!e || el.classList.contains("de-escena")) return;
  el.classList.add("de-escena");
  el.style.setProperty("--escena", e.color);
  if (el.tagName === "BUTTON") return;   // la píldora ON/BYPASS: solo color (no se anidan botones)
  el.style.setProperty("--color", e.color);   // crearPerilla lo fija inline: hay que pisarlo igual
  const volver = nuevo("button", "volver-preset", "↺");
  volver.title = "Reset to preset value";
  volver.setAttribute("aria-label", "Reset to preset value");
  volver.addEventListener("pointerdown", (ev) => ev.stopPropagation());
  volver.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    try {
      await api(`${rutaLinea()}/escena/restaurar`, { nombre: p.nombre });
      await cargarParametros();
      await recargarGrid();
      render();
      aviso("Back to preset value");
    } catch (e2) {
      aviso(e2.message, true);
    }
  });
  el.appendChild(volver);
}

/* Cuando el motor no trae nombre legible, la etiqueta es el id crudo ("gain1", "wet_dry"). */
function etiquetaLegible(texto) {
  const t = String(texto);
  if (/^wet_?dry$/i.test(t)) return "Mix";
  return t.replace(/_/g, " ").replace(/^([a-z]+)\d$/i, "$1");
}

function formatoValor(v, min, max) {
  const rango = max - min;
  if (rango <= 2) return v.toFixed(2);
  if (rango <= 40) return v.toFixed(1);
  return String(Math.round(v));
}

function enviarParametro(nombre, valor) {
  diferir(nombre, async () => {
    try {
      await api(`${rutaLinea()}/parametros`, { pares: { [nombre]: valor } });
    } catch (e) {
      aviso(e.message, true);
    }
  });
}

async function fijarEncendido(u, encendido) {
  try {
    await api(`${rutaLinea()}/parametros`, { pares: { [`${u.id}.on_off`]: encendido ? 1 : 0 } });
    await recargarGrid();
    render();
  } catch (e) {
    aviso(e.message, true);
  }
}

async function quitarBloque(u) {
  try {
    estado.grid = await api(`${rutaLinea()}/grid/quitar`, { unidad: u.id, estereo: u.estereo });
    estado.seleccion = null;
    render();
    aviso(`${u.nombre} removed`);
  } catch (e) {
    aviso(e.message, true);
  }
}

function crearInterruptor(p, color) {
  const cont = nuevo("div", "interruptor");
  cont.style.setProperty("--color", color);
  const b = nuevo("button", p.valor ? "on" : "", p.valor ? "ON" : "OFF");
  b.addEventListener("click", () => {
    p.valor = p.valor ? 0 : 1;
    b.className = p.valor ? "on" : "";
    b.textContent = p.valor ? "ON" : "OFF";
    enviarParametro(p.nombre, p.valor);
  });
  cont.append(b, nuevo("div", "perilla-etiqueta", esc(etiquetaLegible(p.etiqueta))));
  return cont;
}

/* Perilla: arco de 270°, se arrastra en vertical (arriba = más). Rueda del mouse también. */
function puntoPolar(angulo) {
  const rad = (angulo - 90) * Math.PI / 180;
  return [30 + 25 * Math.cos(rad), 30 + 25 * Math.sin(rad)];
}
function arco(a0, a1) {
  if (Math.abs(a1 - a0) < 0.5) return "";
  const [x0, y0] = puntoPolar(Math.min(a0, a1));
  const [x1, y1] = puntoPolar(Math.max(a0, a1));
  const grande = Math.abs(a1 - a0) > 180 ? 1 : 0;
  return `M${x0.toFixed(2)} ${y0.toFixed(2)} A25 25 0 ${grande} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

function crearPerilla({ valor, min, max, etiqueta, color, bipolar = false, formatear, onCambio }) {
  const el = nuevo("div", "perilla");
  if (color) el.style.setProperty("--color", color);
  el.innerHTML = svg(
    `<path class="pista" d="${arco(-135, 135)}"/><path class="arco" d=""/>` +
    `<circle class="cuerpo" cx="30" cy="30" r="17"/><line class="aguja" x1="30" y1="30" x2="30" y2="16"/>`,
    "0 0 60 60") +
    `<div class="perilla-valor"></div><div class="perilla-etiqueta">${esc(etiqueta)}</div>`;
  const $arco = el.querySelector(".arco");
  const $aguja = el.querySelector(".aguja");
  const $valor = el.querySelector(".perilla-valor");
  let v = limitar(Number.isFinite(valor) ? valor : min, min, max);

  function pintar() {
    const t = (v - min) / (max - min || 1);
    const ang = -135 + 270 * t;
    const desde = bipolar ? 0 : -135;
    $arco.setAttribute("d", arco(desde, ang));
    $aguja.setAttribute("transform", `rotate(${ang} 30 30)`);
    $valor.textContent = formatear(v);
  }
  pintar();

  let y0 = 0;
  let v0 = 0;
  el.addEventListener("pointerdown", (ev) => {
    el.setPointerCapture(ev.pointerId);
    y0 = ev.clientY;
    v0 = v;
  });
  el.addEventListener("pointermove", (ev) => {
    if (!el.hasPointerCapture(ev.pointerId)) return;
    v = limitar(v0 + (y0 - ev.clientY) / 170 * (max - min), min, max);
    pintar();
    onCambio(v);
  });
  el.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    v = limitar(v - Math.sign(ev.deltaY) * (max - min) / 100, min, max);
    pintar();
    onCambio(v);
  }, { passive: false });
  return el;
}

// -- Selector "+" (categorías -> modelos) ------------------------------------------------------

const NOMBRE_TRAMO = { pre: "Main line", a: "Line A", b: "Line B", post: "After the merge" };

/* "+": catálogo para un tramo. Mono y estéreo van juntos (el motor los ubica); lo único que se
 * filtra es la regla del motor: con líneas paralelas, antes del SPLIT solo efectos mono. */
async function abrirSelector(tramo) {
  let catalogo;
  try {
    catalogo = await api(`${rutaLinea()}/plugins?tramo=${encodeURIComponent(tramo)}`);
  } catch (e) {
    aviso(e.message, true);
    return;
  }
  const soloMono = tramo === "pre" && estado.grid && estado.grid.split;
  const categorias = catalogo.categorias
    .map((c) => ({ ...c, plugins: c.plugins.filter((p) => !(soloMono && p.estereo)) }))
    .filter((c) => c.plugins.length);
  mostrarCapa(true);
  $selector.hidden = false;
  mostrarCategorias(categorias, tramo);
}

function cabeceraSelector(titulo, alVolver) {
  const cab = nuevo("div", "selector-cabeza");
  if (alVolver) {
    const volver = nuevo("button", "flecha", svg('<path d="M15 5l-7 7 7 7"/>'));
    volver.addEventListener("click", alVolver);
    cab.appendChild(volver);
  }
  cab.appendChild(nuevo("div", "titulo", esc(titulo)));
  const cerrar = nuevo("button", "flecha", svg('<path d="M6 6l12 12M18 6 6 18"/>'));
  cerrar.addEventListener("click", cerrarCapas);
  cab.appendChild(cerrar);
  return cab;
}

function mostrarCategorias(categorias, tramo) {
  $selector.innerHTML = "";
  $selector.appendChild(cabeceraSelector(`Add block · ${NOMBRE_TRAMO[tramo] || tramo}`));
  const cuerpo = nuevo("div", "selector-cuerpo");
  const leyenda = nuevo("div", "leyenda");
  for (const c of categorias) {
    const info = cat(c.id);
    const b = nuevo("button", "item-leyenda",
      `<div class="icono-mini" style="--color:${info.color}">${svg(info.icono)}</div>` +
      `<div>${esc(info.nombre)}<small>${c.plugins.length} model${c.plugins.length === 1 ? "" : "s"}</small></div>`);
    b.addEventListener("click", () => mostrarModelos(c, categorias, tramo));
    leyenda.appendChild(b);
  }
  cuerpo.appendChild(leyenda);
  $selector.appendChild(cuerpo);
}

function mostrarModelos(c, categorias, tramo) {
  const info = cat(c.id);
  $selector.innerHTML = "";
  $selector.appendChild(cabeceraSelector(info.nombre, () => mostrarCategorias(categorias, tramo)));
  const cuerpo = nuevo("div", "selector-cuerpo");
  const lista = nuevo("div", "lista-modelos");
  for (const p of c.plugins) {
    const b = nuevo("button", "item-modelo",
      `<div class="icono-mini" style="--color:${info.color}">${svg(info.icono)}</div>` +
      `<div>${esc(p.nombre)}<small>${p.en_cadena ? "Already in this line" : (p.estereo ? "Stereo" : "Mono")}</small></div>`);
    b.disabled = p.en_cadena;
    b.addEventListener("click", () => insertarBloque(p, tramo));
    lista.appendChild(b);
  }
  cuerpo.appendChild(lista);
  $selector.appendChild(cuerpo);
}

async function insertarBloque(p, tramo) {
  try {
    estado.grid = await api(`${rutaLinea()}/grid/insertar`, { unidad: p.id, tramo });
    cerrarCapas();
    aviso(`${p.nombre} added`);
    await seleccionarBloque(tramo === "pre" ? p.id : `${tramo}/${p.id}`);
  } catch (e) {
    aviso(e.message, true);
  }
}

// -- Capas: velo / popover ------------------------------------------------------------------

function mostrarCapa(visible) {
  $velo.hidden = !visible;
}
function cerrarCapas() {
  $velo.hidden = true;
  $popover.hidden = true;
  $selector.hidden = true;
  $selector.innerHTML = "";
  if (!$modal.hidden) {
    $modal.hidden = true;
    $modal.innerHTML = "";
    const alCerrar = modalAlCerrar;
    modalAlCerrar = null;
    if (alCerrar) alCerrar();
  }
}

// -- Ventanas flotantes (Tuner / Tempo) ---------------------------------------------------------

const $modal = $("modal");
let modalAlCerrar = null;

function abrirModal(titulo, extrasCabeza, cuerpo, alCerrar) {
  cerrarCapas();
  $modal.innerHTML = "";
  const cab = nuevo("div", "modal-cabeza");
  cab.appendChild(nuevo("div", "modal-titulo", esc(titulo)));
  const extras = nuevo("div", "modal-extras");
  for (const x of extrasCabeza) extras.appendChild(x);
  cab.appendChild(extras);
  const cerrar = nuevo("button", "modal-cerrar", svg('<path d="M6 6l12 12M18 6 6 18"/>'));
  cerrar.setAttribute("aria-label", "Close");
  cerrar.addEventListener("click", cerrarCapas);
  cab.appendChild(cerrar);
  $modal.append(cab, cuerpo);
  modalAlCerrar = alCerrar || null;
  mostrarCapa(true);
  $modal.hidden = false;
}

// Afinador: el motor de la línea analiza el tono; la app lo consulta ~10 veces por segundo y
// calcula nota y cents con su referencia (La4, 440 Hz por defecto, ajustable).
const NOTAS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const NOTAS_DOBLE = ["C", "C#/Db", "D", "D#/Eb", "E", "F", "F#/Gb", "G", "G#/Ab", "A", "A#/Bb", "B"];
const ICONO_PARLANTE = '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4.5 4.5 0 0 1 0 6M18 6.5a8 8 0 0 1 0 11"/>';
const ICONO_MUDO = '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M16 9.5l5 5M21 9.5l-5 5"/>';

function leerPreferencia(clave, porDefecto) {
  try {
    const v = localStorage.getItem(clave);
    return v === null ? porDefecto : JSON.parse(v);
  } catch (e) {
    return porDefecto;
  }
}
function guardarPreferencia(clave, valor) {
  try { localStorage.setItem(clave, JSON.stringify(valor)); } catch (e) { /* sin storage: no pasa nada */ }
}

function abrirAfinador() {
  let linea = estado.linea;
  let referencia = leerPreferencia("afinador.referencia", 440);
  let mudo = false;
  let cents = 0;
  let activo = true;
  let tPoll = null;

  const selector = nuevo("select", "modal-select");
  for (const l of estado.lineas) {
    const o = nuevo("option", "", esc(etiquetaLinea(l)));
    o.value = l;
    o.selected = l === linea;
    selector.appendChild(o);
  }
  const btnMudo = nuevo("button", "modal-icono", svg(ICONO_PARLANTE));
  btnMudo.title = "Mute output while tuning";

  const cuerpo = nuevo("div", "afinador");
  cuerpo.innerHTML = `
    <div class="af-escala"><span>-50</span><span class="af-flecha izq">${svg('<path d="M9 5l7 7-7 7"/>')}</span>
      <span class="af-cents">–</span><span class="af-flecha der">${svg('<path d="M15 5l-7 7 7 7"/>')}</span><span>+50</span></div>
    <div class="af-pista"><div class="af-marca"></div><div class="af-punto"></div></div>
    <div class="af-notas"><span class="af-vecina izq">–</span><span class="af-nota">–</span><span class="af-vecina der">–</span></div>
    <div class="af-pie"><span class="af-hz">No signal</span>
      <div class="af-ref"><span>A4</span><button class="menos" aria-label="Lower reference">−</button>
      <span class="af-ref-valor"></span><button class="mas" aria-label="Raise reference">+</button></div></div>`;
  const q = (s) => cuerpo.querySelector(s);

  const enviar = (extra = {}) => api(`/lineas/${encodeURIComponent(linea)}/afinador`,
    { activo: true, silenciar: mudo, referencia, ...extra }).catch((e) => aviso(e.message, true));

  function pintarRef() { q(".af-ref-valor").textContent = `${referencia.toFixed(1)} Hz`; }
  function cambiarRef(paso) {
    referencia = Math.round(limitar(referencia + paso, 400, 480) * 10) / 10;
    guardarPreferencia("afinador.referencia", referencia);
    pintarRef();
    diferir("afinador.ref", () => enviar(), 200);
  }
  q(".menos").addEventListener("click", () => cambiarRef(-1));
  q(".mas").addEventListener("click", () => cambiarRef(1));
  btnMudo.addEventListener("click", () => {
    mudo = !mudo;
    btnMudo.innerHTML = svg(mudo ? ICONO_MUDO : ICONO_PARLANTE);
    btnMudo.classList.toggle("activo", mudo);
    enviar();
  });
  selector.addEventListener("change", () => {
    api(`/lineas/${encodeURIComponent(linea)}/afinador`, { activo: false, silenciar: false }).catch(() => {});
    linea = selector.value;
    enviar();
  });

  function pintar(frecuencia) {
    const punto = q(".af-punto");
    if (!(frecuencia > 20 && frecuencia < 5000)) {
      cuerpo.classList.remove("afinado", "cerca");
      cuerpo.classList.add("sin-senal");
      q(".af-nota").textContent = "–";
      q(".af-vecina.izq").textContent = q(".af-vecina.der").textContent = "";
      q(".af-cents").textContent = "–";
      q(".af-hz").textContent = "No signal";
      punto.style.left = "50%";
      return;
    }
    cuerpo.classList.remove("sin-senal");
    const n = 12 * Math.log2(frecuencia / referencia) + 69;
    const cercana = Math.round(n);
    const c = (n - cercana) * 100;
    cents = Math.abs(c - cents) > 30 ? c : cents * 0.6 + c * 0.4;   // suaviza sin arrastrar saltos
    const idx = ((cercana % 12) + 12) % 12;
    q(".af-nota").innerHTML = `${NOTAS[idx]}<sub>${Math.floor(cercana / 12) - 1}</sub>`;
    q(".af-vecina.izq").textContent = NOTAS_DOBLE[(idx + 11) % 12];
    q(".af-vecina.der").textContent = NOTAS_DOBLE[(idx + 1) % 12];
    q(".af-cents").textContent = `${cents >= 0 ? "+" : ""}${cents.toFixed(1)}`;
    q(".af-hz").textContent = `${frecuencia.toFixed(1)} Hz`;
    punto.style.left = `${50 + limitar(cents, -50, 50)}%`;
    cuerpo.classList.toggle("afinado", Math.abs(cents) <= 3);
    cuerpo.classList.toggle("cerca", Math.abs(cents) > 3 && Math.abs(cents) <= 15);
    q(".af-flecha.izq").classList.toggle("on", cents < -3);   // bajo: subir
    q(".af-flecha.der").classList.toggle("on", cents > 3);    // alto: bajar
  }

  async function sondear() {
    if (!activo) return;
    try {
      const r = await api(`/lineas/${encodeURIComponent(linea)}/afinador`);
      if (activo) pintar(r.frecuencia);
    } catch (e) {
      if (activo) q(".af-hz").textContent = "Engine offline";
    }
    if (activo) tPoll = setTimeout(sondear, 100);
  }

  pintarRef();
  pintar(0);
  abrirModal("Tuner", [selector, btnMudo], cuerpo, () => {
    activo = false;
    clearTimeout(tPoll);
    // sendBeacon: llega aunque la página se esté cerrando -- nunca dejar la salida muda.
    const url = `/lineas/${encodeURIComponent(linea)}/afinador`;
    const datos = JSON.stringify({ activo: false, silenciar: false });
    const enviado = navigator.sendBeacon && navigator.sendBeacon(url, new Blob([datos], { type: "application/json" }));
    if (!enviado) api(url, { activo: false, silenciar: false }).catch(() => {});
  });
  enviar().then(sondear);
}

// Tempo: TAP (promedio de los últimos 4 intervalos, se reinicia tras 2 s sin tocar), +/- y
// slider. Mueve los delays del GRID. "Preset" se guarda con 💾; "Global" es para toda la banda.
function abrirTempo() {
  let bpm = Math.round((estado.linea_estado && estado.linea_estado.tempo_bpm) || 120);
  let alcance = leerPreferencia("tempo.alcance", "preset");
  let taps = [];

  const cuerpo = nuevo("div", "tempo");
  cuerpo.innerHTML = `
    <div class="segmentado tempo-alcance"><button data-a="global">Global</button><button data-a="preset">Preset</button></div>
    <p class="tempo-ayuda"></p>
    <div class="tempo-fila">
      <button class="tempo-tap">TAP</button>
      <div class="tempo-bpm"><span class="tempo-numero"></span><span class="tempo-led"></span></div>
      <div class="tempo-pasos"><button class="menos" aria-label="Slower">−</button><button class="mas" aria-label="Faster">+</button></div>
    </div>
    <div class="tempo-slider"><input type="range" min="40" max="250" step="1">
      <div class="tempo-marcas"><span style="left:9.5%">60</span><span style="left:28.6%">100</span><span style="left:38.1%">120</span><span style="left:66.7%">180</span></div></div>
    <p class="tempo-nota">Delays in the grid follow this tempo.</p>`;
  const q = (s) => cuerpo.querySelector(s);
  const slider = q("input");

  function pintar() {
    q(".tempo-numero").textContent = String(bpm);
    slider.value = String(limitar(bpm, 40, 250));
    q(".tempo-led").style.animationDuration = `${60 / bpm}s`;
    for (const b of cuerpo.querySelectorAll(".tempo-alcance button")) b.classList.toggle("activo", b.dataset.a === alcance);
    q(".tempo-ayuda").textContent = alcance === "preset"
      ? "The tempo is saved when the preset is saved. Each preset can have its own tempo."
      : "Sets the same tempo on every instrument (GTR 1, GTR 2, BASS, VOX).";
  }
  function fijar(nuevoBpm, inmediato = false) {
    bpm = Math.round(limitar(nuevoBpm, 40, 250));
    pintar();
    diferir("tempo", async () => {
      try {
        const r = await api(`${rutaLinea()}/tempo`, { bpm, alcance });
        estado.linea_estado = r;
        if (r.saltadas && r.saltadas.length) aviso(`Offline, not changed: ${r.saltadas.map(etiquetaLinea).join(", ")}`, true);
      } catch (e) {
        aviso(e.message, true);
      }
    }, inmediato ? 0 : 150);
  }

  for (const b of cuerpo.querySelectorAll(".tempo-alcance button")) {
    b.addEventListener("click", () => {
      alcance = b.dataset.a;
      guardarPreferencia("tempo.alcance", alcance);
      pintar();
      fijar(bpm, true);
    });
  }
  q(".menos").addEventListener("click", () => fijar(bpm - 1));
  q(".mas").addEventListener("click", () => fijar(bpm + 1));
  slider.addEventListener("input", () => fijar(Number(slider.value)));
  q(".tempo-tap").addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    const ahora = performance.now() / 1000;
    if (taps.length && ahora - taps[taps.length - 1] > 2) taps = [];
    taps.push(ahora);
    taps = taps.slice(-5);
    const boton = q(".tempo-tap");
    boton.classList.remove("pulso");
    void boton.offsetWidth;
    boton.classList.add("pulso");
    if (taps.length < 2) return;
    const intervalos = taps.slice(1).map((t, i) => t - taps[i]);
    const promedio = intervalos.reduce((a, b) => a + b, 0) / intervalos.length;
    fijar(60 / promedio, true);
  });

  pintar();
  abrirModal("Tempo", [], cuerpo, null);
}
$velo.addEventListener("click", cerrarCapas);

function abrirPopover(ancla, items, pie) {
  $popover.innerHTML = "";
  for (const it of items) {
    const b = nuevo("button", "", esc(it.texto) + (it.marca ? '<span class="marca">●</span>' : ""));
    b.addEventListener("click", () => { cerrarCapas(); it.accion(); });
    $popover.appendChild(b);
  }
  if (pie) $popover.appendChild(nuevo("div", "estado-linea", esc(pie)));
  ubicarPopover(ancla);
}

/* Mantener apretado un bloque (o clic derecho): asignarlo a un pie A-H de la pedalera. Cada
 * letra muestra qué tiene hoy; elegir una ocupada la reemplaza, como en Cortex. */
function menuStomp(ancla, u) {
  const ocupados = {};
  for (const s of (estado.linea_estado ? estado.linea_estado.stomps : [])) ocupados[s.pie] = s;
  $popover.innerHTML = "";
  $popover.appendChild(nuevo("div", "pop-titulo", `Assign <b>${esc(u.nombre)}</b> to stomp`));
  const grilla = nuevo("div", "pop-letras");
  LETRAS.forEach((letra, pie) => {
    const s = ocupados[pie];
    const propio = s && s.unidad === u.id;
    const b = nuevo("button", "pop-letra" + (propio ? " actual" : "") + (s && !propio ? " ocupada" : ""),
      `<b>${letra}</b><small>${s ? esc(propio ? "Current" : s.etiqueta) : "Free"}</small>`);
    b.addEventListener("click", () => { cerrarCapas(); asignarStomp(u, pie); });
    grilla.appendChild(b);
  });
  $popover.appendChild(grilla);
  if (u.pie !== null && u.pie !== undefined) {
    const quitar = nuevo("button", "pop-quitar", "Remove from stomp");
    quitar.addEventListener("click", () => { cerrarCapas(); asignarStomp(u, null); });
    $popover.appendChild(quitar);
  }
  ubicarPopover(ancla);
}

async function asignarStomp(u, pie) {
  try {
    estado.linea_estado = await api(`${rutaLinea()}/stomps`, { unidad: u.id, pie });
    await recargarGrid();
    render();
    aviso(pie === null ? `${u.nombre} removed from stomps` : `${u.nombre} → stomp ${LETRAS[pie]}`);
  } catch (e) {
    aviso(e.message, true);
  }
}

function ubicarPopover(ancla) {
  mostrarCapa(true);
  $popover.hidden = false;
  const r = ancla.getBoundingClientRect();
  const w = $popover.offsetWidth;
  const h = $popover.offsetHeight;
  let x = r.left;
  let y = r.bottom + 6;
  if (x + w > innerWidth - 8) x = innerWidth - w - 8;
  if (y + h > innerHeight - 8) y = Math.max(8, r.top - h - 6);
  $popover.style.left = `${Math.max(8, x)}px`;
  $popover.style.top = `${y}px`;
}

function menuInstrumento(ancla) {
  abrirPopover(ancla, estado.lineas.map((l) => ({
    texto: etiquetaLinea(l),
    marca: l === estado.linea,
    accion: () => { if (l !== estado.linea) cambiarLinea(l); },
  })));
}

function textoMotor() {
  const m = estado.motor;
  if (!m) return "Engine offline";
  const v = Array.isArray(m.version) ? m.version[2] : m.version;
  return `Arquitec DSP ${v} · CPU ${Number(m.carga_cpu).toFixed(1)}%`;
}

// -- PRESETS ---------------------------------------------------------------------------------

function renderPresets() {
  $contenido.innerHTML = "";
  const e = estado.linea_estado;
  if (!e) { $contenido.appendChild(nuevo("div", "mensaje-centro", "Loading…")); return; }
  const pantalla = nuevo("div", "pantalla-tiles");

  const barra = nuevo("div", "barra-sub");
  const ant = nuevo("button", "flecha", svg('<path d="M15 5l-7 7 7 7"/>'));
  const sig = nuevo("button", "flecha", svg('<path d="M9 5l7 7-7 7"/>'));
  ant.disabled = sig.disabled = e.total_bancos < 2;
  ant.addEventListener("click", () => accion("banco_anterior"));
  sig.addEventListener("click", () => accion("banco_siguiente"));
  barra.append(ant, nuevo("div", "titulo", `Bank ${e.banco_visible + 1}<small>${esc(e.banco_visible_nombre)}</small>`), sig);
  pantalla.appendChild(barra);

  const tiles = nuevo("div", "tiles");
  for (let i = 0; i < 8; i++) {
    const nombre = e.presets_banco_visible[i];
    const codigo = `${e.banco_visible + 1}${LETRAS[i]}`;
    const activo = e.banco_visible === e.banco_activo && i === e.posicion_activa;
    const t = nuevo("button", "tile-preset" + (activo ? " activo" : "") + (nombre ? "" : " vacio"),
      `<span class="codigo">${codigo}</span><span class="nombre">${nombre ? esc(nombre) : "—"}</span>`);
    if (nombre) t.addEventListener("click", () => accion("preset_en_banco", i));
    tiles.appendChild(t);
  }
  pantalla.appendChild(tiles);
  $contenido.appendChild(pantalla);
}

// -- GIG -------------------------------------------------------------------------------------

function switchesStomp() {
  const e = estado.linea_estado;
  const bloques = itemsGrid().filter((u) => u.tipo === "bloque");
  const enGrid = {};
  for (const u of bloques) enGrid[u.id] = u;
  if (e.stomps.length) {
    // Cada stomp en SU letra (pie de la pedalera); las letras libres quedan como hueco.
    const slots = new Array(8).fill(null);
    for (const s of e.stomps) {
      if (s.pie < 0 || s.pie > 7) continue;
      slots[s.pie] = {
        nombre: enGrid[s.unidad] ? enGrid[s.unidad].nombre : s.etiqueta,
        categoria: s.categoria,
        on: s.activo,
        fueraDeGrid: s.en_cadena === false,
        pisar: () => accion("toggle_stomp", s.pie),
      };
    }
    while (slots.length && slots[slots.length - 1] === null) slots.pop();
    return slots;
  }
  return bloques.slice(0, 8).map((u) => ({
    nombre: u.nombre,
    categoria: u.categoria,
    on: u.encendido,
    fueraDeGrid: false,
    pisar: () => fijarEncendido(u, !u.encendido),
  }));
}

function renderGig() {
  $contenido.innerHTML = "";
  const e = estado.linea_estado;
  if (!e) { $contenido.appendChild(nuevo("div", "mensaje-centro", "Loading…")); return; }
  const pantalla = nuevo("div", "pantalla-tiles");

  const barra = nuevo("div", "barra-sub");
  const seg = nuevo("div", "segmentado");
  for (const [modo, texto] of [["stomp", "STOMP"], ["scene", "SCENE"]]) {
    const b = nuevo("button", estado.gigModo === modo ? "activo" : "", texto);
    b.addEventListener("click", () => { estado.gigModo = modo; render(); });
    seg.appendChild(b);
  }
  barra.appendChild(seg);
  barra.appendChild(nuevo("div", "indicacion",
    estado.gigModo === "stomp" ? `${esc(etiquetaLinea(estado.linea))} · tap to bypass`
      : `${esc(etiquetaLinea(estado.linea))} · ${e.escena_activa ? esc(e.escena_activa) : "no scene"}`));
  pantalla.appendChild(barra);

  const tiles = nuevo("div", "tiles");
  if (estado.gigModo === "stomp") {
    const sw = switchesStomp();
    if (!sw.length) tiles.appendChild(nuevo("div", "mensaje-centro", "No blocks in the grid yet."));
    sw.forEach((s, i) => {
      if (!s) {
        tiles.appendChild(nuevo("div", "tile libre", `<div class="tile-letra">${LETRAS[i]}</div>`));
        return;
      }
      const c = cat(s.categoria);
      const t = nuevo("button", "tile " + (s.on && !s.fueraDeGrid ? "on" : "off"),
        `<div class="tile-icono">${svg(c.icono)}</div><div class="tile-letra">${LETRAS[i]}</div>` +
        `<div class="tile-nombre">${esc(s.nombre)}${s.fueraDeGrid ? '<span class="tile-nota">Not in grid</span>' : ""}</div>`);
      t.style.setProperty("--color", c.color);
      t.addEventListener("click", () => {
        if (s.fueraDeGrid) { aviso("Add this block in GRID first", true); return; }
        s.pisar();
      });
      tiles.appendChild(t);
    });
  } else {
    e.escenas.forEach((nombre, i) => {
      const color = COLORES_ESCENA[i % COLORES_ESCENA.length];
      const t = nuevo("button", "tile " + (nombre === e.escena_activa ? "on" : "off"),
        `<div class="tile-icono">${svg(ICONO_ESCENA)}</div><div class="tile-letra">${LETRAS[i]}</div>` +
        `<div class="tile-nombre">${esc(nombre)}</div>`);
      t.style.setProperty("--color", color);
      t.addEventListener("click", () => accion("escena", i));
      tiles.appendChild(t);
    });
    if (e.escenas.length < 8) {
      const mas = nuevo("button", "tile agregar", `<div>${svg(ICONO_MAS)}<span>New scene ${LETRAS[e.escenas.length]}</span></div>`);
      mas.addEventListener("click", nuevaEscena);
      tiles.appendChild(mas);
    }
  }
  pantalla.appendChild(tiles);
  $contenido.appendChild(pantalla);
}

async function nuevaEscena() {
  try {
    estado.linea_estado = await api(`${rutaLinea()}/escenas`, {});
    render();
    const e = estado.linea_estado;
    aviso(`Scene ${LETRAS[e.escenas.length - 1]} created from current sound`);
  } catch (e) {
    aviso(e.message, true);
  }
}

// -- SENDS -------------------------------------------------------------------------------------

async function renderSends() {
  $contenido.innerHTML = "";
  if (!estado.matriz) {
    $contenido.appendChild(nuevo("div", "mensaje-centro", "Loading…"));
    try {
      estado.matriz = await api("/mezclador/matriz");
      if (!estado.bus || !estado.matriz.buses.includes(estado.bus)) estado.bus = estado.matriz.buses[0];
    } catch (e) {
      $contenido.innerHTML = "";
      $contenido.appendChild(nuevo("div", "mensaje-centro error", `Sends unavailable: ${esc(e.message)}`));
      return;
    }
    if (estado.tab !== "sends") return;
    $contenido.innerHTML = "";
  }
  const m = estado.matriz;
  const pantalla = nuevo("div", "pantalla-tiles");

  const barra = nuevo("div", "barra-sub");
  const seg = nuevo("div", "segmentado");
  for (const bus of m.buses) {
    const b = nuevo("button", bus === estado.bus ? "activo" : "", esc(etiquetaBus(bus)));
    b.addEventListener("click", () => { estado.bus = bus; render(); });
    seg.appendChild(b);
  }
  barra.appendChild(seg);
  barra.appendChild(nuevo("div", "indicacion", m.modo_bus[estado.bus] === "estereo" ? "STEREO OUT" : "MONO OUT"));
  pantalla.appendChild(barra);

  const consola = nuevo("div", "consola");
  for (const fuente of m.fuentes) {
    const celda = m.matriz[fuente][estado.bus];
    const canal = nuevo("div", "canal");
    canal.appendChild(nuevo("div", "canal-nombre", esc(etiquetaLinea(fuente))));
    canal.appendChild(crearPerilla({
      valor: celda.paneo, min: -1, max: 1, etiqueta: "Pan", color: "#60A5FA", bipolar: true,
      formatear: (v) => (Math.abs(v) < 0.01 ? "C" : `${Math.round(Math.abs(v) * 100)}${v < 0 ? "L" : "R"}`),
      onCambio: (v) => { celda.paneo = v; enviarMezcla("paneo", fuente, v); },
    }));
    const db = nuevo("div", "canal-db", formatoDb(celda.ganancia));
    canal.appendChild(crearFader(celda.ganancia, (g) => {
      celda.ganancia = g;
      db.textContent = formatoDb(g);
      enviarMezcla("ganancia", fuente, g);
    }));
    canal.appendChild(db);
    consola.appendChild(canal);
  }
  pantalla.appendChild(consola);
  $contenido.appendChild(pantalla);
}

function formatoDb(g) {
  if (g <= 0.0005) return "-∞ dB";
  const db = 20 * Math.log10(g);
  return `${db > 0.05 ? "+" : ""}${db.toFixed(1)} dB`;
}

function enviarMezcla(campo, fuente, valor) {
  const bus = estado.bus;
  diferir(`mezcla|${campo}|${fuente}|${bus}`, async () => {
    try {
      await api(campo === "ganancia" ? "/mezclador/ganancia" : "/mezclador/paneo", { fuente, bus, valor });
    } catch (e) {
      aviso(e.message, true);
    }
  });
}

/* Fader vertical, ganancia lineal 0..2 (unidad = mitad del recorrido, marcada con una línea). */
function crearFader(valor, onCambio) {
  const el = nuevo("div", "fader",
    '<div class="fader-pista"></div><div class="fader-nivel"></div><div class="fader-cero"></div><div class="fader-perilla"></div>');
  const $nivel = el.querySelector(".fader-nivel");
  const $perilla = el.querySelector(".fader-perilla");
  el.querySelector(".fader-cero").style.bottom = "calc(6px + (100% - 12px) * 0.5)";
  let g = limitar(valor, 0, 2);
  function pintar() {
    const pos = g / 2;
    $perilla.style.bottom = `calc(6px + (100% - 12px) * ${pos})`;
    $nivel.style.height = `calc((100% - 12px) * ${pos})`;
  }
  pintar();
  function desdeEvento(ev) {
    const r = el.getBoundingClientRect();
    const pos = 1 - (ev.clientY - r.top - 6) / (r.height - 12);
    g = limitar(pos, 0, 1) * 2;
    if (Math.abs(g - 1) < 0.03) g = 1;    // imán en 0 dB
    pintar();
    onCambio(g);
  }
  el.addEventListener("pointerdown", (ev) => { el.setPointerCapture(ev.pointerId); desdeEvento(ev); });
  el.addEventListener("pointermove", (ev) => { if (el.hasPointerCapture(ev.pointerId)) desdeEvento(ev); });
  return el;
}

// -- Cabecera y tabs: eventos -------------------------------------------------------------------

$("btn-prev").addEventListener("click", () => accion("preset_anterior"));
$("btn-next").addEventListener("click", () => accion("preset_siguiente"));
$("btn-guardar").addEventListener("click", async () => {
  try {
    estado.linea_estado = await api(`${rutaLinea()}/guardar`, {});
    render();
    aviso(`Saved: ${estado.linea_estado.preset}`);
  } catch (e) {
    aviso(e.message, true);
  }
});
$("btn-menu").addEventListener("click", (ev) => {
  abrirPopover(ev.currentTarget, [
    { texto: "Tuner", accion: abrirAfinador },
    { texto: `Tempo · ${Math.round((estado.linea_estado && estado.linea_estado.tempo_bpm) || 120)} BPM`, accion: abrirTempo },
  ], textoMotor());
});
for (const b of document.querySelectorAll(".tab")) {
  b.addEventListener("click", () => {
    estado.tab = b.dataset.tab;
    if (estado.tab !== "grid") estado.seleccion = null;
    render();
  });
}
// Cerrar la pestaña/app con el afinador abierto: apagarlo y des-silenciar igual.
addEventListener("pagehide", () => { if (!$modal.hidden) cerrarCapas(); });
addEventListener("resize", () => diferir("resize", () => { if (estado.tab === "grid") renderGrid(); }, 120));

// -- Estado del motor (punto del menú) ---------------------------------------------------------

async function actualizarMotor() {
  const punto = $("punto-estado");
  try {
    estado.motor = await api("/estado");
    punto.className = "punto-estado ok";
  } catch (e) {
    estado.motor = null;
    punto.className = "punto-estado error";
  }
}

// -- Sincronía al instante con las demás pantallas (OS, tablet, celular) ----------------------

let dedoAbajo = false;
let syncPendiente = false;
document.addEventListener("pointerdown", () => { dedoAbajo = true; }, true);
const soltarDedo = () => {
  dedoAbajo = false;
  if (syncPendiente) { syncPendiente = false; diferir("sync", aplicarSync, 250); }
};
document.addEventListener("pointerup", soltarDedo, true);
document.addEventListener("pointercancel", soltarDedo, true);

const cambiosSync = { linea: false, parametros: false, mezcla: false };

async function aplicarSync() {
  // Si el usuario está en medio de un gesto (perilla, fader, arrastre), esperar a que suelte:
  // re-dibujar bajo el dedo le arrancaría el control.
  if (dedoAbajo) { syncPendiente = true; return; }
  const c = { ...cambiosSync };
  cambiosSync.linea = cambiosSync.parametros = cambiosSync.mezcla = false;
  try {
    if (c.mezcla) {
      estado.matriz = await api("/mezclador/matriz");
    }
    if (c.linea) {
      await cargarLinea();
      if (estado.seleccion) await cargarParametros();
    } else if (c.parametros && estado.seleccion) {
      await cargarParametros();
    }
    render();
  } catch (e) {
    /* el motor puede estar reiniciando: el próximo aviso o el reintento lo levantan */
  }
}

function conectarSync() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/sync`);
  ws.onmessage = (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (m.origen === ID_CLIENTE) return;
    if (m.tipo === "mezcla") cambiosSync.mezcla = true;
    else if (m.linea === "*" || m.linea === estado.linea) {
      if (m.tipo === "parametros") cambiosSync.parametros = true;
      else cambiosSync.linea = true;
    } else {
      return;
    }
    diferir("sync", aplicarSync, 150);
  };
  ws.onclose = () => setTimeout(conectarSync, 2000);
}

async function iniciar() {
  try {
    estado.lineas = await api("/lineas");
  } catch (e) {
    $contenido.innerHTML = `<div class="mensaje-centro error">Can't reach the system: ${esc(e.message)}</div>`;
    return;
  }
  estado.linea = estado.lineas[0];
  await cambiarLinea(estado.linea);
  actualizarMotor();
  setInterval(actualizarMotor, 5000);
  conectarSync();
}

iniciar();
