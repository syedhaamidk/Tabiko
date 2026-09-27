/**
 * Offline shell for Tabiko.
 *
 * The app is useful with no connection for one specific reason: the basemap is
 * our own vector data served from this origin, not a third-party tile server. So
 * the map still draws offline, which is the whole point of caching anything.
 *
 * Three rules, deliberately:
 *   1. API calls are never cached. Place data, saved places and reviews all
 *      change, and a stale "3 spots near you" is worse than an honest error.
 *   2. Navigations fall back to the cached shell only when the network fails,
 *      so an updated deploy is picked up on the next online visit.
 *   3. Static assets are cache-first, because their URLs are content-hashed.
 */

const VERSION = "tabiko-v1";
const SHELL_CACHE = `${VERSION}-shell`;
const DATA_CACHE = `${VERSION}-data`;

// The shell document and the manifest. Build assets are not listed here because
// their names are content-hashed; they are discovered from the document below.
const SHELL_DOCUMENT = "/index.html";
const SHELL = ["/", SHELL_DOCUMENT, "/manifest.webmanifest"];

// The self-drawn basemap. Large, but this is the feature that must work offline.
const MAP_DATA = ["/data/citywide.json", "/data/neighborhoodMap.json"];

/**
 * Cache the hashed build assets by reading them out of index.html.
 *
 * The very first page load fetches its JS and CSS before this worker has
 * activated, so relying on runtime caching alone would leave a first-time
 * visitor with no offline copy at all. Reading the document at install time
 * closes that gap without a build step, because the document is always the
 * source of truth for what the current bundle references.
 */
async function precacheBuildAssets() {
  const response = await fetch(SHELL_DOCUMENT, { cache: "reload" });
  if (!response.ok) return;
  const html = await response.text();
  const urls = new Set();
  for (const match of html.matchAll(/(?:src|href)="([^"]+)"/g)) {
    const value = match[1];
    if (value.startsWith("/") && !value.startsWith("//")) urls.add(value);
  }
  const cache = await caches.open(SHELL_CACHE);
  await Promise.allSettled([...urls].map((url) => cache.add(url)));
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      // addAll is all-or-nothing, so one bad URL would leave no cache at all.
      .then((cache) => Promise.allSettled(SHELL.map((url) => cache.add(url))))
      .then(precacheBuildAssets)
      .then(() => caches.open(DATA_CACHE))
      // The basemap is the product, so it is worth the ~900 KB to have it work
      // offline from the very first completed visit.
      .then((cache) => Promise.allSettled(MAP_DATA.map((url) => cache.add(url))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => !key.startsWith(VERSION))
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

function isApiRequest(url) {
  return url.pathname.startsWith("/api/");
}

function isMapData(url) {
  return url.pathname.startsWith("/data/");
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Never serve a cached API response, and never let one enter the cache.
  if (isApiRequest(url)) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) =>
          // A gateway or captive portal can answer with a real 502/503 rather
          // than failing the request, so a non-ok response has to fall back too.
          response.ok
            ? response
            : caches.match(SHELL_DOCUMENT).then((cached) => cached ?? response),
        )
        .catch(() =>
          caches.match(SHELL_DOCUMENT).then((cached) => cached ?? Response.error()),
        ),
    );
    return;
  }

  if (isMapData(url)) {
    event.respondWith(
      caches.open(DATA_CACHE).then(async (cache) => {
        const cached = await cache.match(request);
        if (cached) return cached;
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
      }),
    );
    return;
  }

  // Hashed build assets: cache-first is safe because the name changes on change.
  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ??
        fetch(request).then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        }),
    ),
  );
});
