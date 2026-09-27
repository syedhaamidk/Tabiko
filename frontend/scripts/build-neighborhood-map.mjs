/**
 * Builds the vendored neighborhood basemap used by Tabiko.
 *
 * Tabiko draws its own map, so the app has no runtime dependency on a tile
 * provider. This script pulls real OpenStreetMap geometry once, simplifies it
 * aggressively, and writes a compact JSON file the frontend imports directly.
 *
 *   node scripts/build-neighborhood-map.mjs
 *
 * Override the area with CLI flags, e.g.
 *   node scripts/build-neighborhood-map.mjs --center 13.0689,77.5708 --span 0.011,0.013
 */

import { writeFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
// Served as a static asset rather than bundled, so the base map stays a
// separately cacheable request instead of inflating the JavaScript bundle.
const OUTPUT = resolve(HERE, "../public/data/neighborhoodMap.json");

const DEFAULTS = {
  center: [12.9915, 77.552],
  span: [0.012, 0.0128],
  endpoint: "https://overpass-api.de/api/interpreter",
  // A dense city has tens of thousands of building footprints. Keeping a capped
  // set of the larger ones preserves the urban massing that makes a map legible
  // while holding the payload to a size that still compresses well.
  maxBuildings: 4000,
  minBuildingArea: 150,
  buildingTolerance: 0.00007,
};

function parseArgs(argv) {
  const config = { ...DEFAULTS };
  for (let index = 0; index < argv.length; index += 1) {
    const [flag, inlineValue] = argv[index].split("=");
    const value = inlineValue ?? argv[index + 1];
    if (flag === "--center") {
      const [lat, lon] = value.split(",").map(Number);
      config.center = [lat, lon];
      if (inlineValue === undefined) index += 1;
    } else if (flag === "--span") {
      const [lat, lon] = value.split(",").map(Number);
      config.span = [lat, lon];
      if (inlineValue === undefined) index += 1;
    } else if (flag === "--endpoint") {
      config.endpoint = value;
      if (inlineValue === undefined) index += 1;
    } else if (flag === "--tolerance-scale") {
      TOLERANCE_SCALE = Number(value);
      if (inlineValue === undefined) index += 1;
    } else if (flag === "--max-buildings") {
      config.maxBuildings = Number(value);
      if (inlineValue === undefined) index += 1;
    } else if (flag === "--min-building-area") {
      config.minBuildingArea = Number(value);
      if (inlineValue === undefined) index += 1;
    } else if (flag === "--building-tolerance") {
      config.buildingTolerance = Number(value);
      if (inlineValue === undefined) index += 1;
    }
  }
  return config;
}

const ROAD_CLASSES = [
  "motorway",
  "trunk",
  "primary",
  "secondary",
  "tertiary",
  "residential",
  "unclassified",
  "living_street",
  "pedestrian",
  "footway",
  "service",
];

// Draw priority, line weight class, simplification tolerance (degrees),
// and the shortest segment worth keeping. Lower tolerances keep more junction
// vertices, which is what lets in-app directions route across the network.
const ROAD_RULES = {
  motorway: { tolerance: 0.000015, minLength: 40 },
  trunk: { tolerance: 0.000015, minLength: 40 },
  primary: { tolerance: 0.000018, minLength: 30 },
  secondary: { tolerance: 0.00002, minLength: 30 },
  tertiary: { tolerance: 0.000025, minLength: 25 },
  residential: { tolerance: 0.00004, minLength: 25 },
  unclassified: { tolerance: 0.000045, minLength: 20 },
  living_street: { tolerance: 0.00005, minLength: 20 },
  pedestrian: { tolerance: 0.000055, minLength: 20 },
  footway: { tolerance: 0.00007, minLength: 15 },
  service: { tolerance: 0.00007, minLength: 15 },
};

// Simplification is deliberately loose only where it does not hurt routing.
// Tightening this scale keeps more junction vertices, which is what lets
// in-app directions connect streets; 0.4 costs a few KB and is the default.
let TOLERANCE_SCALE = 0.4;

const METERS_PER_DEGREE_LAT = 111_320;
const METERS_PER_DEGREE_LON = 104_000;

function buildQuery(bounds) {
  const [south, west, north, east] = bounds;
  const bbox = `${south},${west},${north},${east}`;
  return `[out:json][timeout:90];
(
  way["highway"~"^(${ROAD_CLASSES.join("|")})$"](${bbox});
  way["building"](${bbox});
  way["building:part"](${bbox});
  way["natural"="water"](${bbox});
  way["waterway"~"^(river|canal|stream)$"](${bbox});
  way["landuse"~"^(grass|forest|recreation_ground|village_green|cemetery|industrial)$"](${bbox});
  way["leisure"~"^(park|garden|playground|pitch)$"](${bbox});
  nwr["name"]["amenity"~"^(restaurant|cafe|fast_food|bar|pub|ice_cream|marketplace|place_of_worship|school|hospital|library|theatre|cinema|hotel)$"](${bbox});
  nwr["name"]["shop"~"^(bakery|supermarket|convenience|butcher|greengrocer)$"](${bbox});
  nwr["name"]["place"~"^(neighbourhood|suburb|quarter|locality|island|islet)$"](${bbox});
  way["name"]["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"](${bbox});
);
out geom;`;
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

function simplify(points, tolerance) {
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

function lengthMeters(points) {
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

/** Shoelace area in square metres, used to rank building footprints by size. */
function polygonArea(ring) {
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

function roundPoint([lat, lon]) {
  return [Number(lat.toFixed(5)), Number(lon.toFixed(5))];
}

function cleanGeometry(geometry, tolerance, minLength) {
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

const POI_AMENITY = new Set([
  "restaurant",
  "cafe",
  "fast_food",
  "bar",
  "pub",
  "ice_cream",
  "marketplace",
  "place_of_worship",
  "school",
  "hospital",
  "library",
  "theatre",
  "cinema",
  "hotel",
  "bakery",
  "supermarket",
  "convenience",
  "butcher",
  "greengrocer",
]);

function classify(element) {
  const tags = element.tags ?? {};
  if (tags.highway && ROAD_CLASSES.includes(tags.highway)) {
    return { kind: "road", class: tags.highway, name: tags.name ?? null };
  }
  if (tags.building || tags["building:part"]) return { kind: "building" };
  if (tags.natural === "water") return { kind: "water" };
  if (tags.waterway) return { kind: "water" };
  if (tags.leisure === "park" || tags.leisure === "garden") return { kind: "park" };
  if (tags.leisure === "playground" || tags.leisure === "pitch") return { kind: "pitch" };
  if (tags.landuse === "industrial") return { kind: "industrial" };
  if (tags.landuse || tags.natural === "wood") return { kind: "park" };
  if (tags.amenity && POI_AMENITY.has(tags.amenity) && tags.name) {
    return { kind: "poi", category: tags.amenity, name: tags.name };
  }
  if (tags.shop && POI_AMENITY.has(tags.shop) && tags.name) {
    return { kind: "poi", category: tags.shop, name: tags.name };
  }
  if (tags.place && tags.name && !tags.highway) {
    return { kind: "district", name: tags.name };
  }
  return null;
}

function midpoint(points) {
  const middle = points[Math.floor(points.length / 2)];
  return roundPoint(middle);
}

function elementAnchor(element) {
  if (element.type === "node" && typeof element.lat === "number") {
    return roundPoint([element.lat, element.lon]);
  }
  if (!element.geometry?.length) return null;
  const sum = element.geometry.reduce(
    (accumulator, point) => [accumulator[0] + point.lat, accumulator[1] + point.lon],
    [0, 0],
  );
  return roundPoint([sum[0] / element.geometry.length, sum[1] / element.geometry.length]);
}

// A landmark worth drawing at a glance before the rest.
const POI_PRIORITY = [
  "hospital",
  "school",
  "place_of_worship",
  "marketplace",
  "supermarket",
  "bakery",
  "hotel",
  "theatre",
  "cinema",
  "library",
  "restaurant",
  "cafe",
  "bar",
  "pub",
  "fast_food",
  "ice_cream",
  "convenience",
  "butcher",
  "greengrocer",
];

async function main() {
  const config = parseArgs(process.argv.slice(2));
  const [centerLat, centerLon] = config.center;
  const [latSpan, lonSpan] = config.span;
  const bounds = [
    Number((centerLat - latSpan).toFixed(6)),
    Number((centerLon - lonSpan).toFixed(6)),
    Number((centerLat + latSpan).toFixed(6)),
    Number((centerLon + lonSpan).toFixed(6)),
  ];

  process.stdout.write(`Fetching OSM geometry for ${bounds.join(", ")} ...\n`);
  const query = buildQuery(bounds);
  let payload = null;
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    try {
      const response = await fetch(
        `${config.endpoint}?data=${encodeURIComponent(query)}`,
        { headers: { "User-Agent": "tabiko-neighborhood-map/1.0 (static basemap build)" } },
      );
      if (!response.ok) {
        const detail = (await response.text()).slice(0, 200);
        throw new Error(`Overpass responded ${response.status}: ${detail}`);
      }
      payload = await response.json();
      break;
    } catch (error) {
      if (attempt === 4) throw error;
      const waitSeconds = attempt * 5;
      process.stdout.write(`  attempt ${attempt} failed (${error.message.slice(0, 80)}); retrying in ${waitSeconds}s\n`);
      await new Promise((resolve) => setTimeout(resolve, waitSeconds * 1000));
    }
  }
  const elements = payload?.elements ?? [];
  process.stdout.write(`Received ${elements.length} ways.\n`);

  const roads = [];
  const water = [];
  const parks = [];
  const pitches = [];
  const industrial = [];
  const buildings = [];
  const pois = [];
  const districts = [];

  for (const element of elements) {
    const info = classify(element);
    if (!info) continue;
    if (info.kind === "road") {
      const rules = ROAD_RULES[info.class];
      const coords = cleanGeometry(
        element.geometry,
        rules.tolerance * TOLERANCE_SCALE,
        rules.minLength,
      );
      if (!coords) continue;
      roads.push({ class: info.class, name: info.name, coords });
    } else if (info.kind === "poi") {
      const at = elementAnchor(element);
      if (!at) continue;
      pois.push({ name: info.name, category: info.category, at });
    } else if (info.kind === "district") {
      const at = elementAnchor(element);
      if (!at) continue;
      districts.push({ name: info.name, at });
    } else {
      // Buildings get the coarsest tolerance: at city zoom only the footprint
      // silhouette matters, and dropping fragments keeps the payload small.
      const tolerance =
        info.kind === "building"
          ? config.buildingTolerance
          : info.kind === "water"
            ? 0.00006
            : 0.00008;
      const minLength = info.kind === "building" ? 18 : info.kind === "water" ? 40 : 60;
      const coords = cleanGeometry(element.geometry, tolerance, minLength);
      if (!coords) continue;
      const bucket =
        info.kind === "water"
          ? water
          : info.kind === "park"
            ? parks
            : info.kind === "pitch"
              ? pitches
              : info.kind === "building"
                ? buildings
                : industrial;
      bucket.push(coords);
    }
  }

  // Roads sort major-first so the renderer can paint arterials on top.
  roads.sort((left, right) => ROAD_CLASSES.indexOf(left.class) - ROAD_CLASSES.indexOf(right.class));

  // Label only the biggest named arteries, at most one label per street name.
  const seenLabels = new Set();
  const labels = [];
  for (const road of roads) {
    const isLabelable = ["motorway", "trunk", "primary", "secondary", "tertiary"].includes(road.class);
    if (!isLabelable || !road.name || seenLabels.has(road.name)) continue;
    if (road.coords.length < 3) continue;
    seenLabels.add(road.name);
    labels.push({ name: road.name, class: road.class, at: midpoint(road.coords) });
    if (labels.length >= 30) break;
  }

  // One landmark dot per name so the map has recognizable anchors.
  const seenPois = new Set();
  pois.sort(
    (left, right) =>
      POI_PRIORITY.indexOf(left.category) - POI_PRIORITY.indexOf(right.category),
  );
  const landmarks = [];
  for (const poi of pois) {
    if (seenPois.has(poi.name)) continue;
    seenPois.add(poi.name);
    landmarks.push(poi);
    if (landmarks.length >= 90) break;
  }

  // Buildings dominate the payload in a dense area, so keep only the largest
  // footprints: the big blocks are what read as a city at map zoom.
  buildings.sort((left, right) => polygonArea(right) - polygonArea(left));
  const keptBuildings = buildings
    .filter((ring) => polygonArea(ring) >= config.minBuildingArea)
    .slice(0, config.maxBuildings);

  const result = {
    meta: {
      generated: new Date().toISOString().slice(0, 10),
      source: "OpenStreetMap contributors",
      license: "ODbL 1.0",
      bbox: bounds,
      note: "Regenerate with scripts/build-neighborhood-map.mjs",
    },
    center: [centerLat, centerLon],
    roads,
    labels,
    districts,
    landmarks,
    water,
    parks,
    pitches,
    industrial,
    buildings: keptBuildings,
  };

  await mkdir(dirname(OUTPUT), { recursive: true });
  await writeFile(OUTPUT, `${JSON.stringify(result)}\n`, "utf8");

  const bytes = Buffer.byteLength(JSON.stringify(result));
  process.stdout.write(
    `Wrote ${OUTPUT}\n` +
      `  roads: ${roads.length}, buildings: ${keptBuildings.length} (from ${buildings.length}), ` +
      `water: ${water.length}, parks: ${parks.length}, pitches: ${pitches.length}, ` +
      `industrial: ${industrial.length}, labels: ${labels.length}, ` +
      `districts: ${districts.length}, landmarks: ${landmarks.length}\n` +
      `  size: ${(bytes / 1024).toFixed(1)} KB\n`,
  );
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exit(1);
});
