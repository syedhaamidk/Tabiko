import { useEffect, useMemo, useRef, useState } from "react";
import {
  CircleMarker,
  MapContainer,
  Marker,
  Polyline,
  Popup,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { getRestaurantVisual, moneyTier, prettyTag } from "../lib/restaurantVisual";
import { foodIconSvgMarkup } from "../lib/foodIcons";
import {
  buildStreetGraph,
  findWalkingRoute,
  formatDistance,
  formatDuration,
} from "../lib/routePlanner";
import { loadMapData } from "../lib/mapData";
import { loadCityData } from "../lib/cityData";
import { clusterPoints, cullToBounds } from "../lib/clusterPoints";
import { buildCuisineLegend, cuisineColor, cuisinePresentation } from "../lib/cuisinePresentation";
import { fetchRestaurantPoints } from "../api";
import InterfaceIcon from "./InterfaceIcon";

/**
 * Tabiko draws its own basemap from vendored OpenStreetMap geometry, so there is
 * no tile provider, no API key, and no runtime network call for the map itself.
 * See scripts/build-neighborhood-map.mjs to regenerate the geometry.
 */

const THEMES = {
  sunset: {
    label: "Sunset",
    icon: "sun",
    land: "#EFE1C6",
    terrain: { fill: "#E2D8F0", stroke: "#A992CB" },
    park: { fill: "#C3EE96", stroke: "#5E9B3C" },
    water: { fill: "#8ED8EC", stroke: "#2C90B4" },
    building: { fill: "#E3CCA6", stroke: "#C0A175" },
    road: {
      casing: "#C99A5E",
      fill: "#FFFFFF",
      arterial: "#FFD98A",
      arterialCasing: "#B4712F",
      detail: "#B4915F",
    },
    text: { fill: "#8A5524" },
    landmark: { fill: "#FFFFFF", stroke: "#B07434", text: "#7A4E22" },
    city: {
      water: { fill: "#8ED8EC", stroke: "#2C90B4" },
      green: { fill: "#C3EE96", stroke: "#5E9B3C" },
      road: { casing: "#C99A5E", fill: "#FFFFFF", major: "#FFD98A" },
      label: "#7A4E22",
    },
    route: "#FF2E88",
    routeCasing: "#2A0E1E",
    routeStart: "#C6F135",
    routeEnd: "#FF2E88",
  },
  ink: {
    label: "After dark",
    icon: "moon",
    land: "#140A20",
    terrain: { fill: "#261A3E", stroke: "#40306A" },
    park: { fill: "#20502F", stroke: "#47914F" },
    water: { fill: "#113851", stroke: "#2F7CA3" },
    building: { fill: "#332654", stroke: "#4E3A78" },
    road: {
      casing: "#07030D",
      fill: "#6B57A0",
      arterial: "#FFC53D",
      arterialCasing: "#7A4E12",
      detail: "#4B3C72",
    },
    text: { fill: "#F6E6C8" },
    landmark: { fill: "#2A1B44", stroke: "#FFC53D", text: "#F0DCC0" },
    city: {
      water: { fill: "#113851", stroke: "#2F7CA3" },
      green: { fill: "#20502F", stroke: "#47914F" },
      road: { casing: "#07030D", fill: "#6B57A0", major: "#FFC53D" },
      label: "#F0DCC0",
    },
    route: "#FFC53D",
    routeCasing: "#0C0616",
    routeStart: "#C6F135",
    routeEnd: "#FF5BA8",
  },
};

const ROAD_WEIGHT = {
  motorway: 10,
  trunk: 9,
  primary: 8,
  secondary: 6.6,
  tertiary: 5.4,
  residential: 4.4,
  unclassified: 4.2,
  living_street: 3.8,
  pedestrian: 3.2,
  footway: 2.4,
  service: 3.2,
};

const ARTERIAL_CLASSES = new Set(["motorway", "trunk", "primary", "secondary", "tertiary"]);
const DETAIL_CLASSES = new Set(["pedestrian", "footway", "service"]);
const DETAIL_DASH = { pedestrian: "2 7", footway: "1 7" };

const PANES = [
  ["tabiko-city-terrain", 100],
  ["tabiko-city-roads", 150],
  ["tabiko-city-labels", 160],
  ["tabiko-terrain", 200],
  ["tabiko-buildings", 300],
  ["tabiko-road-casing", 410],
  ["tabiko-roads", 420],
  ["tabiko-road-detail", 430],
  ["tabiko-route", 440],
  ["tabiko-landmarks", 520],
  ["tabiko-labels", 640],
];

// The city overview and the street-level detail hand over to each other here, so
// both are never drawn on top of each other in the same view.
const CITY_MAX_ZOOM = 14.5;
const DETAIL_MIN_ZOOM = 14.5;

const CITY_ARTERIAL_WEIGHT = {
  motorway: 3.6,
  trunk: 3.2,
  primary: 2.4,
  secondary: 1.8,
};
const CITY_MAJOR_CLASSES = new Set(["motorway", "trunk"]);

const HOME_ZOOM = 15.5;
// Zoom 11 frames the whole metropolitan area (~53 x 40 km of vendored data).
const MIN_ZOOM = 11;
const MAX_ZOOM = 18;

// Vendored geometry is ODbL-derived, so OpenStreetMap attribution is required.
const OSM_ATTRIBUTION =
  'Map data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

const LEGEND_PLACEHOLDER = "No cuisine key yet";

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function closeRing(coordinates) {
  if (coordinates.length < 3) return null;
  const first = coordinates[0];
  const last = coordinates[coordinates.length - 1];
  if (first[0] === last[0] && first[1] === last[1]) return coordinates;
  return [...coordinates, first];
}

// Tabiko stores every coordinate as [lat, lon] to match the rest of the app and
// Leaflet's latlng order. GeoJSON requires [lon, lat], so conversion happens here.
function toGeoJsonPoint([lat, lon]) {
  return [lon, lat];
}

function toLineCollection(roads, keep) {
  return {
    type: "FeatureCollection",
    features: roads
      .filter((road) => keep(road.class))
      .map((road) => ({
        type: "Feature",
        properties: { class: road.class },
        geometry: { type: "LineString", coordinates: road.coords.map(toGeoJsonPoint) },
      })),
  };
}

function toAreaCollection(areas) {
  const features = [];
  for (const area of areas) {
    const ring = closeRing(area);
    if (!ring) continue;
    features.push({
      type: "Feature",
      properties: {},
      geometry: { type: "Polygon", coordinates: [ring.map(toGeoJsonPoint)] },
    });
  }
  return { type: "FeatureCollection", features };
}

function ensurePanes(map) {
  for (const [name, zIndex] of PANES) {
    if (!map.getPane(name)) map.createPane(name);
    map.getPane(name).style.zIndex = zIndex;
  }
}

// Pane creation must happen before any child layer mounts, otherwise Leaflet
// cannot resolve `map.getPane(...)` and Marker._initIcon throws.
function PaneSetup() {
  const map = useMap();
  useEffect(() => {
    ensurePanes(map);
  }, [map]);
  return null;
}

function createBaseLayers(theme, mapData) {
  const layers = [];

  const addArea = (areas, style, pane) => {
    if (!areas.length) return;
    layers.push(
      L.geoJSON(toAreaCollection(areas), { pane, style, interactive: false }),
    );
  };

  addArea(
    mapData.industrial,
    () => ({ fillColor: theme.terrain.fill, color: theme.terrain.stroke, weight: 1.2 }),
    "tabiko-terrain",
  );
  addArea(
    mapData.pitches,
    () => ({ fillColor: theme.park.fill, color: theme.park.stroke, weight: 1, fillOpacity: 0.55 }),
    "tabiko-terrain",
  );
  addArea(
    mapData.parks,
    () => ({ fillColor: theme.park.fill, color: theme.park.stroke, weight: 1.6, fillOpacity: 0.85 }),
    "tabiko-terrain",
  );
  addArea(
    mapData.water,
    () => ({ fillColor: theme.water.fill, color: theme.water.stroke, weight: 1.6, fillOpacity: 0.9 }),
    "tabiko-terrain",
  );

  addArea(
    mapData.buildings,
    () => ({
      fillColor: theme.building.fill,
      color: theme.building.stroke,
      weight: 0.8,
      fillOpacity: 0.95,
    }),
    "tabiko-buildings",
  );

  const isSolid = (roadClass) => !DETAIL_CLASSES.has(roadClass);

  layers.push(
    L.geoJSON(toLineCollection(mapData.roads, isSolid), {
      pane: "tabiko-road-casing",
      interactive: false,
      style: (feature) => {
        const roadClass = feature.properties.class;
        const weight = ROAD_WEIGHT[roadClass] ?? 3;
        return {
          color: ARTERIAL_CLASSES.has(roadClass) ? theme.road.arterialCasing : theme.road.casing,
          weight: weight + 3,
          opacity: 1,
          lineCap: "round",
          lineJoin: "round",
        };
      },
    }),
  );

  layers.push(
    L.geoJSON(toLineCollection(mapData.roads, isSolid), {
      pane: "tabiko-roads",
      interactive: false,
      style: (feature) => {
        const roadClass = feature.properties.class;
        return {
          color: ARTERIAL_CLASSES.has(roadClass) ? theme.road.arterial : theme.road.fill,
          weight: ROAD_WEIGHT[roadClass] ?? 3,
          opacity: 1,
          lineCap: "round",
          lineJoin: "round",
        };
      },
    }),
  );

  layers.push(
    L.geoJSON(toLineCollection(mapData.roads, (roadClass) => DETAIL_CLASSES.has(roadClass)), {
      pane: "tabiko-road-detail",
      interactive: false,
      style: (feature) => {
        const roadClass = feature.properties.class;
        return {
          color: theme.road.detail,
          weight: ROAD_WEIGHT[roadClass] ?? 2.4,
          opacity: 0.85,
          dashArray: DETAIL_DASH[roadClass] ?? null,
          lineCap: "round",
        };
      },
    }),
  );

  return layers;
}

function ZoomWatcher({ minZoom = 0, maxZoom = Infinity, children }) {
  const map = useMap();
  const [visible, setVisible] = useState(() => {
    const zoom = map.getZoom();
    return zoom >= minZoom && zoom <= maxZoom;
  });
  useMapEvents({
    zoomend: () => {
      const zoom = map.getZoom();
      setVisible(zoom >= minZoom && zoom <= maxZoom);
    },
  });
  return visible ? children : null;
}

function cityAreaCollection(areas) {
  const features = [];
  for (const area of areas) {
    const ring = closeRing(area);
    if (!ring) continue;
    features.push({
      type: "Feature",
      properties: {},
      geometry: { type: "Polygon", coordinates: [ring.map(toGeoJsonPoint)] },
    });
  }
  return { type: "FeatureCollection", features };
}

function useZoomLevel() {
  const map = useMap();
  const [zoom, setZoom] = useState(() => map.getZoom());
  useMapEvents({
    zoomend: () => setZoom(map.getZoom()),
  });
  return zoom;
}

// Locality labels are ranked by importance (0 = city … 9 = other). Showing every
// name at once buries the map, so low zooms only reveal the big ones.
function rankLimitForZoom(zoom) {
  if (zoom < 12.5) return 2;
  if (zoom < 13.4) return 3;
  if (zoom < 14.2) return 4;
  return 9;
}

/** Bengaluru's arterial skeleton, drawn while zoomed out. */
function CityBase({ theme, cityData }) {
  const map = useMap();
  const city = theme.city;
  const zoom = useZoomLevel();
  const rankLimit = rankLimitForZoom(zoom);

  useEffect(() => {
    const layers = [];

    const addArea = (areas, style, pane) => {
      if (!areas.length) return;
      layers.push(
        L.geoJSON(cityAreaCollection(areas), { pane, style, interactive: false }),
      );
    };

    addArea(
      cityData.green,
      () => ({ fillColor: city.green.fill, color: city.green.stroke, weight: 0.8, fillOpacity: 0.8 }),
      "tabiko-city-terrain",
    );
    addArea(
      cityData.water,
      () => ({ fillColor: city.water.fill, color: city.water.stroke, weight: 0.8, fillOpacity: 0.9 }),
      "tabiko-city-terrain",
    );

    const collection = {
      type: "FeatureCollection",
      features: cityData.arterials.map((road) => ({
        type: "Feature",
        properties: { class: road.class },
        geometry: { type: "LineString", coordinates: road.coords.map(toGeoJsonPoint) },
      })),
    };

    const weightOf = (roadClass) => CITY_ARTERIAL_WEIGHT[roadClass] ?? 1.6;

    layers.push(
      L.geoJSON(collection, {
        pane: "tabiko-city-roads",
        interactive: false,
        style: (feature) => ({
          color: city.road.casing,
          weight: weightOf(feature.properties.class) + 1.8,
          opacity: 1,
          lineCap: "round",
          lineJoin: "round",
        }),
      }),
      L.geoJSON(collection, {
        pane: "tabiko-city-roads",
        interactive: false,
        style: (feature) => ({
          color: CITY_MAJOR_CLASSES.has(feature.properties.class)
            ? city.road.major
            : city.road.fill,
          weight: weightOf(feature.properties.class),
          opacity: 1,
          lineCap: "round",
          lineJoin: "round",
        }),
      }),
    );

    layers.forEach((layer) => layer.addTo(map));
    return () => layers.forEach((layer) => map.removeLayer(layer));
  }, [map, city, cityData]);

  return cityData.labels
    .filter((label) => label.rank <= rankLimit)
    .map((label) => (
      <Marker
        key={`city-${label.name}`}
        position={label.at}
        interactive={false}
        pane="tabiko-city-labels"
        icon={L.divIcon({
          className: "map-city-label",
          html: `<span style="color:${city.label}">${escapeHtml(label.name)}</span>`,
          iconSize: [0, 0],
        })}
      />
    ));
}

function NeighborhoodBase({ theme, restaurants, mapData }) {
  const map = useMap();
  const themeName = Object.keys(THEMES).find((key) => THEMES[key] === theme);
  const palette = THEMES[themeName];

  useEffect(() => {
    const layers = createBaseLayers(palette, mapData);
    layers.forEach((layer) => layer.addTo(map));
    return () => layers.forEach((layer) => map.removeLayer(layer));
  }, [map, palette, mapData]);

  // Landmarks that sit on top of a Tabiko marker would double-draw, so hide them.
  const landmarks = useMemo(() => {
    const hidden = restaurants.map((restaurant) => [restaurant.latitude, restaurant.longitude]);
    return mapData.landmarks.filter((landmark) => {
      const [lat, lon] = landmark.at;
      return hidden.every(([hLat, hLon]) => Math.hypot((lat - hLat) * 111_320, (lon - hLon) * 104_000) > 70);
    });
  }, [restaurants]);

  return (
    <ZoomWatcher minZoom={15.4}>
      {landmarks.map((landmark) => (
        <CircleMarker
          key={`landmark-${landmark.name}`}
          center={landmark.at}
          radius={4}
          pane="tabiko-landmarks"
          interactive={false}
          pathOptions={{
            fillColor: palette.landmark.fill,
            color: palette.landmark.stroke,
            weight: 1.6,
            fillOpacity: 1,
          }}
        >
          <Tooltip
            permanent
            direction="right"
            offset={[6, 0]}
            className="map-landmark-label"
            opacity={1}
          >
            <span style={{ color: palette.landmark.text }}>{escapeHtml(landmark.name)}</span>
          </Tooltip>
        </CircleMarker>
      ))}
      {mapData.labels.map((road) => (
        <Marker
          key={`label-${road.name}`}
          position={road.at}
          interactive={false}
          pane="tabiko-labels"
          icon={L.divIcon({
            className: "map-road-label",
            html: `<span style="color:${palette.text.fill}">${escapeHtml(road.name)}</span>`,
            iconSize: [0, 0],
          })}
        />
      ))}
    </ZoomWatcher>
  );
}

/**
 * Auto-fit is only worth doing for a focused result set. Fitting a city-wide
 * one would yank the viewport out to the whole city on every filter change.
 */
const AUTOFIT_MAX_PLACES = 400;

function FitPointsBounds({ points }) {
  const map = useMap();

  // Deliberately keyed on a signature of the result set, not on the clustered
  // output: clusters change on every zoom, so depending on them would make this
  // re-fit, which re-zooms, which re-clusters — an endless loop.
  const fitKey = points.length
    ? `${points[0].id}:${points[points.length - 1].id}:${points.length}`
    : "empty";

  useEffect(() => {
    if (points.length === 0 || points.length > AUTOFIT_MAX_PLACES) return;
    map.fitBounds(
      L.latLngBounds(points.map((point) => [point.latitude, point.longitude])),
      { padding: [70, 70], maxZoom: 17, animate: false },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, fitKey]);

  return null;
}

function FoodMarker({ restaurant, onSelect, onDirections }) {
  const visual = getRestaurantVisual(restaurant);
  const icon = useMemo(
    () =>
      L.divIcon({
        className: "food-marker-shell",
        html: `
          <span class="food-marker__orbit" style="--marker-color:${visual.color}"></span>
          <span class="food-marker__bubble">${foodIconSvgMarkup(visual, 44, `map-${restaurant.id}`)}</span>
        `,
        iconSize: [58, 58],
        iconAnchor: [29, 29],
        popupAnchor: [0, -28],
      }),
    [visual],
  );

  return (
    <Marker position={[restaurant.latitude, restaurant.longitude]} icon={icon} title={restaurant.name}>
      <Popup className="food-popup" minWidth={240}>
        <div className="food-popup__card">
          <div
            className="food-popup__icon"
            dangerouslySetInnerHTML={{ __html: foodIconSvgMarkup(visual, 44, `popup-${restaurant.id}`) }}
          />
          <div>
            <span>{visual.label}</span>
            <strong>{restaurant.name}</strong>
            <p>
              {[prettyTag(restaurant.type_tag), moneyTier(restaurant.price_tier)]
                .filter(Boolean)
                .join(" · ")}
            </p>
            <div className="food-popup__actions">
              <button type="button" onClick={() => onSelect?.(restaurant.id)}>
                View place <InterfaceIcon name="arrow-right" size={14} />
              </button>
              <button
                type="button"
                className="is-directions"
                onClick={() => onDirections?.(restaurant)}
              >
                Directions <InterfaceIcon name="location" size={14} />
              </button>
            </div>
          </div>
        </div>
      </Popup>
    </Marker>
  );
}

// The street graph only depends on vendored data, so it is built once per
// dataset and shared by every route query.
let cachedRoads = null;
let cachedGraph = null;
function getStreetGraph(roads) {
  if (cachedRoads !== roads) {
    cachedGraph = buildStreetGraph(roads);
    cachedRoads = roads;
  }
  return cachedGraph;
}

function FitRouteBounds({ route }) {
  const map = useMap();

  useEffect(() => {
    if (!route || route.coordinates.length < 2) return;
    map.fitBounds(L.latLngBounds(route.coordinates), { padding: [60, 60], maxZoom: 17 });
  }, [map, route]);

  return null;
}

/**
 * Both vendored layers are OpenStreetMap derived, so the ODbL credit has to be
 * on screen at every zoom. Registering it here rather than in a data layer
 * keeps it visible when only the city overview is drawn.
 */
function AttributionBridge() {
  const map = useMap();
  useEffect(() => {
    map.attributionControl.addAttribution(OSM_ATTRIBUTION);
    return () => map.attributionControl.removeAttribution(OSM_ATTRIBUTION);
  }, [map]);
  return null;
}

function BoundsBridge({ bounds }) {  const map = useMap();
  useEffect(() => {
    // MapContainer only reads map options on creation, and the bounds depend on
    // data that arrives later, so they are applied imperatively.
    map.setMaxBounds(bounds ?? null);
    return () => map.setMaxBounds(null);
  }, [map, bounds]);
  return null;
}

function ClusterMarker({ cluster, theme, onExpand }) {
  const presentation = cuisinePresentation(cluster.cuisine);
  const color = cuisineColor(cluster.cuisine);
  const size = cluster.count >= 1000 ? 54 : cluster.count >= 100 ? 46 : 38;

  const icon = useMemo(
    () =>
      L.divIcon({
        className: "cluster-marker-shell",
        html: `<span class="cluster-marker" style="--cluster-size:${size}px;--cluster-color:${color};--cluster-ink:${theme.city.label}"><b>${cluster.count}</b></span>`,
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
      }),
    [size, color, theme.city.label, cluster.count],
  );

  return (
    <Marker
      position={[cluster.latitude, cluster.longitude]}
      icon={icon}
      title={`${cluster.count} places`}
      eventHandlers={{ click: () => onExpand?.(cluster) }}
    />
  );
}

/** Zoom to exactly the places inside a cluster. */
/**
 * Fetches only the places inside the visible map, padded so a small pan does not
 * need a new request.
 *
 * Without this the map asked for all 7,728 places on every filter change: 1.3 MB
 * of JSON, and 7,728 Pydantic models and serialisations on the server per reader.
 * The API already accepted a bounding box, so the fix is passing the viewport
 * through.
 *
 * The previous points stay on screen while a new box loads, so panning never
 * flashes the map empty, and the box is padded generously so a cluster just off
 * screen still carries its real count.
 */
const VIEWPORT_PADDING = 0.5;
const VIEWPORT_DEBOUNCE_MS = 400;

// Two decimals is about a kilometre, coarser than the padding, so ordinary
// panning lands on the same key and reuses the response already held.
function roundBox(box) {
  return [box.south, box.west, box.north, box.east].map((v) => v.toFixed(2)).join(",");
}

function ViewportPointLoader({ filters, onPoints, onLoading }) {
  const map = useMap();
  const filtersKey = JSON.stringify(filters ?? {});
  const lastBoxRef = useRef(null);
  const timerRef = useRef(null);
  const requestRef = useRef(0);

  useEffect(() => {
    // A new filter set invalidates whatever was fetched for the old one.
    lastBoxRef.current = null;
  }, [filtersKey]);

  useEffect(() => {
    let active = true;

    const load = () => {
      const bounds = map.getBounds();
      const latSpan = (bounds.getNorth() - bounds.getSouth()) * VIEWPORT_PADDING;
      const lonSpan = (bounds.getEast() - bounds.getWest()) * VIEWPORT_PADDING;
      const box = {
        south: bounds.getSouth() - latSpan,
        west: bounds.getWest() - lonSpan,
        north: bounds.getNorth() + latSpan,
        east: bounds.getEast() + lonSpan,
      };

      const key = roundBox(box);
      if (key === lastBoxRef.current) return;
      lastBoxRef.current = key;

      const token = requestRef.current + 1;
      requestRef.current = token;
      onLoading(true);

      fetchRestaurantPoints({
        ...(filters ?? {}),
        south: box.south,
        west: box.west,
        north: box.north,
        east: box.east,
      })
        .then((rows) => {
          // A pan during a fetch must not let a stale response win.
          if (!active || token !== requestRef.current) return;
          onPoints(rows);
          onLoading(false);
        })
        .catch(() => {
          if (!active || token !== requestRef.current) return;
          onPoints([]);
          onLoading(false);
        });
    };

    const schedule = () => {
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(load, VIEWPORT_DEBOUNCE_MS);
    };

    schedule();
    map.on("moveend", schedule);

    return () => {
      active = false;
      clearTimeout(timerRef.current);
      map.off("moveend", schedule);
    };
    // `filters` is compared by identity through filtersKey so a fresh object
    // literal on every render does not restart the fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, filtersKey, onPoints, onLoading]);

  return null;
}

function ClusterExpander({ pendingCluster }) {
  const map = useMap();
  useEffect(() => {
    if (!pendingCluster) return;
    const bounds = L.latLngBounds(pendingCluster.bounds);
    // animate:false matters here. Markers are re-created on zoomend, and an
    // animated fitBounds would still be repositioning them while React unmounts
    // the old set, which throws inside Leaflet's setPosition.
    map.fitBounds(bounds, { padding: [70, 70], maxZoom: 17, animate: false });
  }, [map, pendingCluster]);
  return null;
}

/**
 * Draws every place in the result set.
 *
 * This has to live inside MapContainer because clustering depends on the current
 * zoom and culling depends on the live viewport.
 */
function PlaceMarkers({
  points,
  theme,
  onSelect,
  onDirections,
  onExpandCluster,
  routeActive,
}) {
  const map = useMap();
  const zoom = useZoomLevel();
  const [boundsVersion, setBoundsVersion] = useState(0);

  useMapEvents({
    moveend: () => setBoundsVersion((value) => value + 1),
  });

  const clusters = useMemo(() => clusterPoints(points, zoom), [points, zoom]);
  const visible = useMemo(
    () => cullToBounds(clusters, map.getBounds()),
    // boundsVersion forces a re-read of the live bounds after a pan.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [clusters, boundsVersion],
  );

  return (
    <>
      {!routeActive && <FitPointsBounds points={points} />}
      {visible.map((cluster) =>
        cluster.kind === "cluster" ? (
          <ClusterMarker
            key={`cluster-${cluster.id}`}
            cluster={cluster}
            theme={theme}
            onExpand={onExpandCluster}
          />
        ) : (
          <FoodMarker
            key={`point-${cluster.id}`}
            restaurant={{
              id: cluster.id,
              name: cluster.name,
              latitude: cluster.latitude,
              longitude: cluster.longitude,
              cuisine_tags: cluster.cuisine,
              type_tag: cluster.typeTag,
            }}
            onSelect={onSelect}
            onDirections={onDirections}
          />
        ),
      )}
    </>
  );
}

function MapRefBridge({ onReady }) {
  const map = useMap();
  useEffect(() => {
    onReady(map);
    // Dev-only handle for automated checks. `import.meta.env.DEV` is inlined at
    // build time, so this branch is dropped from production bundles.
    if (import.meta.env.DEV) {
      window.__tabikoMap = map;
      return () => {
        if (window.__tabikoMap === map) delete window.__tabikoMap;
      };
    }
    return undefined;
  }, [map, onReady]);
  return null;
}

function RouteLine({ route, palette }) {
  if (!route) return null;

  const start = route.coordinates[0];
  const end = route.coordinates[route.coordinates.length - 1];

  return (
    <>
      <FitRouteBounds route={route} />
      <Polyline
        positions={route.coordinates}
        pane="tabiko-route"
        interactive={false}
        pathOptions={{ color: palette.routeCasing, weight: 11, lineCap: "round" }}
      />
      <Polyline
        positions={route.coordinates}
        pane="tabiko-route"
        interactive={false}
        pathOptions={{ color: palette.route, weight: 6, lineCap: "round" }}
      />
      <CircleMarker
        center={start}
        radius={7}
        pane="tabiko-route"
        interactive={false}
        pathOptions={{
          color: palette.routeCasing,
          weight: 3,
          fillColor: palette.routeStart,
          fillOpacity: 1,
        }}
      />
      <CircleMarker
        center={end}
        radius={9}
        pane="tabiko-route"
        interactive={false}
        pathOptions={{
          color: palette.routeCasing,
          weight: 3,
          fillColor: palette.routeEnd,
          fillOpacity: 1,
        }}
      />
    </>
  );
}

function DirectionsPanel({ route, error, originLabel, destinationLabel, onUseMyLocation, onClear, locating }) {
  if (!route && !error) return null;

  return (
    <div className="directions-card" role="region" aria-label="Walking directions">
      <div className="directions-card__head">
        <span className="directions-card__title">
          <InterfaceIcon name="location" size={16} /> Walking route
        </span>
        <button type="button" className="directions-card__close" onClick={onClear} aria-label="Clear directions">
          <InterfaceIcon name="check" size={14} strokeWidth={2.6} />
        </button>
      </div>

      {error && <p className="directions-card__error">{error}</p>}

      {route && (
        <>
          <div className="directions-card__endpoints">
            <span>{originLabel}</span>
            <InterfaceIcon name="arrow-right" size={13} />
            <strong>{destinationLabel}</strong>
          </div>
          <div className="directions-card__totals">
            <strong>{formatDistance(route.distanceMeters)}</strong>
            <span>about {formatDuration(route.durationSeconds)} on foot</span>
          </div>
          <ol className="directions-card__steps">
            {route.instructions.slice(0, 40).map((step, index) => (
              <li key={`${index}-${step.text}`}>
                <span className="directions-card__step-distance">{formatDistance(step.distance)}</span>
                <span className="directions-card__step-text">{step.text}</span>
              </li>
            ))}
          </ol>
        </>
      )}

      <button type="button" className="directions-card__locate" onClick={onUseMyLocation} disabled={locating}>
        <InterfaceIcon name="location" size={14} />
        {locating ? "Locating…" : "Start from my location"}
      </button>
    </div>
  );
}

export default function MapView({ restaurants, onSelect, filters = {}, cravingResults = null }) {
  const [themeName, setThemeName] = useState("sunset");
  const theme = THEMES[themeName];

  const [route, setRoute] = useState(null);
  const [routeError, setRouteError] = useState(null);
  const [routeTarget, setRouteTarget] = useState(null);
  const [origin, setOrigin] = useState(null);
  const [locating, setLocating] = useState(false);
  // This is the Leaflet map instance itself, not a ref object.
  const [mapInstance, setMapInstance] = useState(null);
  const [mapData, setMapData] = useState(null);
  const [mapDataError, setMapDataError] = useState(null);
  const [cityData, setCityData] = useState(null);
  const [cityPoints, setCityPoints] = useState([]);
  const [cravingPoints, setCravingPoints] = useState(null);
  const [pointsLoading, setPointsLoading] = useState(true);
  const [pendingCluster, setPendingCluster] = useState(null);

  useEffect(() => {
    // Points are fetched by ViewportPointLoader, which needs the live map
    // bounds and can only run inside the map container. An empty set here means
    // the loader has not delivered yet, and the loader keeps the previous set on
    // screen while a new viewport loads rather than clearing it.
    setCityPoints([]);
  }, [filters]);

  useEffect(() => {
    let active = true;
    loadMapData()
      .then((data) => {
        if (active) setMapData(data);
      })
      .catch((error) => {
        if (active) setMapDataError(error.message);
      });
    return () => {
      active = false;
    };
  }, []);

  // The city overview is optional: if it fails, the map still works at street
  // level rather than showing an error.
  useEffect(() => {
    let active = true;
    loadCityData()
      .then((data) => {
        if (active) setCityData(data);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  const homeCenter = useMemo(() => mapData?.center ?? [12.9915, 77.552], [mapData]);
  const dataBounds = useMemo(() => {
    if (!mapData) return null;
    const [south, west, north, east] = mapData.meta.bbox;
    return L.latLngBounds([south, west], [north, east]);
  }, [mapData]);

  // Panning is bounded by whichever area is actually loaded: the whole city
  // when the overview is available, otherwise just the seeded neighborhood.
  const viewBounds = useMemo(() => {
    if (cityData) {
      const [south, west, north, east] = cityData.meta.bbox;
      return L.latLngBounds([south, west], [north, east]).pad(0.04);
    }
    return dataBounds ? dataBounds.pad(0.12) : null;
  }, [cityData, dataBounds]);

  const routeFrom = (fromPoint, fromLabel, target) => {
    if (!mapData) return;
    const destination = [target.latitude, target.longitude];
    const result = findWalkingRoute(getStreetGraph(mapData.roads), fromPoint, destination);
    setRouteTarget(target);
    if (result.ok) {
      setRoute(result);
      setRouteError(null);
    } else {
      setRoute(null);
      setRouteError(result.reason);
    }
    setOrigin({ point: fromPoint, label: fromLabel });
  };

  /**
   * Marker source.
   *
   * The map draws every place in the filtered city set from the lightweight
   * points endpoint, not the rich records the cards page in. Craving results
   * already arrive as full objects, so they are converted inline instead.
   */
  const points = cravingPoints ?? cityPoints;
  const legend = useMemo(() => buildCuisineLegend(points), [points]);

  // Craving results already arrive as full records, so reuse them directly.
  useEffect(() => {
    if (cravingResults === null) {
      setCravingPoints(null);
      return;
    }
    setCravingPoints(
      cravingResults.map((restaurant) => ({
        id: restaurant.id,
        name: restaurant.name,
        latitude: restaurant.latitude,
        longitude: restaurant.longitude,
        cuisine_tags: restaurant.cuisine_tags,
        type_tag: restaurant.type_tag,
      })),
    );
  }, [cravingResults]);

  const handleDirections = (restaurant) => {
    // Default the walk to start from the middle of the current view, which needs
    // no permission prompt and works before the user shares a location.
    mapInstance?.closePopup();
    const center = mapInstance?.getCenter();
    const startPoint = center ? [center.lat, center.lng] : homeCenter;
    routeFrom(startPoint, "Map centre", restaurant);
  };

  const handleUseMyLocation = () => {
    if (!navigator.geolocation || !routeTarget || !mapData) {
      setRouteError("This browser cannot share a location. Directions still start from the map centre.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocating(false);
        routeFrom([position.coords.latitude, position.coords.longitude], "My location", routeTarget);
      },
      () => {
        setLocating(false);
        setRouteError("Location permission was declined, so the walk still starts from the map centre.");
      },
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 },
    );
  };

  const clearDirections = () => {
    setRoute(null);
    setRouteError(null);
    setRouteTarget(null);
    setOrigin(null);
  };

  // A route to a place that has been filtered away should not linger. This has
  // to test against the full filtered result set (points), not the cards: the
  // card list is paged, so most destinations are not loaded in it yet and this
  // would clear the route the moment it was created.
  useEffect(() => {
    if (!routeTarget) return;
    if (points.some((point) => point.id === routeTarget.id)) return;
    clearDirections();
  }, [points, routeTarget]);

  return (
    <section className="map-section" aria-labelledby="map-heading">
      <div className={`map-shell map-shell--${themeName}`}>
        <div className="map-shell__header">
          <div className="map-shell__title">
            <span className="section-kicker section-kicker--light">Flavor radar</span>
            <h2 id="map-heading">Explore the neighborhood table</h2>
          </div>

          <div className="map-shell__controls">
            <div className="map-style-toggle" role="group" aria-label="Map theme">
              {Object.entries(THEMES).map(([key, value]) => (
                <button
                  key={key}
                  type="button"
                  className={themeName === key ? "is-active" : ""}
                  onClick={() => setThemeName(key)}
                  aria-pressed={themeName === key}
                >
                  <InterfaceIcon name={value.icon} size={16} />
                  {value.label}
                </button>
              ))}
            </div>
            <div className="map-legend" aria-label="Cuisine key">
              <span className="map-legend__total">
                <InterfaceIcon name="pin" size={16} />
                {points.length} {points.length === 1 ? "place" : "places"}
              </span>
              {legend.map((group) => (
                <span className="map-legend__item" key={group.key}>
                  <i className="map-legend__swatch" style={{ "--legend-color": group.color }} />
                  <InterfaceIcon name={group.icon} size={15} />
                  {group.label}
                  <b>{group.count}</b>
                </span>
              ))}
              {legend.length === 0 && (
                <span className="map-legend__empty">{LEGEND_PLACEHOLDER}</span>
              )}
            </div>
          </div>
        </div>

        <div className="map-canvas">
          <MapContainer
            center={homeCenter}
            zoom={HOME_ZOOM}
            minZoom={MIN_ZOOM}
            maxZoom={MAX_ZOOM}
            scrollWheelZoom
            zoomControl
            className="food-map"
          >
            <PaneSetup />
            <MapRefBridge onReady={setMapInstance} />
            <AttributionBridge />
            <BoundsBridge bounds={viewBounds} />
            {cityData && (
              <ZoomWatcher maxZoom={CITY_MAX_ZOOM}>
                <CityBase theme={theme} cityData={cityData} />
              </ZoomWatcher>
            )}
            {mapData && (
              <ZoomWatcher minZoom={DETAIL_MIN_ZOOM}>
                <NeighborhoodBase theme={theme} restaurants={restaurants} mapData={mapData} />
              </ZoomWatcher>
            )}
            <RouteLine route={route} palette={theme} />
            <ClusterExpander pendingCluster={pendingCluster} />
            <ViewportPointLoader
              filters={filters}
              onPoints={setCityPoints}
              onLoading={setPointsLoading}
            />
            {pointsLoading && <div className="map-loading">Radar sweeping the city…</div>}
            <PlaceMarkers
              points={points}
              theme={theme}
              onSelect={onSelect}
              onDirections={handleDirections}
              onExpandCluster={setPendingCluster}
              routeActive={Boolean(route)}
            />
          </MapContainer>
          <div className="map-canvas__grain" aria-hidden="true" />
          {mapDataError && (
            <div className="map-empty" role="alert">
              Base map could not be loaded: {mapDataError}
            </div>
          )}
          <DirectionsPanel
            route={route}
            error={routeError}
            originLabel={origin?.label ?? "Map centre"}
            destinationLabel={routeTarget?.name ?? "Destination"}
            onUseMyLocation={handleUseMyLocation}
            onClear={clearDirections}
            locating={locating}
          />
          {restaurants.length === 0 && (
            <div className="map-empty">Radar found no flavor — loosen the filters.</div>
          )}
          <div className="map-stamp" aria-hidden="true">
            <span>Tabiko radar</span>
            <strong>{points.length} live spots</strong>
          </div>
        </div>
      </div>
    </section>
  );
}
