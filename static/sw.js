// Minimal PWA service worker — its mere existence (with a fetch handler)
// is what makes Chrome offer "Install app". Only /static/ GETs are cached
// (offline icons/manifest); /api/*, all POSTs (incl. the telegram webhook)
// and the live task feed always go straight to the network.
const CACHE = "devin-static-v1";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(clients.claim()));
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || !url.pathname.startsWith("/static/"))
    return;
  e.respondWith(caches.match(e.request).then(hit => hit ||
    fetch(e.request).then(r => {
      const copy = r.clone();
      caches.open(CACHE).then(c => c.put(e.request, copy));
      return r;
    })));
});
