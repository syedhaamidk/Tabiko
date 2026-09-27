import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// Leaflet is a browser-only library that reaches for real layout on import, and
// its own module graph is not what these tests are about. Components that mount
// a map get this stub instead, which records the imperative calls they make.
vi.mock("leaflet", () => {
  const layer = () => ({
    addTo: () => layer(),
    remove: () => {},
    on: () => layer(),
    off: () => {},
    bindTooltip: () => layer(),
    setStyle: () => {},
    bringToFront: () => {},
  });
  const map = () => {
    const instance = {
      getZoom: () => 13,
      getCenter: () => ({ lat: 12.9716, lng: 77.5946 }),
      getBounds: () => ({
        getSouth: () => 12.9,
        getWest: () => 77.5,
        getNorth: () => 13.05,
        getEast: () => 77.7,
      }),
      setView: () => instance,
      fitBounds: () => instance,
      setMaxBounds: () => instance,
      remove: () => {},
      on: () => instance,
      off: () => instance,
      invalidateSize: () => {},
      addLayer: () => instance,
      removeLayer: () => instance,
      eachLayer: () => {},
    };
    return instance;
  };
  return {
    __esModule: true,
    default: {
      map,
      tileLayer: layer,
      circleMarker: () => ({ ...layer(), addTo: () => {}, getLatLng: () => ({ lat: 0, lng: 0 }) }),
      marker: () => ({ ...layer(), setLatLng: () => {} }),
      polyline: () => ({ ...layer(), setLatLngs: () => {}, getLatLngs: () => [] }),
      polygon: () => layer(),
      rectangle: () => layer(),
      latLngBounds: (corners) => ({
        getSouth: () => corners?.[0]?.[0] ?? 0,
        getWest: () => corners?.[0]?.[1] ?? 0,
        getNorth: () => corners?.[1]?.[0] ?? 0,
        getEast: () => corners?.[1]?.[1] ?? 0,
      }),
      divIcon: (options) => ({ options }),
      point: (lat, lng) => ({ lat, lng }),
      Control: { attribution: () => ({ addTo: () => {} }) },
      DomEvent: { off: () => {} },
      layers: { control: () => ({ addTo: () => {} }) },
    },
  };
});
