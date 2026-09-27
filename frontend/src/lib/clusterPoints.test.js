import { describe, expect, it } from "vitest";
import { clusterPoints, cullToBounds } from "./clusterPoints";

/**
 * Grid clustering decides what the map draws at every zoom, so the two things
 * worth pinning down are that no place is ever lost and that a cluster's count
 * always equals the number of places inside it.
 */

// Two degrees wide, which is roughly greater Bengaluru.
const boundsFor = (count, startLat = 12.75) =>
  Array.from({ length: count }, (_, index) => ({
    id: index + 1,
    name: `Place ${index + 1}`,
    latitude: startLat + (index % 100) / 1000,
    longitude: 77.45 + Math.floor(index / 100) / 1000,
    cuisine_tags: "Biryani",
    type_tag: "family_restaurant",
  }));

const totalOf = (clusters) =>
  clusters.reduce((sum, cluster) => sum + (cluster.kind === "cluster" ? cluster.count : 1), 0);

describe("clusterPoints", () => {
  it("keeps every place at every zoom", () => {
    const points = boundsFor(2000);

    for (const zoom of [11, 13, 15, 16, 17, 20]) {
      expect(totalOf(clusterPoints(points, zoom)), `zoom ${zoom}`).toBe(2000);
    }
  });

  it("draws individual pins at the single-place zoom and above", () => {
    const points = boundsFor(500);

    const atSixteen = clusterPoints(points, 16);
    expect(atSixteen.every((item) => item.kind === "point")).toBe(true);
    expect(atSixteen).toHaveLength(500);
  });

  it("folds places into clusters below the single-place zoom", () => {
    const points = boundsFor(2000);

    const clusters = clusterPoints(points, 11);
    expect(clusters.length).toBeLessThan(2000);
    expect(clusters.every((item) => item.kind === "cluster")).toBe(true);
  });

  it("shrinks clusters as the reader zooms in", () => {
    const points = boundsFor(2000);

    const coarse = clusterPoints(points, 11).length;
    const fine = clusterPoints(points, 15).length;
    expect(fine).toBeGreaterThan(coarse);
  });

  it("sorts largest clusters first so the biggest bubbles are never culled", () => {
    const counts = clusterPoints(boundsFor(2000), 12).map((c) => c.count);
    expect(counts).toEqual([...counts].sort((a, b) => b - a));
  });

  it("gives every cluster a bounding box that contains its members", () => {
    const points = boundsFor(800);
    const clusters = clusterPoints(points, 14).filter((c) => c.kind === "cluster");

    for (const cluster of clusters) {
      const [[south, west], [north, east]] = cluster.bounds;
      expect(south).toBeLessThanOrEqual(cluster.latitude);
      expect(north).toBeGreaterThanOrEqual(cluster.latitude);
      expect(west).toBeLessThanOrEqual(cluster.longitude);
      expect(east).toBeGreaterThanOrEqual(cluster.longitude);
    }
  });

  it("carries the dominant cuisine so a bubble is coloured like its members", () => {
    const points = [
      ...Array.from({ length: 5 }, (_, i) => ({
        id: i + 1,
        name: `Biryani ${i}`,
        latitude: 12.99,
        longitude: 77.55,
        cuisine_tags: "Biryani",
        type_tag: "family_restaurant",
      })),
      {
        id: 99,
        name: "One Pizza",
        latitude: 12.99,
        longitude: 77.55,
        cuisine_tags: "Italian",
        type_tag: "family_restaurant",
      },
    ];

    const [largest] = clusterPoints(points, 12);
    expect(largest.count).toBe(6);
    expect(largest.cuisine).toBe("Biryani");
  });

  it("tolerates places with no cuisine at all", () => {
    const points = [
      { id: 1, name: "No Cuisine", latitude: 12.99, longitude: 77.55, type_tag: "unclassified" },
    ];

    const clusters = clusterPoints(points, 12);
    expect(totalOf(clusters)).toBe(1);
    expect(clusters[0].cuisine).toBeNull();
  });

  it("reads only the first tag of a multi-tag cuisine", () => {
    const points = [
      {
        id: 1,
        name: "Both",
        latitude: 12.99,
        longitude: 77.55,
        cuisine_tags: "Biryani, Multi-cuisine",
        type_tag: "family_restaurant",
      },
    ];

    expect(clusterPoints(points, 12)[0].cuisine).toBe("Biryani");
  });

  it("returns nothing for an empty result set", () => {
    expect(clusterPoints([], 13)).toEqual([]);
  });

  it("never returns a count of zero for a cluster", () => {
    for (const cluster of clusterPoints(boundsFor(1500), 13)) {
      expect(cluster.count).toBeGreaterThan(0);
    }
  });
});

describe("cullToBounds", () => {
  const bounds = {
    getSouth: () => 12.9,
    getWest: () => 77.5,
    getNorth: () => 13.0,
    getEast: () => 77.6,
  };

  it("drops what is outside the padded view", () => {
    const clusters = [
      { latitude: 12.95, longitude: 77.55 },
      { latitude: 13.5, longitude: 77.55 },
    ];

    expect(cullToBounds(clusters, bounds)).toHaveLength(1);
  });

  it("keeps everything when the bounds are not known yet", () => {
    const clusters = [{ latitude: 99, longitude: 99 }];
    expect(cullToBounds(clusters, null)).toBe(clusters);
  });
});
