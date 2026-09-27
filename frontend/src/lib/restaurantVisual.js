const CUISINE_VISUALS = [
  {
    match: /south indian|keralan|tamil|andhra/i,
    color: "#E63946",
    accent: "#FFD166",
    label: "South Indian",
  },
  {
    match: /north indian|mughlai/i,
    color: "#F45B69",
    accent: "#FFCA3A",
    label: "North Indian",
  },
  {
    match: /chinese/i,
    color: "#EF476F",
    accent: "#FFD166",
    label: "Chinese",
  },
  {
    match: /italian|pizza|pasta/i,
    color: "#2A9D8F",
    accent: "#E9C46A",
    label: "Italian",
  },
  {
    match: /continental|american|european/i,
    color: "#457B9D",
    accent: "#F4A261",
    label: "Continental",
  },
  {
    match: /cafe|bakery|coffee/i,
    color: "#A66A4E",
    accent: "#F4C095",
    label: "Cafe / Bakery",
  },
  {
    match: /street food|fast food/i,
    color: "#F45B69",
    accent: "#06D6A0",
    label: "Street Food",
  },
  {
    match: /multi-cuisine/i,
    color: "#7B61FF",
    accent: "#FFD166",
    label: "Multi-cuisine",
  },
];

const ICON_KEYS = {
  "South Indian": "south_indian",
  "North Indian": "north_indian",
  Chinese: "chinese",
  Italian: "italian",
  Continental: "continental",
  "Cafe / Bakery": "cafe",
  "Street Food": "street",
  "Multi-cuisine": "multi",
};

const TYPE_ICON_KEYS = {
  cafe: "cafe",
  family_restaurant: "multi",
  fine_dine: "continental",
  cloud_kitchen: "default",
  darshini_qsr: "south_indian",
  bar_microbrewery: "default",
  food_court_stall: "chinese",
  canteen: "south_indian",
  dhaba: "north_indian",
  street_stall: "street",
  hotel_restaurant: "continental",
  takeaway: "qsr",
  unclassified: "default",
};

const PATTERNS = ["dots", "stripes", "waves", "sparks"];

function hashString(value) {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(index);
    hash |= 0;
  }
  return Math.abs(hash);
}

function tint(hex, amount) {
  const normalized = hex.replace("#", "");
  const channels = [0, 2, 4].map((offset) =>
    parseInt(normalized.slice(offset, offset + 2), 16),
  );
  return `#${channels
    .map((channel) =>
      Math.round(channel + (255 - channel) * amount)
        .toString(16)
        .padStart(2, "0"),
    )
    .join("")}`;
}

function splitTags(value) {
  return (value || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

export function getRestaurantVisual(restaurant) {
  const cuisines = splitTags(restaurant?.cuisine_tags);
  const cuisineMatch = CUISINE_VISUALS.find((visual) =>
    cuisines.some((cuisine) => visual.match.test(cuisine)),
  );
  const type = restaurant?.type_tag || "unclassified";
  const seed = hashString(restaurant?.name || "tabiko");
  const baseColor = cuisineMatch?.color || "#FF5D3B";
  const baseAccent = cuisineMatch?.accent || "#FFD23F";
  const label = cuisineMatch?.label || cuisines[0] || "Food spot";

  return {
    iconKey: ICON_KEYS[label] || TYPE_ICON_KEYS[type] || ICON_KEYS["Multi-cuisine"],
    pattern: PATTERNS[seed % PATTERNS.length],
    color: tint(baseColor, (seed % 4) * 0.055),
    accent: tint(baseAccent, ((seed >> 3) % 4) * 0.07),
    label,
    tone: cuisineMatch?.label?.toLowerCase().replace(/[^a-z]+/g, "-") || "multi",
  };
}

export function prettyTag(tag) {
  if (!tag) return null;
  return tag.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function moneyTier(tier) {
  if (tier == null) return null;
  return "₹".repeat(Math.max(1, Math.min(4, tier)));
}
