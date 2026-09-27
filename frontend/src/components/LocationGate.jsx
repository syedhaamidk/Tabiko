import InterfaceIcon from "./InterfaceIcon";
import { LOCATION_STATUS } from "../lib/useUserLocation";

/**
 * Location gate for nearby discovery.
 *
 * The card list is location-first, so it stays hidden until the browser reports
 * a granted geolocation permission. A first-time visitor is in the same state as
 * someone who declined: no cards, and an explicit way to opt in. The position
 * itself is owned by useUserLocation in App, because the same coordinates also
 * drive distance sorting and the radius filter; this component only decides
 * whether the cards are allowed to appear.
 *
 * The map is deliberately not gated, so browsing the whole city still works
 * without sharing a location.
 */

export default function LocationGate({ status, locating, error, onRequest, children, onBrowseMap }) {
  if (status === LOCATION_STATUS.granted) return children;

  if (status === LOCATION_STATUS.checking) {
    return (
      <section className="location-gate" aria-busy="true" aria-live="polite">
        <p className="location-gate__hint">Checking whether nearby places can be shown…</p>
      </section>
    );
  }

  const denied = status === LOCATION_STATUS.denied;
  const unavailable = status === LOCATION_STATUS.unavailable;

  return (
    <section className="location-gate" aria-live="polite">
      <span className="location-gate__icon">
        <InterfaceIcon name="location" size={34} />
      </span>
      <div>
        <span className="section-kicker">Location off</span>
        <h2>Cards are on hold</h2>
        <p>
          {unavailable
            ? "This browser will not share a location, so nearby cards stay hidden. The food map still works."
            : denied
              ? "You turned location off, so nearby cards stay hidden. The food map still works."
              : "Turn on location to see cards for the places around you right now, sorted nearest first. Nothing is stored or sent anywhere."}
        </p>
        {!unavailable && (
          <button
            type="button"
            className="location-gate__button"
            onClick={onRequest}
            disabled={locating}
          >
            <InterfaceIcon name="location" size={16} />
            {locating ? "Asking your browser…" : "Turn on location"}
          </button>
        )}
        {onBrowseMap && (
          <button type="button" className="location-gate__alt" onClick={onBrowseMap}>
            <InterfaceIcon name="map-style" size={16} />
            Explore the food map instead
          </button>
        )}
        <p className="location-gate__note">
          The food map is always open, so you can still browse every place.
        </p>
        {error && <p className="location-gate__error">{error}</p>}
      </div>
    </section>
  );
}
