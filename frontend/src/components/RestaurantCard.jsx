import FoodGlyph from "../lib/foodIcons";
import InterfaceIcon from "./InterfaceIcon";
import {
  getRestaurantVisual,
  moneyTier,
  prettyTag,
} from "../lib/restaurantVisual";

const DIETARY_ICONS = {
  veg: "leaf",
  non_veg: "non-veg",
  vegan: "vegan",
  jain: "jain",
  halal: "halal",
};

function splitTags(value) {
  return (value || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

/** Metres below a kilometre, then kilometres with one decimal above it. */
export function formatDistance(metres) {
  if (metres == null) return null;
  if (metres < 950) return `${Math.round(metres / 10) * 10} m`;
  // Round in metres first. Dividing then calling toFixed is not equivalent:
  // 0.95 is not exactly representable, so (950 / 1000).toFixed(1) is "0.9" and
  // exactly 950 m would have read as a shorter distance than 951 m.
  return `${(Math.round(metres / 100) / 10).toFixed(1)} km`;
}

export default function RestaurantCard({
  restaurant,
  onSelect,
  saved = false,
  saving = false,
  onToggleSave,
}) {
  const cuisines = splitTags(restaurant.cuisine_tags);
  const dietary = splitTags(restaurant.dietary_flags);
  const goodFor = splitTags(restaurant.good_for);
  const visual = getRestaurantVisual(restaurant);
  const price = moneyTier(restaurant.price_tier);
  // Only present when the request carried an origin, so it is never a guess.
  const distance = formatDistance(restaurant.distance_m);

  return (
    <div className="restaurant-card-wrap">
      <button
        type="button"
        className={`restaurant-card restaurant-card--${visual.tone}`}
        style={{ "--card-color": visual.color, "--card-accent": visual.accent }}
        onClick={() => onSelect(restaurant.id)}
        aria-label={`Explore ${restaurant.name}`}
      >
      <span className="restaurant-card__stripe" aria-hidden="true" />
      <span className="restaurant-card__tape" aria-hidden="true" />
      <span className="restaurant-card__poster-number" aria-hidden="true">
        #{String(restaurant.id).padStart(2, "0")}
      </span>
      <span className="restaurant-card__flavor-sticker" aria-hidden="true">
        <FoodGlyph visual={visual} size={17} instanceId={`flavor-${restaurant.id}`} />
        {visual.label}
      </span>
      <span className="restaurant-card__watermark" aria-hidden="true">
        <FoodGlyph visual={visual} size={92} instanceId={`watermark-${restaurant.id}`} />
      </span>
      <span className="restaurant-card__top">
        <span className="restaurant-card__icon" aria-hidden="true">
          <FoodGlyph visual={visual} size={52} instanceId={`card-${restaurant.id}`} />
        </span>
        <span className="restaurant-card__identity">
          <span className="restaurant-card__eyebrow">{visual.label}</span>
          <span className="restaurant-card__name" role="heading" aria-level="3">
            {restaurant.name}
          </span>
        </span>
        <span className="restaurant-card__badges">
          {distance && (
            <span className="distance-badge">
              <InterfaceIcon name="walk" size={13} />
              {distance}
            </span>
          )}
          {price && <span className="restaurant-card__price">{price}</span>}
        </span>
      </span>

      <span className="tag-row">
        {cuisines.slice(0, 3).map((cuisine) => (
          <span className="tag-pill" key={cuisine}>
            {prettyTag(cuisine)}
          </span>
        ))}
        {dietary.slice(0, 2).map((flag) => (
          <span className="tag-pill tag-pill--diet" key={flag}>
            <InterfaceIcon name={DIETARY_ICONS[flag.toLowerCase()]} size={13} />
            {prettyTag(flag)}
          </span>
        ))}
      </span>

      <span className="restaurant-card__meta">
        <span>
          {prettyTag(restaurant.type_tag || "unclassified")}
          {restaurant.noise_level && restaurant.noise_level !== "unknown"
            ? ` · ${prettyTag(restaurant.noise_level)}`
            : ""}
        </span>
        {goodFor.length > 0 && (
          <span>Good for {goodFor.slice(0, 2).map(prettyTag).join(" + ")}</span>
        )}
      </span>

      {restaurant.craving_score != null && (
        <span className="flavor-match">
          <InterfaceIcon name="sparkles" size={14} /> Flavor match {restaurant.craving_score}%
        </span>
      )}

      {restaurant.hygiene_score != null && (
        <span className="hygiene-badge">
          <InterfaceIcon name="leaf" size={14} /> Freshness signal {restaurant.hygiene_score.toFixed(1)}/5
        </span>
      )}

      <span className="restaurant-card__footer">
        <span className="good-food-stamp">GOOD FOOD<br />NO BORING BITES</span>
        <span className="restaurant-card__explore">
          Explore <span aria-hidden="true">→</span>
        </span>
      </span>
      </button>
      {onToggleSave && (
        // A sibling of the card, not a child: nesting a button inside the card's
        // button is invalid and would make the card untappable with a keyboard.
        <button
          type="button"
          className={`save-toggle${saved ? " is-saved" : ""}`}
          onClick={() => onToggleSave(restaurant.id)}
          disabled={saving}
          aria-pressed={saved}
          aria-label={saved ? `Remove ${restaurant.name} from saved places` : `Save ${restaurant.name}`}
          title={saved ? "Remove from saved" : "Save for later"}
        >
          <InterfaceIcon name={saved ? "bookmark-filled" : "bookmark"} size={15} />
        </button>
      )}
    </div>
  );
}
