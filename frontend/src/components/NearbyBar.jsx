import InterfaceIcon from "./InterfaceIcon";
import { LOCATION_STATUS } from "../lib/useUserLocation";

/**
 * Proximity controls: how far to look, and how to order the result.
 *
 * The radius is a real filter on the API, not a client-side trim, so the cards
 * and the map always agree about what is in range. It is opt-in: "Anywhere"
 * stays the default, because the whole city is the point of having loaded it,
 * and only a reader who asks for a radius should lose the rest.
 *
 * Distance ordering needs a position, so it is offered only once the browser has
 * given one. Asking for it is what triggers the permission prompt, from a click
 * rather than on page load.
 */

const RADII = [
  { value: "", label: "Anywhere" },
  { value: 500, label: "500 m" },
  { value: 1000, label: "1 km" },
  { value: 2000, label: "2 km" },
  { value: 5000, label: "5 km" },
];

const SORTS = [
  { value: "distance", label: "Nearest first", icon: "walk" },
  { value: "name", label: "A to Z", icon: "layers" },
];

export default function NearbyBar({
  radius,
  onRadiusChange,
  sort,
  onSortChange,
  location,
  onRequestLocation,
  onRefreshLocation,
  disabled,
}) {
  const { granted, coords, locating, status } = location;
  // Distance ordering is meaningless without a fix, so fall back rather than
  // let the control sit there promising something it cannot deliver.
  const canSortByDistance = granted && Boolean(coords);
  const effectiveSort = canSortByDistance ? sort : "name";

  const off = disabled || !granted;

  return (
    <section className="nearby-shell" aria-label="Nearby controls">
      <div className="nearby-shell__group">
        <span className="nearby-shell__label" id="radius-label">
          <InterfaceIcon name="location" size={15} />
          Within
        </span>
        <div className="nearby-chips" role="group" aria-labelledby="radius-label">
          {RADII.map((option) => {
            const selected = radius === option.value;
            return (
              <button
                key={option.label}
                type="button"
                className={`nearby-chip${selected ? " is-active" : ""}`}
                aria-pressed={selected}
                disabled={off}
                onClick={() => onRadiusChange(option.value)}
              >
                {option.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="nearby-shell__group">
        <span className="nearby-shell__label" id="sort-label">
          <InterfaceIcon name="layers" size={15} />
          Order
        </span>
        <div className="nearby-chips" role="group" aria-labelledby="sort-label">
          {SORTS.map((option) => {
            const unavailable = option.value === "distance" && !canSortByDistance;
            const selected = effectiveSort === option.value;
            return (
              <button
                key={option.value}
                type="button"
                className={`nearby-chip${selected ? " is-active" : ""}`}
                aria-pressed={selected}
                disabled={disabled || unavailable}
                title={
                  unavailable
                    ? "Turn on location to sort by distance"
                    : undefined
                }
                onClick={() => onSortChange(option.value)}
              >
                <InterfaceIcon name={option.icon} size={14} />
                {option.label}
              </button>
            );
          })}
        </div>
        {granted && (
          <button
            type="button"
            className="nearby-refresh"
            onClick={onRefreshLocation}
            disabled={disabled || locating}
          >
            <InterfaceIcon name="location" size={14} />
            {locating ? "Locating…" : "Update my location"}
          </button>
        )}
      </div>

      {!granted && !disabled && (
        <p className="nearby-shell__note">
          {status === LOCATION_STATUS.unavailable
            ? "This browser will not share a location, so results are listed A to Z."
            : status === LOCATION_STATUS.denied
              ? "Location is off, so results are listed A to Z. Turn it on to sort by distance and filter by radius."
              : "Turn on location to sort places by distance and filter by radius."}
          {status !== LOCATION_STATUS.unavailable && (
            <>
              {" "}
              <button type="button" className="nearby-shell__link" onClick={onRequestLocation}>
                Turn on location
              </button>
            </>
          )}
        </p>
      )}
      {granted && !coords && !locating && (
        <p className="nearby-shell__note">
          Could not read your position, so results are listed A to Z. The food map still
          works.
        </p>
      )}
    </section>
  );
}
