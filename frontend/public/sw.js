/* Offline fallback for the GitHub-Pages copy of the Vention Printer Interface.

   The tool controls a LOCAL operator (the printer service on this machine, :8020) and serves the
   whole app there with no internet. If the internet drops, the remote Pages page can't load — a
   browser error, with the healthy local operator one click away. This worker precaches ONE
   self-contained styled page (offline.html) and serves it ONLY when a top-level NAVIGATION fails.

   It deliberately does NOT cache the app shell or /api,/ws: a cached SPA shell goes stale after a
   deploy (offline you'd then load a broken shell instead of a clear page), and API/WebSocket traffic
   must always be live. offline.html links to the local operator, which serves a fresh, working app. */
const CACHE = "vpi-offline-v1";
const OFFLINE_URL = new URL("offline.html", self.registration.scope).href;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.add(OFFLINE_URL)).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  // Drop caches from older worker versions, then take control.
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return; // page loads only — never assets, /api, or /ws
  event.respondWith(
    fetch(event.request).catch(() => caches.match(OFFLINE_URL).then((cached) => cached ?? Response.error())),
  );
});
