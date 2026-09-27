import { describe, expect, it } from "vitest";
import { buildQuery, EMPTY_FILTERS, needsLocation } from "./filterQuery";

/**
 * The class of bug this guards against is silent: the map once requested
 * `sort=distance` with no origin, the API answered 422, and the map rendered
 * blank with nothing in the console pointing at the cause.
 */

describe("buildQuery", () => {
  it("omits every unset filter", () => {
    // `sort: "name"` is a value the API accepts, so it is sent; what matters is
    // that nothing empty reaches the wire.
    expect(buildQuery(EMPTY_FILTERS, null)).toEqual({
      sort: "name",
      limit: 100,
      offset: 0,
    });
  });

  it("sends only the filters the reader set", () => {
    const query = buildQuery(
      { ...EMPTY_FILTERS, cuisine: "Biryani", dietary: "veg" },
      null,
    );
    expect(query).toEqual({
      cuisine: "Biryani",
      dietary: "veg",
      sort: "name",
      limit: 100,
      offset: 0,
    });
  });

  it("sends an origin only when there is one", () => {
    expect(buildQuery(EMPTY_FILTERS, { lat: 12.9915, lon: 77.552 })).toMatchObject({
      origin_lat: 12.9915,
      origin_lon: 77.552,
    });
    expect(buildQuery(EMPTY_FILTERS, null).origin_lat).toBeUndefined();
  });

  it("never sends a radius or a distance order without a position", () => {
    // The 422 that blanked the map: a distance order the API cannot satisfy.
    const query = buildQuery(
      { ...EMPTY_FILTERS, radius_m: 2000, sort: "distance" },
      null,
    );
    expect(query.radius_m).toBeUndefined();
    expect(query.sort).not.toBe("distance");
    expect(query.origin_lat).toBeUndefined();
  });

  it("never sends a distance order without a position", () => {
    expect(buildQuery({ ...EMPTY_FILTERS, sort: "distance" }, null).sort).not.toBe(
      "distance",
    );
  });

  it("keeps a radius and a distance order once a position exists", () => {
    const query = buildQuery(
      { ...EMPTY_FILTERS, radius_m: 2000, sort: "distance" },
      { lat: 12.9915, lon: 77.552 },
    );
    expect(query).toMatchObject({
      radius_m: 2000,
      sort: "distance",
      origin_lat: 12.9915,
      origin_lon: 77.552,
    });
  });

  it("keeps alphabetical order when the reader chose it, position or not", () => {
    expect(
      buildQuery({ ...EMPTY_FILTERS, sort: "name" }, { lat: 12.99, lon: 77.55 }).sort,
    ).toBe("name");
  });

  it("passes the page window through", () => {
    expect(buildQuery(EMPTY_FILTERS, null, 200, 50)).toMatchObject({
      offset: 200,
      limit: 50,
    });
  });

  it("keeps a zero radius rather than treating it as unset", () => {
    // 0 is falsy. Dropping it would silently widen the search instead of
    // returning nothing.
    const query = buildQuery(
      { ...EMPTY_FILTERS, radius_m: 0 },
      { lat: 12.99, lon: 77.55 },
    );
    expect(query.radius_m).toBe(0);
  });

  it("carries the search phrase and the access filter through", () => {
    const query = buildQuery(
      { ...EMPTY_FILTERS, search: "biryani", accessibility: "wheelchair_accessible" },
      null,
    );
    expect(query.search).toBe("biryani");
    expect(query.accessibility).toBe("wheelchair_accessible");
  });

  it("drops a null but keeps a zero", () => {
    const query = buildQuery({ ...EMPTY_FILTERS, cuisine: null, radius_m: 0 }, null);
    expect(query).not.toHaveProperty("cuisine");
  });
});

describe("needsLocation", () => {
  it("is false for a plain browse", () => {
    expect(needsLocation(EMPTY_FILTERS, null)).toBe(false);
  });

  it("is true when a radius is asked for without a position", () => {
    expect(needsLocation({ ...EMPTY_FILTERS, radius_m: 500 }, null)).toBe(true);
  });

  it("is true when distance order is asked for without a position", () => {
    expect(needsLocation({ ...EMPTY_FILTERS, sort: "distance" }, null)).toBe(true);
  });

  it("is false once a position exists", () => {
    expect(
      needsLocation(
        { ...EMPTY_FILTERS, radius_m: 500, sort: "distance" },
        { lat: 1, lon: 1 },
      ),
    ).toBe(false);
  });
});
