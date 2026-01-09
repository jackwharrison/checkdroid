// static/sw.js

// Bump this VERSION on every deploy!
const VERSION = "checkdroid-sw-v4";
const STATIC_CACHE = `static-${VERSION}`;
const HTML_CACHE = `html-${VERSION}`;

// List all assets and offline pages you want to precache.
const PRECACHE_URLS = [
  "/offline/index",
  "/offline/validate",
  "/offline/registration",
  "/offline/review",
  "/static/styles.css?v=4",
  "/static/app.js?v=4",
  "/static/icons/user.svg",
  "/static/icons/arrow.svg",
  "/static/favicon.ico",
];

// INSTALL: Precache assets and offline pages.
self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(STATIC_CACHE);
      for (const url of PRECACHE_URLS) {
        try {
          const res = await fetch(url, { cache: "no-store" });
          if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
          await cache.put(url, res);
        } catch (err) {
          console.warn("[SW] Precache failed:", url, err);
        }
      }
      await self.skipWaiting();
    })()
  );
});

// ACTIVATE: Delete ALL old caches except current version.
self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.map((k) => {
          if (k !== STATIC_CACHE && k !== HTML_CACHE) {
            console.log("[SW] Deleting old cache:", k);
            return caches.delete(k);
          }
        })
      );
      await self.clients.claim();
    })()
  );
});

// Helpers
function isNavigationRequest(request) {
  return request.mode === "navigate";
}
function isApiRequest(url) {
  return url.pathname.startsWith("/api/");
}
function isStaticRequest(url) {
  return url.pathname.startsWith("/static/");
}

// FETCH: Serve requests from the appropriate cache or network.
self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Only handle same-origin requests.
  if (url.origin !== self.location.origin) return;

  // 1) Static assets: cache-first.
  if (isStaticRequest(url)) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(STATIC_CACHE);
        const hit = await cache.match(req);
        if (hit) return hit;
        try {
          const res = await fetch(req);
          cache.put(req, res.clone());
          return res;
        } catch (err) {
          return new Response("Offline", { status: 503 });
        }
      })()
    );
    return;
  }

  // 2) API: network-first, fallback to offline 503.
  if (isApiRequest(url)) {
    event.respondWith(
      (async () => {
        try {
          return await fetch(req);
        } catch (e) {
          return new Response(JSON.stringify({ offline: true }), {
            headers: { "Content-Type": "application/json" },
            status: 503,
          });
        }
      })()
    );
    return;
  }

  // 3) Navigations (HTML): network-first, fallback to cached, then offline shell.
  if (isNavigationRequest(req)) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(HTML_CACHE);
        try {
          const res = await fetch(req);
          cache.put(req, res.clone());
          return res;
        } catch (e) {
          const cached = await cache.match(req);
          if (cached) return cached;
          // Fallback by path prefix for offline shell.
          if (url.pathname.startsWith("/registration/"))
            return (await caches.open(STATIC_CACHE)).match("/offline/registration");
          if (url.pathname.startsWith("/validate/review"))
            return (await caches.open(STATIC_CACHE)).match("/offline/review");
          if (url.pathname.startsWith("/validate"))
            return (await caches.open(STATIC_CACHE)).match("/offline/validate");
          return (await caches.open(STATIC_CACHE)).match("/offline/index");
        }
      })()
    );
    return;
  }
});

// OPTIONAL: Debugging (remove in production)
// self.addEventListener("fetch", (event) => {
//   console.log("[SW] Fetch:", event.request.url);
// });

self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});
