import BrandMark from "./BrandMark";
import InterfaceIcon from "./InterfaceIcon";
import RestaurantCard from "./RestaurantCard";

export default function RestaurantList({
  restaurants,
  status,
  onSelect,
  cravingMode = false,
  hasMore = false,
  loadingMore = false,
  totalCount = null,
  onLoadMore,
  favorites = null,
  saveNotice = null,
  savedMode = false,
}) {
  if (status === "loading") {
    return (
      <div className="loading-state" role="status">
        <span className="loading-plate" aria-hidden="true">
          <BrandMark size={54} />
        </span>
        <strong>Rolling through the good stuff…</strong>
        <span>Scanning the neighborhood for flavor.</span>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="error-state" role="alert">
        <InterfaceIcon name="location" size={30} />
        <strong>The flavor map went quiet.</strong>
        <span>Check that the API is running on port 8010, then refresh.</span>
      </div>
    );
  }

  if (restaurants.length === 0) {
    if (savedMode) {
      return (
        <div className="empty-state">
          <InterfaceIcon name="bookmark" size={30} />
          <strong>No saved places yet.</strong>
          <span>Tap the bookmark on any card to keep it here for later.</span>
        </div>
      );
    }
    return (
      <div className="empty-state">
        <InterfaceIcon name="search" size={30} />
        <strong>Nothing on the table matches that craving.</strong>
        <span>Loosen a filter or let the radar scan again.</span>
      </div>
    );
  }

  return (
    <section className="results-section" aria-labelledby="results-heading">
      <div className="results-heading">
        <div>
          <span className="section-kicker">
            {savedMode ? "Your shortlist" : cravingMode ? "Radar hits" : "Fresh intel"}
          </span>
          <h2 id="results-heading">
            {savedMode
              ? "Places you kept."
              : cravingMode
                ? "Your flavor shortlist"
                : "Pick your next personality."}
          </h2>
        </div>
        <span className="results-count">
          {totalCount != null && totalCount > restaurants.length
            ? `${restaurants.length}+`
            : restaurants.length}{" "}
          {restaurants.length === 1 ? "spot" : "spots"}
        </span>
      </div>

      <div className="restaurant-grid">
        {restaurants.map((restaurant) => (
          <RestaurantCard
            key={restaurant.id}
            restaurant={restaurant}
            onSelect={onSelect}
            saved={favorites ? favorites.isSaved(restaurant.id) : false}
            saving={favorites ? favorites.isPending(restaurant.id) : false}
            onToggleSave={favorites ? favorites.requestToggle : undefined}
          />
        ))}
      </div>

      {saveNotice && (
        <p className="save-notice" role="status">
          <InterfaceIcon name="bookmark" size={15} />
          {saveNotice}
        </p>
      )}

      {onLoadMore && hasMore && (
        <div className="load-more">
          <button type="button" onClick={onLoadMore} disabled={loadingMore}>
            <InterfaceIcon name="layers" size={16} />
            {loadingMore ? "Pulling more plates…" : "Show more places"}
          </button>
          <span>Showing {restaurants.length} loaded so far</span>
        </div>
      )}

      <p className="data-attribution">
        <InterfaceIcon name="pin" size={14} /> Place intel from{" "}
        <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
          OpenStreetMap
        </a>{" "}
        contributors
      </p>
    </section>
  );
}
