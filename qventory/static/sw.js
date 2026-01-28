// static/sw.js
const CACHE = 'qventory-v4'; // <-- sube versión (v2, v3...) cuando cambies el SW
const APP_SHELL = [
  '/',                     // landing pública
  '/offline',              // fallback sin conexión
  '/static/style.css',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/icon-180.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;

  // Skip external URLs (like eBay OAuth redirects)
  if (!req.url.startsWith(self.location.origin)) {
    return; // Let browser handle external requests
  }

  // Skip eBay OAuth routes - let browser handle redirects natively
  if (req.url.includes('/settings/ebay/')) {
    return; // Don't intercept OAuth flow
  }

  // Navegación: intenta red, si falla usa /offline
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(() => caches.match('/offline'))
    );
    return;
  }

  // Estáticos: cache-first con actualización en segundo plano
  if (req.url.includes('/static/')) {
    event.respondWith(
      caches.match(req).then(res => {
        const fetchPromise = fetch(req).then(networkRes => {
          const clone = networkRes.clone();
          caches.open(CACHE).then(c => c.put(req, clone));
          return networkRes;
        }).catch(() => res); // si falla red, usa cache
        return res || fetchPromise;
      })
    );
    return;
  }

  // Otros: network con fallback a cache
  event.respondWith(
    fetch(req).catch(() => caches.match(req))
  );
});
