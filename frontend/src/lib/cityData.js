/**
 * Loads the citywide overview layer.
 *
 * Holds Bengaluru's arterial skeleton (motorway through secondary), large water
 * and green spaces, and named localities, so zooming out shows the city's shape
 * instead of an empty rectangle. The street-level detail for the seeded
 * neighbourhood comes from `loadMapData`.
 *
 * Like the neighborhood data this lives in `public/data/`, so it is a separately
 * cacheable request rather than bundled JavaScript.
 */

const URL = "/data/citywide.json";

let pending = null;

export function loadCityData() {
  if (!pending) {
    pending = fetch(URL)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`City overview request failed (${response.status})`);
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
