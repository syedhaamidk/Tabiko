import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchStats, listFavoritePlaces, listRestaurants } from "./api";
import RestaurantList from "./components/RestaurantList";
import RestaurantDetail from "./components/RestaurantDetail";
import FilterBar from "./components/FilterBar";
import PlaceSearch from "./components/PlaceSearch";
import NearbyBar from "./components/NearbyBar";
import CravingSearchBar from "./components/CravingSearchBar";
import MapView from "./components/MapView";
import FriendsFeed from "./components/FriendsFeed";
import InstallButton from "./components/InstallButton";
import AuthBar from "./components/AuthBar";
import BrandMark from "./components/BrandMark";
import InterfaceIcon from "./components/InterfaceIcon";
import LocationGate from "./components/LocationGate";
import {
  FestivalConfetti,
  FestivalMarquee,
  HeroCollage,
} from "./components/FestivalDecor";
import useUserLocation from "./lib/useUserLocation";
import useFavorites from "./lib/useFavorites";
import { buildQuery, EMPTY_FILTERS } from "./lib/filterQuery";
import { ThemeProvider } from "./ThemeContext";
import { AuthProvider, useAuth } from "./AuthContext";
import "./styles/global.css";

// Keys here are the API's own query parameter names, so the object can be handed
// straight to both /restaurants and /restaurants/points. That is deliberate: the
// cards and the map are driven by one object, so they cannot drift apart about
// what "biryani within 2 km" means.
const INITIAL_FILTERS = EMPTY_FILTERS;

// The API caps a page at 100. Cards fetch one page at a time and reveal 48 at a
// time, so a city-wide result set costs a single request until asked for more.
// The map is unaffected: it reads the lightweight points endpoint.
const PAGE_SIZE = 100;
const VISIBLE_STEP = 48;

function MainApp() {
  const { loading: authLoading, user: authUser } = useAuth();
  const [selectedId, setSelectedId] = useState(null);
  const [filters, setFilters] = useState(INITIAL_FILTERS);
  const [restaurants, setRestaurants] = useState([]);
  const [status, setStatus] = useState("loading");
  const [cravingResults, setCravingResults] = useState(null);
  const [viewMode, setViewMode] = useState(() =>
    // The manifest's "Food map" shortcut links here, so honour it on load
    // rather than shipping a shortcut that lands on the card list.
    new URLSearchParams(window.location.search).get("view") === "map" ? "map" : "grid",
  );
  const [visibleCount, setVisibleCount] = useState(VISIBLE_STEP);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [totalCount, setTotalCount] = useState(null);
  const [stats, setStats] = useState(null);
  const [savedOnly, setSavedOnly] = useState(false);
  // The Friends feed is a separate view from the map and the grid, not a filter
  // on either: it is a list of reviews rather than a list of places, so it does
  // not belong in the same `viewMode` toggle.
  const [showingFriends, setShowingFriends] = useState(false);
  const authSignedIn = Boolean(authUser);
  const [savedPlaces, setSavedPlaces] = useState(null);
  const [savedStatus, setSavedStatus] = useState("idle");
  const [savedRefresh, setSavedRefresh] = useState(0);
  const [saveNotice, setSaveNotice] = useState(null);
  const location = useUserLocation();
  const favorites = useFavorites();
  // A reader who picks an order has made a choice; only auto-select nearest on
  // the transition into having a position, and never over a deliberate pick.
  const sortChosen = useRef(false);

  // The browser's position is not something the reader typed, so it is folded in
  // here instead of being written into the filter object the controls edit. The
  // same object feeds both the cards and the map, so neither can ask the API a
  // question the other one is not also asking.
  const coords = location.coords;
  const proximity = useMemo(
    () =>
      coords
        ? { ...filters, origin_lat: coords.lat, origin_lon: coords.lon }
        : { ...filters, radius_m: "", sort: "name" },
    [coords, filters],
  );

  // A food app that can measure distance should use it. Switch to nearest-first
  // the moment a position arrives, but respect an order the reader chose.
  useEffect(() => {
    if (!coords) return;
    setFilters((previous) =>
      previous.sort === "distance" || sortChosen.current
        ? previous
        : { ...previous, sort: "distance" },
    );
  }, [coords]);

  const chooseSort = useCallback((sort) => {
    sortChosen.current = true;
    setFilters((previous) => ({ ...previous, sort }));
  }, []);

  // Saving needs an account, so a signed-out tap says so rather than failing
  // silently against a 401 the reader cannot see.
  const requestToggle = useCallback(
    async (id) => {
      if (!favorites.signedIn) {
        setSaveNotice("Sign in to save places for later.");
        return false;
      }
      setSaveNotice(null);
      const ok = await favorites.toggle(id);
      if (!ok) {
        setSaveNotice("Could not update your saved places. Try again.");
      } else if (savedOnly) {
        // Keep the shortlist view honest without refetching on every toggle
        // while the reader is browsing the whole city.
        setSavedRefresh((value) => value + 1);
      }
      return ok;
    },
    [favorites, savedOnly],
  );

  // The shortlist is its own list, not a filter over the paged city results:
  // a saved place is often nowhere near the page that happens to be loaded.
  useEffect(() => {
    if (!savedOnly || !favorites.signedIn) {
      setSavedPlaces(null);
      setSavedStatus("idle");
      return;
    }
    let active = true;
    setSavedStatus("loading");
    listFavoritePlaces()
      .then((rows) => {
        if (!active) return;
        setSavedPlaces(rows);
        setSavedStatus("ready");
      })
      .catch(() => active && setSavedStatus("error"));
    return () => {
      active = false;
    };
  }, [savedOnly, favorites.signedIn, savedRefresh]);

  useEffect(() => {
    let active = true;
    fetchStats()
      .then((value) => active && setStats(value))
      .catch(() => {
        // The hero falls back to its own wording, so a failed stat call is not
        // worth surfacing.
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const syncHash = () => {
      const match = window.location.hash.match(/^#restaurant-(\d+)$/);
      setSelectedId(match ? Number(match[1]) : null);
    };
    syncHash();
    window.addEventListener("hashchange", syncHash);
    return () => window.removeEventListener("hashchange", syncHash);
  }, []);

  const openRestaurant = (id) => {
    window.location.hash = `restaurant-${id}`;
    setSelectedId(id);
  };

  const closeRestaurant = () => {
    window.history.replaceState(null, "", window.location.pathname);
    setSelectedId(null);
  };

  const filterParams = useCallback(
    (offset) => buildQuery(filters, coords, offset, PAGE_SIZE),
    [filters, coords],
  );

  useEffect(() => {
    if (cravingResults !== null) return;
    let cancelled = false;
    setStatus("loading");
    setVisibleCount(VISIBLE_STEP);

    // A city-wide result set is thousands of rows, so the first page is fetched
    // eagerly and further pages only when the reader asks for more. The map uses
    // the separate lightweight points endpoint, so it always has every match.
    listRestaurants(filterParams(0))
      .then((page) => {
        if (cancelled) return;
        setRestaurants(page.items);
        setTotalCount(page.total);
        setHasMore(page.items.length === PAGE_SIZE);
        setStatus("ready");
      })
      .catch(() => !cancelled && setStatus("error"));
    return () => {
      cancelled = true;
    };
  }, [filterParams, cravingResults]);

  const revealMore = () => {
    const nextVisible = visibleCount + VISIBLE_STEP;
    setVisibleCount(nextVisible);
    if (nextVisible <= restaurants.length || !hasMore || loadingMore) return;
    setLoadingMore(true);
    listRestaurants(filterParams(restaurants.length))
      .then((page) => {
        setRestaurants((previous) => {
          const seen = new Set(previous.map((item) => item.id));
          return [...previous, ...page.items.filter((item) => !seen.has(item.id))];
        });
        setHasMore(page.items.length === PAGE_SIZE);
      })
      .catch(() => setHasMore(false))
      .finally(() => setLoadingMore(false));
  };

  // The shortlist replaces the city list wholesale while it is on; it is not a
  // filter, because a saved place is usually not on the current page.
  const showingSaved = savedOnly && favorites.signedIn;
  const displayedRestaurants = showingSaved
    ? (savedPlaces ?? [])
    : (cravingResults ?? restaurants);
  const displayedStatus = showingSaved
    ? savedStatus === "idle"
      ? "loading"
      : savedStatus
    : cravingResults !== null
      ? "ready"
      : status;
  // The grid reveals a slice at a time; the map always gets the full set.
  const visibleRestaurants = showingSaved
    ? displayedRestaurants
    : cravingResults !== null
      ? cravingResults
      : restaurants.slice(0, visibleCount);
  // Hide the button while a page is in flight, but keep it visible so the reader
  // can keep going once it lands.
  const canRevealMore =
    !showingSaved &&
    cravingResults === null &&
    (restaurants.length > visibleRestaurants.length || (hasMore && !loadingMore));

  // What the API reported for the current filters, so the search box can say how
  // many places a phrase actually found rather than how many are on screen.
  const matchesCount = showingSaved ? null : (cravingResults !== null ? null : totalCount);

  const favoritesForList = useMemo(
    () => ({ ...favorites, requestToggle }),
    [favorites, requestToggle],
  );

  if (authLoading) {
    return (
      <div className="app-loading">
        <span className="loading-plate" aria-hidden="true">
          <BrandMark size={54} />
        </span>
        <strong>Waking up the food map…</strong>
      </div>
    );
  }

  return (
    <ThemeProvider>
      <div className="app-shell">
        <FestivalConfetti />
        <div className="floating-food" aria-hidden="true">
          <span><InterfaceIcon name="spice" size={25} /></span>
          <span><InterfaceIcon name="chinese" size={25} /></span>
          <span><InterfaceIcon name="comfort" size={25} /></span>
          <span><InterfaceIcon name="coffee" size={25} /></span>
          <span><InterfaceIcon name="leaf" size={25} /></span>
        </div>

        <header className="app-header">
          <nav className="topbar" aria-label="Primary">
            <a className="brand" href="#top" aria-label="Tabiko home">
              <span className="brand__mark" aria-hidden="true">
                <BrandMark size={46} />
              </span>
              <span className="brand__wordmark">TABIKO</span>
            </a>
            <div className="topbar__tags" aria-label="App highlights">
              <span><InterfaceIcon name="pin" size={14} /> Bengaluru</span>
              <span><InterfaceIcon name="spice" size={14} /> Street-food energy</span>
              <span><InterfaceIcon name="group" size={14} /> Community table</span>
            </div>
            <InstallButton />
          </nav>

          <HeroCollage />

          <div className="hero-copy" id="top">
            <span className="hero-copy__kicker">Big flavor. Zero boring bites.</span>
            <h1>
              Follow the flavor.
              <span> Find the funk.</span>
            </h1>
            <p>
              Tabiko is your neon-lit neighborhood table: real cravings, cult
              dishes, local intel, and a map that changes mood with every cuisine.
            </p>
            <div className="hero-copy__stats" aria-label="Product highlights">
              <span><strong>{stats ? stats.places.toLocaleString("en-IN") : "7,700+"}</strong> Bengaluru places</span>
              <span><strong>{stats ? stats.cuisines : "17"}</strong> cuisines mapped</span>
              <span><strong>0</strong> pay-to-play spots</span>
            </div>
          </div>
        </header>

        <FestivalMarquee />
        <AuthBar />

        {selectedId ? (
          <RestaurantDetail
            restaurantId={selectedId}
            onBack={closeRestaurant}
          />
        ) : (
          <main className="discovery-layout">
            <CravingSearchBar onResults={setCravingResults} />
            <FilterBar
              filters={filters}
              onChange={setFilters}
              disabled={cravingResults !== null}
            />
            <PlaceSearch
              value={filters.search}
              onChange={(search) => setFilters((previous) => ({ ...previous, search }))}
              disabled={cravingResults !== null}
              resultCount={matchesCount}
            />
            <NearbyBar
              radius={filters.radius_m}
              onRadiusChange={(radius_m) => setFilters((previous) => ({ ...previous, radius_m }))}
              sort={filters.sort}
              onSortChange={chooseSort}
              location={location}
              onRequestLocation={location.request}
              onRefreshLocation={location.refresh}
              disabled={cravingResults !== null}
            />

            <div className="view-toolbar">
              <div>
                <span className="section-kicker">Pick your view</span>
                <strong>
                  {showingSaved
                    ? "Your saved places"
                    : cravingResults !== null
                      ? "Craving radar hits"
                      : "Fresh from the table"}
                </strong>
              </div>
              <div className="view-toolbar__controls">
                <button
                  type="button"
                  className={`saved-toggle${savedOnly ? " is-active" : ""}`}
                  onClick={() => setSavedOnly((value) => !value)}
                  aria-pressed={savedOnly}
                  disabled={!favorites.signedIn}
                  title={
                    favorites.signedIn
                      ? "Show only the places you saved"
                      : "Sign in to save places"
                  }
                >
                  <InterfaceIcon
                    name={savedOnly ? "bookmark-filled" : "bookmark"}
                    size={15}
                  />
                  Saved
                  {favorites.signedIn && favorites.count > 0 && (
                    <span className="saved-toggle__count">{favorites.count}</span>
                  )}
                </button>
                <button
                  type="button"
                  className={`saved-toggle${showingFriends ? " is-active" : ""}`}
                  onClick={() => setShowingFriends((value) => !value)}
                  aria-pressed={showingFriends}
                  disabled={!authSignedIn}
                  title={
                    authSignedIn
                      ? "Show reviews from the people you follow"
                      : "Sign in to see reviews from people you follow"
                  }
                >
                  <InterfaceIcon name="people" size={15} />
                  Friends
                </button>
                <div className="view-toggle" role="group" aria-label="Result view">
                  <button
                    className={viewMode === "grid" ? "is-active" : ""}
                    onClick={() => setViewMode("grid")}
                    disabled={viewMode === "grid"}
                    aria-pressed={viewMode === "grid"}
                  >
                    <InterfaceIcon name="layers" size={15} /> Cards
                  </button>
                  <button
                    className={viewMode === "map" ? "is-active" : ""}
                    onClick={() => setViewMode("map")}
                    disabled={viewMode === "map"}
                    aria-pressed={viewMode === "map"}
                  >
                    <InterfaceIcon name="map-style" size={15} /> Food map
                  </button>
                </div>
              </div>
            </div>

            {showingFriends ? (
              <FriendsFeed onOpenRestaurant={openRestaurant} />
            ) : viewMode === "grid" ? (
              <LocationGate
                status={location.status}
                locating={location.locating}
                error={location.error}
                onRequest={location.request}
                onBrowseMap={() => setViewMode("map")}
              >
                <RestaurantList
                  restaurants={visibleRestaurants}
                  status={displayedStatus}
                  onSelect={openRestaurant}
                  cravingMode={cravingResults !== null}
                  totalCount={showingSaved ? (savedPlaces?.length ?? null) : totalCount}
                  hasMore={canRevealMore}
                  onLoadMore={revealMore}
                  loadingMore={loadingMore}
                  favorites={favoritesForList}
                  saveNotice={saveNotice}
                  savedMode={showingSaved}
                />
              </LocationGate>
            ) : (
              <MapView
                restaurants={displayedRestaurants}
                onSelect={openRestaurant}
                filters={proximity}
                cravingResults={cravingResults}
              />
            )}
          </main>
        )}

        <footer className="app-footer">
          <span>Cooked up with masala & main-character energy</span>
          <span>Place intel © OpenStreetMap contributors</span>
        </footer>
      </div>
    </ThemeProvider>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <MainApp />
    </AuthProvider>
  );
}
