/**
 * Shared geometry helpers for the Tabiko basemap build scripts.
 *
 * Everything is stored as [lat, lon] to match the rest of the app; only the
 * GeoJSON conversion in the renderers swaps to the GeoJSON [lon, lat] order.
 */

export const METERS_PER_DEGREE_LAT = 111_320;
export const METERS_PER_DEGREE_LON = 104_000;

export function roundPoint([lat, lon]) {
  return [Number(lat.toFixed(5)), Number(lon.toFixed(5))];
}

export function lengthMeters(points) {
  let total = 0;
  for (let i = 1; i < points.length; i += 1) {
    const [lat1, lon1] = points[i - 1];
    const [lat2, lon2] = points[i];
    const dLat = (lat2 - lat1) * METERS_PER_DEGREE_LAT;
    const dLon = (lon2 - lon1) * METERS_PER_DEGREE_LON * Math.cos((lat1 * Math.PI) / 180);
    total += Math.hypot(dLat, dLon);
  }
  return total;
}

/** Shoelace area in square metres. */
export function polygonArea(ring) {
  if (ring.length < 4) return 0;
  const lat0 = ring[0][0];
  const scale = METERS_PER_DEGREE_LAT * Math.cos((lat0 * Math.PI) / 180);
  let sum = 0;
  for (let i = 0; i < ring.length - 1; i += 1) {
    const x1 = (ring[i][1] - ring[0][1]) * scale;
    const y1 = (ring[i][0] - lat0) * METERS_PER_DEGREE_LAT;
    const x2 = (ring[i + 1][1] - ring[0][1]) * scale;
    const y2 = (ring[i + 1][0] - lat0) * METERS_PER_DEGREE_LAT;
    sum += x1 * y2 - x2 * y1;
  }
  return Math.abs(sum / 2);
}

function perpendicularDistance(point, start, end) {
  const [lat, lon] = point;
  const [lat1, lon1] = start;
  const [lat2, lon2] = end;
  const scale = Math.cos((lat1 * Math.PI) / 180);
  const px = (lon - lon1) * scale;
  const py = lat - lat1;
  const ex = (lon2 - lon1) * scale;
  const ey = lat2 - lat1;
  const lengthSquared = ex * ex + ey * ey;
  if (lengthSquared === 0) return Math.hypot(px, py);
  const t = Math.max(0, Math.min(1, (px * ex + py * ey) / lengthSquared));
  return Math.hypot(px - ex * t, py - ey * t);
}

/** Douglas-Peucker simplification in degrees. */
export function simplify(points, tolerance) {
  if (points.length <= 2) return points;
  let maxDistance = 0;
  let index = 0;
  for (let i = 1; i < points.length - 1; i += 1) {
    const distance = perpendicularDistance(points[i], points[0], points[points.length - 1]);
    if (distance > maxDistance) {
      maxDistance = distance;
      index = i;
    }
  }
  if (maxDistance <= tolerance) return [points[0], points[points.length - 1]];
  const left = simplify(points.slice(0, index + 1), tolerance);
  const right = simplify(points.slice(index), tolerance);
  return left.slice(0, -1).concat(right);
}

/**
 * Normalize, deduplicate, simplify, and drop fragments that are too short.
 * Returns null when the geometry is not worth keeping.
 */
export function cleanGeometry(geometry, tolerance, minLength) {
  if (!geometry || geometry.length < 2) return null;
  // Overpass `out geom` yields {lat, lon} objects; normalize to [lat, lon] pairs.
  const points = geometry.map((point) =>
    Array.isArray(point) ? point : [point.lat, point.lon],
  );
  const deduped = points.filter(
    (point, index) =>
      index === 0 || point[0] !== points[index - 1][0] || point[1] !== points[index - 1][1],
  );
  if (deduped.length < 2 || lengthMeters(deduped) < minLength) return null;
  const simplified = simplify(deduped, tolerance);
  if (simplified.length < 2 || lengthMeters(simplified) < minLength * 0.6) return null;
  return simplified.map(roundPoint);
}

export function closeRing(coordinates) {
  if (coordinates.length < 3) return null;
  const first = coordinates[0];
  const last = coordinates[coordinates.length - 1];
  if (first[0] === last[0] && first[1] === last[1]) return coordinates;
  return [...coordinates, first];
}
