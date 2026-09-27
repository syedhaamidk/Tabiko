/**
 * Grid clustering for map markers.
 *
 * A city-wide result set is thousands of places, and one DOM node per place
 * makes the map unusable. Points are bucketed into square cells whose size is
 * derived from the current zoom, so a cluster always covers roughly the same
 * number of screen pixels and zooming in naturally splits clusters apart.
 *
 * All input and output coordinates are [lat, lon].
 */

// Below this zoom every place is folded into a cluster; at or above it, a cell
// that holds a single place is drawn as that place's own pin.
const SINGLE_PLACE_ZOOM = 16;

const TARGET_CELL_PIXELS = 58;

function cellSizeInDegrees(zoom) {
  // Leaflet's world is 256px * 2^zoom wide and covers 360 degrees of longitude.
  const worldPixels = 256 * 2 ** zoom;
  return (360 / worldPixels) * TARGET_CELL_PIXELS;
}

function dominantCuisine(tally) {
  let best = null;
  let bestCount = 0;
  for (const [cuisine, count] of tally) {
    if (count > bestCount) {
      bestCount = count;
      best = cuisine;
    }
  }
  return best;
}

function firstCuisine(cuisineTags) {
  if (!cuisineTags) return null;
  for (const tag of cuisineTags.split(",")) {
    const trimmed = tag.trim();
    if (trimmed) return trimmed;
  }
  return null;
}

/**
 * Bucket points for the given zoom.
 *
 * Returns clusters sorted largest-first. Each cluster carries the member
 * bounding box so a click can zoom to exactly the places inside it, plus the
 * dominant cuisine so the bubble can be coloured like the pins around it.
 */
export function clusterPoints(points, zoom) {
  if (!points.length) return [];

  if (zoom >= SINGLE_PLACE_ZOOM) {
    return points.map((point) => ({
      kind: "point",
      id: point.id,
      latitude: point.latitude,
      longitude: point.longitude,
      count: 1,
      cuisine: firstCuisine(point.cuisine_tags),
      name: point.name,
      typeTag: point.type_tag,
    }));
  }

  const cell = cellSizeInDegrees(zoom);
  const cells = new Map();

  for (const point of points) {
    const row = Math.floor(point.latitude / cell);
    const column = Math.floor(point.longitude / cell);
    const key = `${row}:${column}`;
    let bucket = cells.get(key);
    if (!bucket) {
      bucket = {
        count: 0,
        sumLat: 0,
        sumLon: 0,
        minLat: point.latitude,
        maxLat: point.latitude,
        minLon: point.longitude,
        maxLon: point.longitude,
        cuisines: new Map(),
        sample: point,
      };
      cells.set(key, bucket);
    }
    bucket.count += 1;
    bucket.sumLat += point.latitude;
    bucket.sumLon += point.longitude;
    bucket.minLat = Math.min(bucket.minLat, point.latitude);
    bucket.maxLat = Math.max(bucket.maxLat, point.latitude);
    bucket.minLon = Math.min(bucket.minLon, point.longitude);
    bucket.maxLon = Math.max(bucket.maxLon, point.longitude);
    const cuisine = firstCuisine(point.cuisine_tags);
    if (cuisine) {
      bucket.cuisines.set(cuisine, (bucket.cuisines.get(cuisine) ?? 0) + 1);
    }
  }

  return [...cells.values()]
    .map((bucket) => ({
      kind: "cluster",
      id: `${bucket.minLat}:${bucket.minLon}:${bucket.count}`,
      latitude: bucket.sumLat / bucket.count,
      longitude: bucket.sumLon / bucket.count,
      count: bucket.count,
      cuisine: dominantCuisine(bucket.cuisines),
      bounds: [
        [bucket.minLat, bucket.minLon],
        [bucket.maxLat, bucket.maxLon],
      ],
      sample: bucket.sample,
    }))
    .sort((left, right) => right.count - left.count);
}

/** Drop anything whose centre is outside the padded view, to keep the DOM small. */
export function cullToBounds(clusters, bounds) {
  if (!bounds) return clusters;
  return clusters.filter(
    (cluster) =>
      cluster.latitude >= bounds.getSouth() &&
      cluster.latitude <= bounds.getNorth() &&
      cluster.longitude >= bounds.getWest() &&
      cluster.longitude <= bounds.getEast(),
  );
}
