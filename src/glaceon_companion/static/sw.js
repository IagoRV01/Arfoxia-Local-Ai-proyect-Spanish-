const CACHE = "arfoxia-ui-v9";
const UI = ["/?ui=9", "/style.css?v=9", "/app.js?v=9", "/manifest.webmanifest?v=9"];
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
          if (event.request.mode === "navigate") return caches.match("/?ui=9");
          return Response.error();
        }),
      ),
  );
});
