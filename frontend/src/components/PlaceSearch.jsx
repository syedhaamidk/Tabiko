import { useEffect, useRef, useState } from "react";
import InterfaceIcon from "./InterfaceIcon";

/**
 * Free-text search over place names and addresses.
 *
 * This is deliberately separate from the craving radar: that matches the
 * flavour text of dishes and reviews, while this matches the thing a reader is
 * actually looking for ("Biryani", "Toit", "a cafe on 12th Main"). The API
 * already supported it, so this is the missing half of the same feature.
 *
 * Keystrokes are debounced here rather than in App so a five-letter word is one
 * request, not five.
 */

const DEBOUNCE_MS = 300;

export default function PlaceSearch({ value, onChange, disabled, resultCount }) {
  const [text, setText] = useState(value ?? "");
  const timer = useRef(null);

  // Follow the parent when it clears the field from somewhere else.
  useEffect(() => {
    setText(value ?? "");
  }, [value]);

  useEffect(() => () => clearTimeout(timer.current), []);

  const push = (next) => {
    setText(next);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => onChange(next.trim()), DEBOUNCE_MS);
  };

  const clear = () => {
    clearTimeout(timer.current);
    setText("");
    onChange("");
  };

  const active = (value ?? "") !== "";
  const trimmed = text.trim();

  return (
    <div className={`place-search${disabled ? " is-disabled" : ""}`}>
      <label className="place-search__label" htmlFor="place-search-input">
        <InterfaceIcon name="search" size={16} />
        Search a place or dish
      </label>
      <div className="place-search__field">
        <input
          id="place-search-input"
          type="search"
          value={text}
          placeholder="Try “biryani”, “Toit”, or a street name"
          autoComplete="off"
          spellCheck="false"
          disabled={disabled}
          onChange={(event) => push(event.target.value)}
          onKeyDown={(event) => {
            // Enter should search now, not after the debounce expires.
            if (event.key === "Enter") {
              event.preventDefault();
              clearTimeout(timer.current);
              onChange(trimmed);
            }
          }}
        />
        {text && (
          <button
            type="button"
            className="place-search__clear"
            onClick={clear}
            disabled={disabled}
            aria-label="Clear search"
          >
            <InterfaceIcon name="close" size={15} />
          </button>
        )}
      </div>
      <p className="place-search__status" role="status" aria-live="polite">
        {active
          ? resultCount != null
            ? `${resultCount} ${resultCount === 1 ? "place matches" : "places match"} “${trimmed}”`
            : `Searching for “${trimmed}”…`
          : ""}
      </p>
    </div>
  );
}
