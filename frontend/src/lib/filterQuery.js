/**
 * Building the request the cards and the map both send.
 *
 * This exists as its own module because of a bug it prevents: the map once asked
 * for `sort=distance` with no origin, the API rejected it with a 422, and the map
 * rendered blank with no visible error. The rule is that one object describes the
 * query for both surfaces, and that a distance order or a radius is never sent
 * without a position to justify it.
 */

export const EMPTY_FILTERS = {
  search: "",
  cuisine: "",
  type_tag: "",
  dietary: "",
  good_for: "",
  accessibility: "",
  radius_m: "",
  sort: "name",
};

/**
 * @param filters the reader's choices
 * @param coords  the browser's position, or null
 * @param offset  page offset
 */
export function buildQuery(filters, coords, offset = 0, limit = 100) {
  // Without a position there is nothing to measure from, so a radius could not be
  // honoured and a distance order would be meaningless. Drop both rather than
  // send a request the API would reject.
  const source = coords ? filters : { ...filters, radius_m: "", sort: "name" };

  const params = Object.fromEntries(
    Object.entries(source).filter(([, value]) => value !== "" && value != null),
  );
  if (coords) {
    params.origin_lat = coords.lat;
    params.origin_lon = coords.lon;
  }
  return { ...params, limit, offset };
}

/** True when the request would need a position the reader has not granted. */
export function needsLocation(filters, coords) {
  return !coords && (Boolean(filters.radius_m) || filters.sort === "distance");
}
