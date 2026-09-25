/* Autodestructivo, a propósito -- reemplaza al service worker cache-first de antes.
 *
 * Bug real encontrado el 25/09/2026: el SW anterior cacheaba el shell (index.html/app.js/
 * style.css) con estrategia cache-first, pero el contenido de ESTE ARCHIVO (sw.js) nunca
 * cambiaba entre actualizaciones del shell -- y el navegador solo vuelve a instalar un service
 * worker cuando el propio sw.js cambia de bytes. Resultado: cada mejora que se subió al
 * servidor quedó invisible para cualquiera que ya hubiera abierto la PWA una vez, sin ningún
 * error visible -- "sigue todo igual" era exactamente ese síntoma.
 *
 * Mientras el proyecto esté en desarrollo activo (cambios frecuentes, probados de verdad viendo
 * el resultado), cachear el shell hace más daño que bien. Este SW nuevo no cachea nada: borra
 * los caches viejos, se autodesregistra, y fuerza a recargar las pestañas abiertas para que
 * queden sirviendo todo directo de la red otra vez. app.js ya no registra ningún service
 * worker, así que esto es una limpieza de una sola vez -- si más adelante hace falta soporte
 * offline de verdad, la estrategia correcta es network-first con revalidación, no cache-first.
 */

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    (async () => {
      const claves = await caches.keys();
      await Promise.all(claves.map((k) => caches.delete(k)));
      await self.registration.unregister();
      const clientes = await self.clients.matchAll({ type: "window" });
      for (const cliente of clientes) cliente.navigate(cliente.url);
    })()
  );
});
