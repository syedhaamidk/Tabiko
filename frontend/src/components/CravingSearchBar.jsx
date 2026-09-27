import { useState } from "react";
import { searchByCraving } from "../api";
import BrandMark from "./BrandMark";
import InterfaceIcon from "./InterfaceIcon";

const QUICK_CRAVINGS = [
  { label: "Spicy", icon: "spice" },
  { label: "Coffee", icon: "coffee" },
  { label: "Comfort food", icon: "comfort" },
  { label: "Date night", icon: "date" },
];

export default function CravingSearchBar({ onResults }) {
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState(null);
  // Terms the corpus has no text for. The results below are still real matches
  // for the rest of the query, but the score cannot speak to these words, and
  // saying so is better than presenting a confident ranking that is really
  // matching a common word like "food".
  const [partial, setPartial] = useState([]);

  async function runSearch(value) {
    const cleaned = value.trim();
    if (!cleaned) {
      onResults(null);
      setError(null);
      setPartial([]);
      return;
    }
    setSearching(true);
    setError(null);
    setPartial([]);
    try {
      const results = await searchByCraving(cleaned);
      onResults(
        results.map((result) => ({
          ...result.restaurant,
          craving_score: Math.min(99, Math.max(1, Math.round(result.relevance * 100))),
        })),
      );
      setPartial(results[0]?.unmatched_terms ?? []);
    } catch (requestError) {
      console.warn("Craving search failed:", requestError);
      onResults([]);
      setError(requestError.message || "Search failed. Try again.");
    } finally {
      setSearching(false);
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    runSearch(query);
  }

  function chooseQuickCraving(value) {
    const nextQuery = value === query ? "" : value;
    setQuery(nextQuery);
    runSearch(nextQuery);
  }

  function clearSearch() {
    setQuery("");
    setError(null);
    setPartial([]);
    onResults(null);
  }

  return (
    <section className="craving-search" aria-labelledby="craving-heading">
      <form onSubmit={handleSubmit} className="craving-search__form">
        <div className="craving-search__copy">
          <span className="section-kicker">Craving radar</span>
          <h2 id="craving-heading">Craving radar on.</h2>
        </div>
        <div className="craving-search__control">
          <span className="craving-search__icon" aria-hidden="true">
            <BrandMark size={26} />
          </span>
          <input
            type="search"
            aria-label="Search by craving"
            placeholder="Type the vibe — “spicy comfort food”"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <button className="app-button app-button--primary" type="submit" disabled={searching}>
            {searching ? "Hunting…" : "Hunt this craving"}
            <span aria-hidden="true">→</span>
          </button>
          {query && (
            <button className="craving-search__clear" type="button" onClick={clearSearch} aria-label="Clear craving search">
              ×
            </button>
          )}
        </div>
      </form>
      <span className="craving-burst" aria-hidden="true">FOLLOW<br />THE<br />FLAVOR!</span>
      <span className="craving-squiggle" aria-hidden="true">〰〰〰</span>
      <div className="craving-search__chips" aria-label="Quick cravings">
        <span>Quick picks:</span>
        {QUICK_CRAVINGS.map((craving) => (
          <button
            type="button"
            key={craving.label}
            className={query === craving.label ? "is-active" : ""}
            onClick={() => chooseQuickCraving(craving.label)}
          >
            <InterfaceIcon name={craving.icon} size={17} strokeWidth={2} />
            {craving.label}
          </button>
        ))}
      </div>
      {error && <p className="craving-search__error">{error}</p>}
      {!error && partial.length > 0 && (
        <p className="craving-search__partial" role="status">
          <InterfaceIcon name="search" size={15} />
          <span>
            No dish or review text mentions{" "}
            <strong>{partial.join(", ")}</strong> yet, so these are matched on
            place names alone. Try a cuisine or a dish instead.
          </span>
        </p>
      )}
    </section>
  );
}
