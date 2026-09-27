/**
 * Presentation for the canonical cuisine labels.
 *
 * `FilterBar` and the map legend both read from here, so a cuisine can never
 * have a menu entry but no legend colour (or the reverse). The keys are exactly
 * the values published by GET /filter-options.
 */

const PALETTE = [
  "#ff2e88",
  "#c6f135",
  "#2d5bff",
  "#ff6b35",
  "#7b61ff",
  "#ffd23f",
  "#2a9d8f",
  "#e63946",
  "#f472b6",
  "#4d7c0f",
];

const DEFAULT_ICON = "plate";

const CUISINE_PRESENTATION = {
  "South Indian": { label: "South Indian", icon: "south-indian" },
  Regional: { label: "Regional / local", icon: "chaat" },
  "North Indian": { label: "North Indian", icon: "north-indian" },
  Biryani: { label: "Biryani", icon: "biryani" },
  Bengali: { label: "Bengali & Bengali sweets", icon: "bengali" },
  "Chaat & Snacks": { label: "Chaat & snacks", icon: "chaat" },
  Tiffin: { label: "Tiffin & mess", icon: "tiffin" },
  Chinese: { label: "Chinese", icon: "chinese" },
  Thai: { label: "Thai", icon: "thai" },
  "Other Asian": { label: "Other Asian", icon: "other-asian" },
  "Arabian & Lebanese": { label: "Arabian & Lebanese", icon: "arabian" },
  Italian: { label: "Italian", icon: "italian" },
  Continental: { label: "Continental", icon: "continental" },
  Mexican: { label: "Mexican", icon: "mexican" },
  African: { label: "African", icon: "african" },
  Seafood: { label: "Seafood", icon: "seafood" },
  "Cafe/Bakery": { label: "Cafe & bakery", icon: "coffee" },
  "Desserts & Sweets": { label: "Desserts & sweets", icon: "desserts" },
  "Street Food": { label: "Street food", icon: "street-food" },
  "Multi-cuisine": { label: "Multi-cuisine", icon: "multi" },
};

export function cuisinePresentation(value) {
  return CUISINE_PRESENTATION[value] ?? { label: value, icon: DEFAULT_ICON };
}

/** Keys of the shared table, used as the bundled fallback filter list. */
export const CANONICAL_CUISINES = Object.keys(CUISINE_PRESENTATION);

/** Stable colour per cuisine so the key does not reshuffle between renders. */
function colorFor(value) {
  const known = Object.keys(CUISINE_PRESENTATION);
  const index = known.indexOf(value);
  if (index >= 0) return PALETTE[index % PALETTE.length];
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) hash = (hash * 31 + value.charCodeAt(i)) | 0;
  return PALETTE[Math.abs(hash) % PALETTE.length];
}

/** Shared with the map legend and cluster bubbles so colours always match. */
export function cuisineColor(value) {
  return colorFor(value);
}

const MAX_LEGEND_ENTRIES = 6;

/**
 * Build the map legend from the cuisines actually present in the results.
 *
 * Deriving this from the data (rather than a fixed list of groups) is what keeps
 * the key honest: it always matches the places on screen, including cuisines
 * added to the taxonomy after this file was written.
 */
export function buildCuisineLegend(restaurants) {
  const counts = new Map();

  for (const restaurant of restaurants) {
    const tags = (restaurant.cuisine_tags || "")
      .split(",")
      .map((tag) => tag.trim())
      .filter(Boolean);
    for (const tag of tags) {
      counts.set(tag, (counts.get(tag) ?? 0) + 1);
    }
  }

  return [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, MAX_LEGEND_ENTRIES)
    .map(([value, count]) => {
      const presentation = cuisinePresentation(value);
      return {
        key: value,
        label: presentation.label,
        icon: presentation.icon,
        color: colorFor(value),
        count,
      };
    });
}
