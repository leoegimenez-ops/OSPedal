/* Service worker minimo: solo cachea el shell estatico (para que abra rapido / offline como
 * pantalla, aunque sin datos reales sin conexion). Las llamadas a la API (/estado, /mezclador/*)
 * nunca se cachean -- siempre tienen que ir a la red, es control en vivo. */

const CACHE = "pedalsistema-shell-v1";
const SHELL = ["./", "index.html", "app.js", "style.css", "manifest.json", "icon.svg"];

self.addEventListener("install", (evento) => {
  evento.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches.keys().then((claves) =>
      Promise.all(claves.filter((c) => c !== CACHE).map((c) => caches.delete(c)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (evento) => {
  const url = new URL(evento.request.url);
  const esShell = SHELL.some((ruta) => url.pathname.endsWith(ruta.replace("./", "")));
  if (!esShell) return;   // todo lo demas (la API) pasa directo a la red, sin intervenir

  evento.respondWith(
    caches.match(evento.request).then((cacheado) => cacheado || fetch(evento.request))
  );
});
