/* static/sw.js */
const VERSION = "checkdroid-sw-v1"; // bump this on releases
const STATIC_CACHE = `static-${VERSION}`;
const HTML_CACHE = `html-${VERSION}`;

const PRECACHE_URLS = [
  // App shell pages (see section 3)
  "/offline/index",
  "/offline/validate",
  "/offline/registration",
  "/offline/review",

  // Static assets
  "/static/styles.css",
  "/static/app.js",
  "/static/icons/user.svg",
  "/static/icons/arrow.svg",
  "/static/favicon.ico",
];
self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(STATIC_CACHE);

    // Precache sequentially so one missing URL doesn't brick the SW install
    for (const url of PRECACHE_URLS) {
      try {
        const res = await fetch(url, { cache: "no-store" });
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        await cache.put(url, res);
      } catch (err) {
        // Keep installing even if one resource fails (important in Flask dev)
        console.warn("[SW] Precache failed:", url, err);
      }
    }

    await self.skipWaiting();
  })());
});


self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.map((k) => {
          if (k !== STATIC_CACHE && k !== HTML_CACHE) return caches.delete(k);
        })
      );
      await self.clients.claim();
    })()
  );
});

function isNavigationRequest(request) {
  return request.mode === "navigate";
}

function isApiRequest(url) {
  return url.pathname.startsWith("/api/");
}

function isStaticRequest(url) {
  return url.pathname.startsWith("/static/");
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Only handle same-origin
  if (url.origin !== self.location.origin) return;

  // 1) Static assets: cache-first
  if (isStaticRequest(url)) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(STATIC_CACHE);
        const hit = await cache.match(req);
        if (hit) return hit;
        const res = await fetch(req);
        cache.put(req, res.clone());
        return res;
      })()
    );
    return;
  }

  // 2) API: network-first (fall back to cache if you want; many apps skip caching API)
  if (isApiRequest(url)) {
    event.respondWith(
      (async () => {
        try {
          return await fetch(req);
        } catch (e) {
          // Optional: return a synthetic offline response
          return new Response(JSON.stringify({ offline: true }), {
            headers: { "Content-Type": "application/json" },
            status: 503,
          });
        }
      })()
    );
    return;
  }

  // 3) Navigations (HTML): offline-first app-shell fallback
  if (isNavigationRequest(req)) {
    event.respondWith(
      (async () => {
        try {
          // Online: try network first (keeps normal behavior when connected)
          const networkRes = await fetch(req);

          // Cache a copy of visited pages (optional but useful)
          const cache = await caches.open(HTML_CACHE);
          cache.put(req, networkRes.clone());

          return networkRes;
        } catch (e) {
          // Offline: try cached exact page first
          const cache = await caches.open(HTML_CACHE);
          const cached = await cache.match(req);
          if (cached) return cached;

          // Otherwise: route to the correct offline shell
          if (url.pathname.startsWith("/registration/")) {
            return (await caches.open(STATIC_CACHE)).match("/offline/registration");
          }
          if (url.pathname.startsWith("/validate/review")) {
            return (await caches.open(STATIC_CACHE)).match("/offline/review");
          }
          if (url.pathname.startsWith("/validate")) {
            return (await caches.open(STATIC_CACHE)).match("/offline/validate");
          }
          // default
          return (await caches.open(STATIC_CACHE)).match("/offline/index");
        }
      })()
    );
    return;
  }
});
