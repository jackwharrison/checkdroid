// static/sw.js

// CHANGE THIS every time you deploy frontend changes!
const VERSION = "checkdroid-sw-v3";
const STATIC_CACHE = `static-${VERSION}`;
const HTML_CACHE = `html-${VERSION}`;

// List everything you want to precache (offline fallback)
const PRECACHE_URLS = [
  "/offline/index",
  "/offline/validate",
  "/offline/registration",
  "/offline/review",
  "/static/styles.css?v=3",
  "/static/app.js?v=3",
  "/static/icons/user.svg",
  "/static/icons/arrow.svg",
  "/static/favicon.ico",
];

// --- INSTALL: Precache core assets ---
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

// --- ACTIVATE: Delete ALL old caches for a guaranteed fresh start ---
self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => {
        if (k !== STATIC_CACHE && k !== HTML_CACHE) {
          console.log("[SW] Deleting old cache:", k);
          return caches.delete(k);
        }
      }));
      await self.clients.claim();
    })()
  );
});

// --- Helpers for request detection ---
function isNavigationRequest(request) {
  return request.mode === "navigate";
}
function isApiRequest(url) {
  return url.pathname.startsWith("/api/");
}
function isStaticRequest(url) {
  return url.pathname.startsWith("/static/");
}

// --- FETCH: Respond to requests based on type ---
self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Only handle requests for this origin
  if (url.origin !== self.location.origin) return;

  // 1) Static assets: cache-first, recache on miss
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

  // 2) API: network-first, fallback to 503 offline
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

  // 3) HTML navigation: network-first, fallback to cached, then offline shell
  if (isNavigationRequest(req)) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(HTML_CACHE);
        try {
          const res = await fetch(req);
          cache.put(req, res.clone());
          return res;
        } catch (e) {
          // First try an exact cached copy
          const cached = await cache.match(req);
          if (cached) return cached;
          // Fallback by path prefix
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

// --- OPTIONAL: Debug logs for troubleshooting (remove in prod) ---
self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});
