// App-shell service worker.
// - Navigations (HTML): network-first, so a new deploy is picked up on the next
//   load instead of being frozen at install time. Falls back to the cached shell
//   when offline.
// - Hashed assets: cache-first (their filenames change per build, so this is safe).
// - API/streaming traffic: never touched.
const CACHE = "aeon-shell-v2";
const SHELL = ["/", "/manifest.webmanifest", "/favicon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) return; // never cache API/stream traffic

  // Network-first for page navigations so new deploys show up without a manual
  // cache clear; keep a fresh copy of the shell for offline fallback.
  if (e.request.mode === "navigate") {
    e.respondWith(
      fetch(e.request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put("/", copy));
          return res;
        })
        .catch(() => caches.match("/")),
    );
    return;
  }

  // Cache-first for everything else (immutable hashed assets, icons, manifest).
  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request).catch(() => caches.match("/"))),
  );
});
