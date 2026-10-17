// Minimal PWA service worker — its mere existence (with a fetch handler)
// is what makes Chrome offer "Install app".
//
// Caching policy:
//  - /static/app/*.js (the UI bundle) — NETWORK-FIRST: always try the
//    freshest code, fall back to cache only when offline. Earlier versions
//    cached it forever and users got stuck on stale UI — never again.
//  - other /static/* (icons, manifest, sw assets) — cache-first, cheap and
//    effectively immutable.
//  - everything else (/api/*, all POSTs incl. the telegram webhook, the
//    live task feed) — always goes straight to the network.
//
// Bump the suffix on any policy change: activate() wipes every cache that
// isn't CACHE, which is also how clients stuck on devin-static-v1 get free.
const CACHE = "devin-static-v2";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e =>
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => clients.claim())));

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || !url.pathname.startsWith("/static/"))
    return;
  if (url.pathname.startsWith("/static/app/")) {
    // app code: network first, cache only as an offline fallback
    e.respondWith(
      fetch(e.request)
        .then(r => {
          const copy = r.clone();
          caches.open(CACHE).then(c => c.put(e.request, copy));
          return r;
        })
        .catch(() => caches.match(e.request)));
    return;
  }
  e.respondWith(caches.match(e.request).then(hit => hit ||
    fetch(e.request).then(r => {
      const copy = r.clone();
      caches.open(CACHE).then(c => c.put(e.request, copy));
      return r;
    })));
});
