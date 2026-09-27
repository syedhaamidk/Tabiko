/**
 * In-app walking directions.
 *
 * Tabiko never hands the user off to a third-party maps app. Instead we route
 * across the same vendored OpenStreetMap street network the map draws, so the
 * route line and the streets on screen can never disagree.
 *
 * Coordinates are [lat, lon] throughout, matching the rest of the app.
 */

const METERS_PER_DEGREE_LAT = 111_320;
const METERS_PER_DEGREE_LON = 104_000;

// Coarse grid for node identity. Our geometry is stored to 5 decimals (~1.1 m),
// so a 4-decimal key (~11 m) merges ways that meet at a junction even when
// simplification dropped the shared vertex.
const GRID = 1e4;

// Walking cost multipliers: >1 makes a street more expensive to choose, which
// pushes routes onto footpaths and quiet lanes the way a walker would.
const AVOIDANCE = {
  motorway: 7,
  trunk: 5,
  primary: 2.6,
  secondary: 1.7,
  tertiary: 1.15,
  residential: 1,
  unclassified: 1,
  living_street: 0.9,
  pedestrian: 0.75,
  footway: 0.7,
  service: 0.85,
};

const DEFAULT_AVOIDANCE = 1.1;

const WALKING_METERS_PER_SECOND = 1.35;

// Simplification removes the shared vertex where one street ends on another, so
// a rendered network can look connected while actually being many separate
// pieces. T-junction detection rebuilds those crossings: any node sitting on
// another street's segment splits that segment and gets a short connector.
//
// The radius is measured empirically. On the vendored area 14 m leaves ~7% of
// real place-to-place pairs unroutable, and 30 m connects every pair. Thirty
// metres can bridge a narrow gap between two streets, which at this map scale
// (about 10 m per pixel at the zoom a route is viewed at) is a few pixels, and
// being able to route at all matters more than that precision.
const SPLIT_RADIUS_METERS = 30;
const INDEX_CELL_DEGREES = 0.0004;

const CLASS_PHRASE = {
  motorway: "the highway",
  trunk: "the highway",
  primary: "the main road",
  secondary: "the main street",
  tertiary: "the cross street",
  residential: "the street",
  unclassified: "the lane",
  living_street: "the shared lane",
  service: "the service lane",
  pedestrian: "the footpath",
  footway: "the footpath",
};

const CLASS_PRIORITY = {
  motorway: 6,
  trunk: 6,
  primary: 5,
  secondary: 4,
  tertiary: 3,
  residential: 2,
  unclassified: 2,
  living_street: 1,
  pedestrian: 0,
  footway: 0,
  service: 1,
};

const COMPASS = [
  "north",
  "north-east",
  "east",
  "south-east",
  "south",
  "south-west",
  "west",
  "north-west",
];

function gridKey(lat, lon) {
  return `${Math.round(lat * GRID)}:${Math.round(lon * GRID)}`;
}

export function distanceMeters(from, to) {
  const dLat = (to[0] - from[0]) * METERS_PER_DEGREE_LAT;
  const dLon = (to[1] - from[1]) * METERS_PER_DEGREE_LON * Math.cos((from[0] * Math.PI) / 180);
  return Math.hypot(dLat, dLon);
}

function bearingBetween(from, to) {
  const lat1 = (from[0] * Math.PI) / 180;
  const lat2 = (to[0] * Math.PI) / 180;
  const dLon = ((to[1] - from[1]) * Math.PI) / 180;
  const y = Math.sin(dLon) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  return (Math.atan2(y, x) * 180) / Math.PI;
}

function normalizeBearing(degrees) {
  return ((degrees % 360) + 360) % 360;
}

function compassOf(degrees) {
  return COMPASS[Math.round(normalizeBearing(degrees) / 45) % 8];
}

function turnDescription(delta) {
  const magnitude = Math.abs(delta);
  const side = delta > 0 ? "right" : "left";
  if (magnitude < 20) return { type: "continue", text: "Continue" };
  if (magnitude < 55) return { type: `slight-${side}`, text: `Bear ${side}` };
  if (magnitude < 125) return { type: side, text: `Turn ${side}` };
  if (magnitude < 170) return { type: `sharp-${side}`, text: `Turn sharp ${side}` };
  return { type: "uturn", text: "Turn around" };
}

/** Project a [lat, lon] point onto a segment, in local metre space. */
function projectOnSegment(point, start, end) {
  const scale = Math.cos((start[0] * Math.PI) / 180);
  const bx = (end[1] - start[1]) * METERS_PER_DEGREE_LON * scale;
  const by = (end[0] - start[0]) * METERS_PER_DEGREE_LAT;
  const px = (point[1] - start[1]) * METERS_PER_DEGREE_LON * scale;
  const py = (point[0] - start[0]) * METERS_PER_DEGREE_LAT;

  const lengthSquared = bx * bx + by * by;
  if (lengthSquared === 0) return null;

  const t = Math.max(0, Math.min(1, (px * bx + py * by) / lengthSquared));
  const cx = bx * t;
  const cy = by * t;
  return {
    t,
    distance: Math.hypot(px - cx, py - cy),
    point: [start[0] + cy / METERS_PER_DEGREE_LAT, start[1] + cx / (METERS_PER_DEGREE_LON * scale)],
  };
}

export function buildStreetGraph(roads) {
  const nodes = new Map();

  const nodeFor = (point) => {
    const key = gridKey(point[0], point[1]);
    let node = nodes.get(key);
    if (!node) {
      node = { id: key, point };
      nodes.set(key, node);
    }
    return node;
  };

  // Spatial index of every vertex so split candidates are found locally.
  const index = new Map();
  const cellKey = (point) =>
    `${Math.floor(point[0] / INDEX_CELL_DEGREES)}:${Math.floor(point[1] / INDEX_CELL_DEGREES)}`;

  const indexNode = (node) => {
    const key = cellKey(node.point);
    if (!index.has(key)) index.set(key, []);
    index.get(key).push(node);
  };

  const nodesNear = (point) => {
    const spanLat = Math.ceil(
      (SPLIT_RADIUS_METERS / METERS_PER_DEGREE_LAT) / INDEX_CELL_DEGREES,
    );
    const spanLon = Math.ceil(
      (SPLIT_RADIUS_METERS / METERS_PER_DEGREE_LON) / INDEX_CELL_DEGREES,
    );
    const [cellLat, cellLon] = cellKey(point).split(":").map(Number);
    const found = [];
    for (let dLat = -spanLat; dLat <= spanLat; dLat += 1) {
      for (let dLon = -spanLon; dLon <= spanLon; dLon += 1) {
        const bucket = index.get(`${cellLat + dLat}:${cellLon + dLon}`);
        if (bucket) found.push(...bucket);
      }
    }
    return found;
  };

  // Pass 1: one node per distinct road vertex.
  for (const road of roads) {
    for (const point of road.coords) indexNode(nodeFor(point));
  }

  const edges = new Map();
  const edgeKey = (a, b) => (a < b ? `${a}|${b}` : `${b}|${a}`);

  const addEdge = (fromNode, toNode, roadClass, name) => {
    if (fromNode.id === toNode.id) return;
    const length = distanceMeters(fromNode.point, toNode.point);
    if (length < 0.4) return;
    const key = edgeKey(fromNode.id, toNode.id);
    const priority = CLASS_PRIORITY[roadClass] ?? 1;
    const existing = edges.get(key);
    if (existing && existing.priority >= priority) return;
    edges.set(key, {
      key,
      from: fromNode.id,
      to: toNode.id,
      length,
      roadClass,
      name,
      cost: length * (AVOIDANCE[roadClass] ?? DEFAULT_AVOIDANCE),
      priority,
    });
  };

  // Pass 2: walk each street, splitting wherever another street's node touches it.
  for (const road of roads) {
    const vertices = road.coords;
    for (let i = 1; i < vertices.length; i += 1) {
      const start = vertices[i - 1];
      const end = vertices[i];
      const startNode = nodeFor(start);
      const endNode = nodeFor(end);

      const splits = [];
      for (const candidate of nodesNear(start)) {
        if (candidate.id === startNode.id || candidate.id === endNode.id) continue;
        const projection = projectOnSegment(candidate.point, start, end);
        if (!projection) continue;
        if (projection.t <= 0.02 || projection.t >= 0.98) continue;
        if (projection.distance > SPLIT_RADIUS_METERS) continue;
        const splitNode = nodeFor(projection.point);
        if (splitNode.id === startNode.id || splitNode.id === endNode.id) continue;
        splits.push({ node: splitNode, t: projection.t, host: candidate });
      }

      splits.sort((left, right) => left.t - right.t);

      let previous = startNode;
      for (const split of splits) {
        addEdge(previous, split.node, road.class, road.name);
        // The stub from the crossing to the street that actually ends there.
        addEdge(split.node, split.host, "footway", null);
        indexNode(split.node);
        previous = split.node;
      }
      addEdge(previous, endNode, road.class, road.name);
    }
  }

  const adjacency = new Map();
  for (const edge of edges.values()) {
    if (!adjacency.has(edge.from)) adjacency.set(edge.from, []);
    if (!adjacency.has(edge.to)) adjacency.set(edge.to, []);
    adjacency.get(edge.from).push(edge);
    adjacency.get(edge.to).push(edge);
  }
  for (const list of adjacency.values()) list.sort((left, right) => left.cost - right.cost);

  return { nodes, adjacency };
}

function nearestNode(graph, point) {
  let best = null;
  let bestDistance = Infinity;
  for (const node of graph.nodes.values()) {
    if (!graph.adjacency.has(node.id)) continue;
    const distance = distanceMeters(point, node.point);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = node;
    }
  }
  return best ? { node: best, distance: bestDistance } : null;
}

/** Binary min-heap so Dijkstra is O(E log V) rather than a linear scan per node. */
function heapPush(heap, item) {
  heap.push(item);
  let index = heap.length - 1;
  while (index > 0) {
    const parent = (index - 1) >> 1;
    if (heap[parent].distance <= heap[index].distance) break;
    const swap = heap[parent];
    heap[parent] = heap[index];
    heap[index] = swap;
    index = parent;
  }
}

function heapPop(heap) {
  const top = heap[0];
  const last = heap.pop();
  if (heap.length > 0) {
    heap[0] = last;
    let index = 0;
    for (;;) {
      const left = index * 2 + 1;
      const right = left + 1;
      let smallest = index;
      if (left < heap.length && heap[left].distance < heap[smallest].distance) smallest = left;
      if (right < heap.length && heap[right].distance < heap[smallest].distance) smallest = right;
      if (smallest === index) break;
      const swap = heap[smallest];
      heap[smallest] = heap[index];
      heap[index] = swap;
      index = smallest;
    }
  }
  return top;
}

/** Dijkstra over the street graph. Returns null when no path exists. */
function shortestPath(graph, startId, goalId) {
  const distances = new Map([[startId, 0]]);
  const previous = new Map();
  const queue = [{ id: startId, distance: 0 }];

  while (queue.length > 0) {
    const current = heapPop(queue);
    // Skip entries superseded by a shorter path found since they were pushed.
    if (current.distance > (distances.get(current.id) ?? Infinity)) continue;
    if (current.id === goalId) break;

    for (const edge of graph.adjacency.get(current.id) ?? []) {
      const neighbourId = edge.from === current.id ? edge.to : edge.from;
      const candidate = current.distance + edge.cost;
      if (candidate < (distances.get(neighbourId) ?? Infinity)) {
        distances.set(neighbourId, candidate);
        previous.set(neighbourId, { node: current.id, edge });
        heapPush(queue, { id: neighbourId, distance: candidate });
      }
    }
  }

  if (startId === goalId) return [];
  if (!previous.has(goalId)) return null;

  const path = [];
  let cursor = goalId;
  while (cursor !== startId) {
    const step = previous.get(cursor);
    if (!step) return null;
    path.unshift({ node: cursor, edge: step.edge });
    cursor = step.node;
  }
  return path;
}

function buildInstructions(nodes, path) {
  const legs = path.map((step) => {
    const otherId = step.edge.from === step.node ? step.edge.to : step.edge.from;
    return {
      from: nodes.get(step.node).point,
      to: nodes.get(otherId).point,
      roadClass: step.edge.roadClass,
      name: step.edge.name,
      distance: step.edge.length,
    };
  });

  if (legs.length === 0) return [];

  const roadPhrase = (group) =>
    group.name ? group.name : CLASS_PHRASE[group.roadClass] ?? "the street";

  // Group consecutive legs that stay on the same street with a steady bearing,
  // then turn each group into one instruction carrying the distance to walk
  // after the action. Group distances therefore sum to the total route length.
  const groups = [];
  let group = {
    roadClass: legs[0].roadClass,
    name: legs[0].name,
    distance: legs[0].distance,
    bearing: bearingBetween(legs[0].from, legs[0].to),
    turn: null,
  };

  for (let index = 1; index < legs.length; index += 1) {
    const leg = legs[index];
    const bearing = bearingBetween(leg.from, leg.to);
    const delta = normalizeBearing(bearing - group.bearing + 180) - 180;
    const sameRoad =
      leg.name !== null && leg.name === group.name && leg.roadClass === group.roadClass;

    if (sameRoad && Math.abs(delta) < 25) {
      group.distance += leg.distance;
      group.bearing = bearing;
      continue;
    }

    groups.push(group);
    group = {
      roadClass: leg.roadClass,
      name: leg.name,
      distance: leg.distance,
      bearing,
      turn: turnDescription(delta),
    };
  }
  groups.push(group);

  return groups.map((entry, index) => {
    const heading = `Head ${compassOf(entry.bearing)}`;
    const text =
      index === 0
        ? entry.name
          ? `${heading} on ${entry.name}`
          : `${heading} along ${roadPhrase(entry)}`
        : entry.turn.type === "continue"
          ? `Carry on ${roadPhrase(entry)}`
          : `${entry.turn.text} onto ${roadPhrase(entry)}`;
    return {
      text,
      distance: Math.round(entry.distance),
      turn: index === 0 ? "start" : entry.turn.type,
      bearing: normalizeBearing(entry.bearing),
      kind: entry.name ? "named" : "generic",
    };
  });
}

const MAX_SNAP_METERS = 400;

// Walking directions run across the vendored street network, which is detailed
// for one neighbourhood. A place elsewhere in the city has no graph to route on,
// so say that plainly rather than implying the route is unavailable.
const OUTSIDE_GRAPH =
  "Walking directions are only mapped for the Rajajinagar neighborhood, so this place has no route yet. Every other part of the place page still works.";

/**
 * Route between two [lat, lon] points across the vendored street network.
 * Returns `{ ok: true, ... }` or `{ ok: false, reason }`.
 */
export function findWalkingRoute(graph, from, to) {
  if (!graph.adjacency.size) {
    return { ok: false, reason: "No street data is loaded for this area yet." };
  }

  const start = nearestNode(graph, from);
  const goal = nearestNode(graph, to);

  if (!start || start.distance > MAX_SNAP_METERS) {
    return { ok: false, reason: OUTSIDE_GRAPH };
  }
  if (!goal || goal.distance > MAX_SNAP_METERS) {
    return { ok: false, reason: OUTSIDE_GRAPH };
  }

  const path = shortestPath(graph, start.node.id, goal.node.id);
  if (!path) {
    return { ok: false, reason: OUTSIDE_GRAPH };
  }

  const coordinates = [
    start.node.point,
    ...path.map((step) => graph.nodes.get(step.node).point),
  ];
  const totalDistance = path.reduce((sum, step) => sum + step.edge.length, 0);

  return {
    ok: true,
    coordinates,
    distanceMeters: Math.round(totalDistance),
    durationSeconds: Math.round(totalDistance / WALKING_METERS_PER_SECOND),
    instructions: buildInstructions(graph.nodes, path),
  };
}

export function formatDistance(meters) {
  if (meters < 950) return `${meters} m`;
  if (meters < 10000) return `${(meters / 1000).toFixed(1)} km`;
  return `${Math.round(meters / 1000)} km`;
}

export function formatDuration(seconds) {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} hr ${minutes % 60} min`;
}
