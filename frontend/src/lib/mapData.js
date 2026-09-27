/**
 * Loads the vendored neighborhood basemap.
 *
 * The geometry lives in `public/data/` rather than being imported so it is a
 * separately cacheable request instead of ~600 KB of inlined JavaScript. The
 * promise is memoized so the map, the routing graph, and any retry share one
 * request.
 */

const URL = "/data/neighborhoodMap.json";

let pending = null;

export function loadMapData() {
  if (!pending) {
    pending = fetch(URL)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Base map request failed (${response.status})`);
        }
        return response.json();
      })
      .catch((error) => {
        // Allow a later attempt to retry rather than caching the failure.
        pending = null;
        throw error;
      });
  }
  return pending;
}
