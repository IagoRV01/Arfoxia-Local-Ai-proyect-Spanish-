const CACHE = "arfoxia-ui-v11";
const UI = ["/?ui=11", "/style.css?v=11", "/app.js?v=11", "/manifest.webmanifest?v=11"];
self.addEventListener("install", (event) =>
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(UI)).then(() => self.skipWaiting()),
  ),
);
self.addEventListener("activate", (event) =>
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((name) => name !== CACHE).map((name) => caches.delete(name))))
      .then(() => self.clients.claim()),
  ),
);
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET" || event.request.url.includes("/api/")) return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (!response || !response.ok) return response;
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() =>
        caches.match(event.request).then((cached) => {
          if (cached) return cached;
          if (event.request.mode === "navigate") return caches.match("/?ui=11");
          return Response.error();
        }),
      ),
  );
});
