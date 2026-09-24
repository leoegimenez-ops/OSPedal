/* PWA de control remoto -- PedalSistema.
 *
 * Sin build step, sin framework: fetch() directo contra server/api.py, servido desde el mismo
 * origen (montado en /app dentro de la misma app de FastAPI), así que las rutas relativas
 * ("/estado", "/mezclador/matriz") funcionan igual en local que atrás de un túnel público.
 *
 * Pantalla única: elegís tu bus (tab de abajo) y ajustás ganancia/paneo de cada fuente con
 * sliders. Cada cambio se manda con un debounce corto para no inundar la API mientras arrastrás.
 */

const $app = document.getElementById("app");
const $tabs = document.getElementById("tabs");
const $dot = document.getElementById("dot-conexion");
const $txtEstado = document.getElementById("txt-estado");
const $txtCpu = document.getElementById("txt-cpu");

let matriz = null;      // ultima respuesta de GET /mezclador/matriz
let busActivo = null;
const temporizadores = {};   // debounce por control: clave "fuente|bus|campo" -> setTimeout id

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
  renderTabs();
  renderBus();
}

function renderTabs() {
  $tabs.innerHTML = "";
  $tabs.hidden = false;
  for (const bus of matriz.buses) {
    const boton = document.createElement("button");
    boton.className = "tab" + (bus === busActivo ? " activo" : "");
    boton.textContent = bus;
    boton.addEventListener("click", () => {
      busActivo = bus;
      renderTabs();
      renderBus();
    });
    $tabs.appendChild(boton);
  }
}

function renderBus() {
  const modo = matriz.modo_bus[busActivo];
  $app.innerHTML = "";

  const titulo = document.createElement("div");
  titulo.className = "bus-titulo";
  titulo.textContent = busActivo;
  $app.appendChild(titulo);

  const subtitulo = document.createElement("div");
  subtitulo.className = "bus-subtitulo";
  subtitulo.textContent = modo === "estereo" ? "Salida estéreo" : "Salida mono";
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
    onCambio: (v) => enviarCambio("ganancia", fuente, busActivo, v),
  }));

  tarjeta.appendChild(controlSlider({
    etiqueta: "PAN",
    valorInicial: celda.paneo,
    min: -1, max: 1, step: 0.01,
    formatear: formatearPaneo,
    clase: "paneo",
    onCambio: (v) => enviarCambio("paneo", fuente, busActivo, v),
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

function enviarCambio(campo, fuente, bus, valor) {
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
    marcarEstado(true, `Guitarix ${Array.isArray(datos.version) ? datos.version[2] : datos.version}`);
    $txtCpu.textContent = `CPU ${Number(datos.carga_cpu).toFixed(1)}%`;
  } catch (e) {
    marcarEstado(false, "Sin conexión");
    $txtCpu.textContent = "";
  }
}

async function iniciar() {
  $dot.className = "dot espera";
  try {
    await cargarMatriz();
  } catch (e) {
    $app.innerHTML = `<div class="error-carga">No se pudo cargar el mezclador: ${e.message}</div>`;
  }
  actualizarEstadoMotor();
  setInterval(actualizarEstadoMotor, 5000);
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

iniciar();
