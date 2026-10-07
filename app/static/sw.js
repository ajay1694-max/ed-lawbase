// ED LawBase service worker - makes the site installable as an app.
// Deliberately minimal: it caches ONLY the app icons and the offline notice.
// Pages, searches, judgments and briefs always come from the server (they sit behind the login),
// so no case-law results or session data are stored on the device.
const CACHE = "lawbase-shell-v1";
const SHELL = ["/offline.html", "/icon-192.png", "/icon-512.png", "/icon-maskable-512.png", "/favicon.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;                       // logins, exports: straight to the network
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (req.mode === "navigate") {                          // pages: network, or the offline notice
    e.respondWith(fetch(req).catch(() => caches.match("/offline.html")));
    return;
  }
  if (SHELL.includes(url.pathname)) {                     // icons: cache first
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req)));
  }
  // everything else (/api/*, scripts): untouched - always the network
});
