// Service worker: l'app si apre anche offline (ultimi dati scaricati, sempre cifrati).
// File dell'app dalla cache (versione = impronta della build), data.bin prima dalla rete.
const CACHE = 'diario-6230ec3910dd';
const SHELL = ["./", "app.js", "base.css", "carica.js", "d3.min.js", "glossary.js", "goal.js", "icon-180.png", "icon-192.png", "icon-512.png", "icons.js", "index.html", "inline-1.js", "inline-2.js", "inline-3.js", "inline-4.js", "manifest.webmanifest", "neon.css", "page.css", "pages.js", "perf.js", "recovery.js", "run.js", "today.js"];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k.startsWith('diario-') && k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.endsWith('/data.bin')) {
    e.respondWith(fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match(req)));
    return;
  }
  e.respondWith(caches.match(req, { ignoreSearch: true }).then((hit) => hit || fetch(req)));
});
