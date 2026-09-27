/**
 * Builds the citywide overview layer for Tabiko.
 *
 * The neighborhood build (build-neighborhood-map.mjs) holds street-level detail
 * for one area. This script holds the arterial skeleton for the whole city, so
 * zooming out shows Bengaluru's shape rather than an empty rectangle. Only
 * motorway/trunk/primary/secondary are kept: the full highway network for the
 * metro is ~219,000 ways, which is far too much to vendor, while the arterial
 * skeleton is ~7,700 ways and stays small enough to ship.
 *
 *   node scripts/build-citywide-map.mjs
 *   node scripts/build-citywide-map.mjs --bbox 12.75,77.45,13.15,77.80
 */

import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanGeometry, closeRing, lengthMeters, polygonArea, roundPoint } from "./lib/geo.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUTPUT = resolve(HERE, "../public/data/citywide.json");

// Greater Bengaluru. Deliberately generous so the outline reads as the whole
// metropolitan area rather than the ring road.
const DEFAULT_BBOX = [12.75, 77.45, 13.15, 77.8];

const ENDPOINTS = [
  "https://overpass-api.de/api/interpreter",
  "https://overpass.kumi.systems/api/interpreter",
  "https://overpass.private.coffee/api/interpreter",
];

const USER_AGENT = "tabiko-citywide-basemap/1.0 (static city overview build)";

// City-scale simplification. A kilometre-wide view cannot show a 10 m dogleg,
// so these tolerances are an order of magnitude coarser than the street level.
const ARTERIAL_TOLERANCE = 0.0009;
const ARTERIAL_MIN_LENGTH = 250;
const AREA_TOLERANCE = 0.0012;
const AREA_MIN_LENGTH = 400;

// Importance ordering for locality labels: the big names should win when the
// label budget is capped.
const PLACE_RANK = {
  city: 0,
  town: 1,
  borough: 2,
  suburb: 3,
  neighbourhood: 4,
  quarter: 5,
  locality: 6,
  island: 7,
  islet: 8,
};

const MAX_LABELS = 220;

function parseArgs(argv) {
  const config = { bbox: DEFAULT_BBOX, endpoint: null };
  for (let index = 0; index < argv.length; index += 1) {
    const [flag, inlineValue] = argv[index].split("=");
    const value = inlineValue ?? argv[index + 1];
    if (flag === "--bbox") {
      config.bbox = value.split(",").map(Number);
      if (inlineValue === undefined) index += 1;
    } else if (flag === "--endpoint") {
      config.endpoint = value;
      if (inlineValue === undefined) index += 1;
    }
  }
  return config;
}

const QUERIES = {
  arterials: `way["highway"~"^(motorway|trunk|primary|secondary)$"]({{bbox}});out geom;`,
  water: `way["natural"="water"]({{bbox}});out geom;`,
  green: `way["leisure"~"^(park|garden|golf_course|nature_reserve)$"]({{bbox}});out geom;`,
  places: `nwr["place"~"^(city|town|borough|suburb|neighbourhood|quarter|locality)$"]["name"]({{bbox}});out center;`,
};

async function fetchOverpass(query, endpoints) {
  const body = `[out:json][timeout:180];${query}`;
  const errors = [];
  for (const endpoint of endpoints) {
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        const response = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT },
          body: new URLSearchParams({ data: body }).toString(),
        });
        if (response.status === 200) {
          const payload = await response.json();
          if (payload.remark) throw new Error(`partial response: ${String(payload.remark).slice(0, 120)}`);
          return payload.elements ?? [];
        }
        errors.push(`${endpoint} HTTP ${response.status}`);
        if (![429, 502, 503, 504].includes(response.status)) break;
      } catch (error) {
        errors.push(`${endpoint} ${error.message}`);
      }
      await new Promise((resolve) => setTimeout(resolve, attempt * 4000));
    }
  }
  throw new Error(`Overpass failed for query: ${errors.join("; ")}`);
}

function centerOf(element) {
  if (element.type === "node" && typeof element.lat === "number") {
    return roundPoint([element.lat, element.lon]);
  }
  if (element.center && typeof element.center.lat === "number") {
    return roundPoint([element.center.lat, element.center.lon]);
  }
  if (Array.isArray(element.geometry) && element.geometry.length) {
    const sum = element.geometry.reduce((acc, point) => [acc[0] + point.lat, acc[1] + point.lon], [0, 0]);
    return roundPoint([sum[0] / element.geometry.length, sum[1] / element.geometry.length]);
  }
  return null;
}

async function main() {
  const config = parseArgs(process.argv.slice(2));
  const [south, west, north, east] = config.bbox;
  const bboxText = `${south},${west},${north},${east}`;
  const endpoints = config.endpoint ? [config.endpoint] : ENDPOINTS;

  const arterials = [];
  const water = [];
  const green = [];
  const labels = [];

  for (const [key, template] of Object.entries(QUERIES)) {
    process.stdout.write(`Fetching ${key} for ${bboxText} ...\n`);
    const elements = await fetchOverpass(template.replace("{{bbox}}", bboxText), endpoints);
    process.stdout.write(`  ${elements.length} elements\n`);

    if (key === "places") {
      for (const element of elements) {
        const name = element.tags?.name;
        const place = element.tags?.place;
        const at = centerOf(element);
        if (!name || !place || !at) continue;
        labels.push({ name, at, rank: PLACE_RANK[place] ?? 9 });
      }
      continue;
    }

    for (const element of elements) {
      const coords = cleanGeometry(
        element.geometry,
        key === "arterials" ? ARTERIAL_TOLERANCE : AREA_TOLERANCE,
        key === "arterials" ? ARTERIAL_MIN_LENGTH : AREA_MIN_LENGTH,
      );
      if (!coords) continue;
      if (key === "arterials") {
        arterials.push({ class: element.tags?.highway, coords });
      } else if (key === "water") {
        const ring = closeRing(coords);
        if (ring) water.push(ring);
      } else {
        const ring = closeRing(coords);
        if (ring) green.push(ring);
      }
    }
  }

  arterials.sort(
    (left, right) => lengthMeters(right.coords) - lengthMeters(left.coords),
  );

  // Keep the largest green spaces: at city zoom a 200 m park is a speck.
  green.sort((left, right) => polygonArea(right) - polygonArea(left));
  const keptGreen = green.slice(0, 900);
  water.sort((left, right) => polygonArea(right) - polygonArea(left));
  const keptWater = water.slice(0, 700);

  // One label per name, most important rank first.
  const seen = new Set();
  const keptLabels = [];
  for (const label of [...labels].sort((left, right) => left.rank - right.rank)) {
    const key = label.name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    keptLabels.push(label);
    if (keptLabels.length >= MAX_LABELS) break;
  }

  const result = {
    meta: {
      generated: new Date().toISOString().slice(0, 10),
      source: "OpenStreetMap contributors",
      license: "ODbL 1.0",
      bbox: config.bbox,
      note: "City overview layer. Regenerate with scripts/build-citywide-map.mjs",
    },
    arterials,
    water: keptWater,
    green: keptGreen,
    labels: keptLabels,
  };

  await mkdir(dirname(OUTPUT), { recursive: true });
  await writeFile(OUTPUT, `${JSON.stringify(result)}\n`, "utf8");

  const kb = (value) => (Buffer.byteLength(JSON.stringify(value)) / 1024).toFixed(0);
  process.stdout.write(
    `Wrote ${OUTPUT}\n` +
      `  arterials: ${arterials.length} (${kb(arterials)} KB), water: ${keptWater.length} (${kb(keptWater)} KB), ` +
      `green: ${keptGreen.length} (${kb(keptGreen)} KB), labels: ${keptLabels.length} (${kb(keptLabels)} KB)\n` +
      `  total: ${(Buffer.byteLength(JSON.stringify(result)) / 1024).toFixed(0)} KB\n`,
  );
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exit(1);
});
