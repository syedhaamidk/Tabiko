"""First-pass restaurant classification from source taxonomy values.

Cuisine and venue type are deliberately separate signals. A South Indian
restaurant is not automatically a Darshini, and a cuisine value alone rarely
proves whether a venue is a cafe, family restaurant, or fine-dining space.
"""

from __future__ import annotations

import re

from .models import RestaurantType

# raw source cuisine -> (fixed app label, default visual theme)
CUISINE_TAG_MAP: dict[str, tuple[str, str]] = {
    "south_indian": ("South Indian", "south_indian"),
    "regional": ("Regional", "multi_cuisine_default"),
    "keralan": ("South Indian", "south_indian"),
    "tamil": ("South Indian", "south_indian"),
    "andhra": ("South Indian", "south_indian"),
    "telugu": ("South Indian", "south_indian"),
    "north_indian": ("North Indian", "north_indian"),
    "mughlai": ("North Indian", "north_indian"),
    "biryani": ("Biryani", "north_indian"),
    "hyderabadi": ("Biryani", "north_indian"),
    "lucknowi": ("Biryani", "north_indian"),
    "awadhi": ("North Indian", "north_indian"),
    "punjabi": ("North Indian", "north_indian"),
    "rajasthani": ("North Indian", "north_indian"),
    "gujarati": ("North Indian", "north_indian"),
    "bengali": ("Bengali", "north_indian"),
    "chaat": ("Chaat & Snacks", "street_food"),
    "tiffin": ("Tiffin", "south_indian"),
    "mess": ("Tiffin", "south_indian"),
    "seafood": ("Seafood", "multi_cuisine_default"),
    "fish": ("Seafood", "multi_cuisine_default"),
    "chinese": ("Chinese", "chinese"),
    "thai": ("Thai", "multi_cuisine_default"),
    "japanese": ("Other Asian", "multi_cuisine_default"),
    "korean": ("Other Asian", "multi_cuisine_default"),
    "vietnamese": ("Other Asian", "multi_cuisine_default"),
    "asian": ("Other Asian", "multi_cuisine_default"),
    "arabian": ("Arabian & Lebanese", "multi_cuisine_default"),
    "lebanese": ("Arabian & Lebanese", "multi_cuisine_default"),
    "african": ("African", "multi_cuisine_default"),
    "mexican": ("Mexican", "continental_italian"),
    "cafe": ("Cafe/Bakery", "cafe_bakery"),
    "coffee_shop": ("Cafe/Bakery", "cafe_bakery"),
    "bakery": ("Cafe/Bakery", "cafe_bakery"),
    "ice_cream": ("Desserts & Sweets", "cafe_bakery"),
    "dessert": ("Desserts & Sweets", "cafe_bakery"),
    "confectionery": ("Desserts & Sweets", "cafe_bakery"),
    "tea": ("Cafe/Bakery", "cafe_bakery"),
    "juice_bar": ("Cafe/Bakery", "cafe_bakery"),
    "street_food": ("Street Food", "street_food"),
    "fast_food": ("Street Food", "street_food"),
    "italian": ("Italian", "continental_italian"),
    "pizza": ("Italian", "continental_italian"),
    "pasta": ("Italian", "continental_italian"),
    "continental": ("Continental", "continental_italian"),
    "american": ("Continental", "continental_italian"),
    "european": ("Continental", "continental_italian"),
    "indian": ("Multi-cuisine", "multi_cuisine_default"),
    "multi_cuisine": ("Multi-cuisine", "multi_cuisine_default"),
    "fusion": ("Multi-cuisine", "multi_cuisine_default"),
    "fine_dining": ("Multi-cuisine", "fine_dine"),
    "bar": ("Multi-cuisine", "multi_cuisine_default"),
    "biergarten": ("Multi-cuisine", "multi_cuisine_default"),
    "microbrewery": ("Multi-cuisine", "multi_cuisine_default"),
}

# Canonical cuisine labels the API can be filtered by, in menu order. The map
# above only ever emits one of these, so the published filter list and the
# stored data cannot drift apart.
CANONICAL_CUISINES: tuple[str, ...] = (
    "South Indian",
    "Regional",
    "North Indian",
    "Biryani",
    "Bengali",
    "Chaat & Snacks",
    "Tiffin",
    "Chinese",
    "Thai",
    "Other Asian",
    "Arabian & Lebanese",
    "Italian",
    "Continental",
    "Mexican",
    "African",
    "Seafood",
    "Cafe/Bakery",
    "Desserts & Sweets",
    "Street Food",
    "Multi-cuisine",
)

# Explicit source tokens that genuinely determine venue type.
TYPE_TAG_MAP: dict[str, RestaurantType] = {
    "cafe": RestaurantType.cafe,
    "coffee_shop": RestaurantType.cafe,
    "bakery": RestaurantType.cafe,
    "ice_cream": RestaurantType.cafe,
    "tea": RestaurantType.cafe,
    "fine_dining": RestaurantType.fine_dine,
    "restaurant": RestaurantType.family_restaurant,
    "bar": RestaurantType.bar_microbrewery,
    "biergarten": RestaurantType.bar_microbrewery,
    "microbrewery": RestaurantType.bar_microbrewery,
    "darshini": RestaurantType.darshini_qsr,
    "qsr": RestaurantType.darshini_qsr,
    "fast_food": RestaurantType.darshini_qsr,
    "food_court": RestaurantType.food_court_stall,
    "cloud_kitchen": RestaurantType.cloud_kitchen,
    "canteen": RestaurantType.canteen,
    "mess": RestaurantType.canteen,
    "dhaba": RestaurantType.dhaba,
    "roadside": RestaurantType.dhaba,
    "street_stall": RestaurantType.street_stall,
    "food_truck": RestaurantType.street_stall,
    "hotel_restaurant": RestaurantType.hotel_restaurant,
    "guesthouse": RestaurantType.hotel_restaurant,
    "takeaway": RestaurantType.takeaway,
    "delivery": RestaurantType.takeaway,
}

# Kept as a public compatibility alias for callers that used the original map.
RAW_TAG_MAP: dict[str, tuple[str, RestaurantType, str]] = {
    key: (
        cuisine,
        TYPE_TAG_MAP.get(key, RestaurantType.unclassified),
        theme,
    )
    for key, (cuisine, theme) in CUISINE_TAG_MAP.items()
}

DEFAULT = ("Multi-cuisine", RestaurantType.unclassified, "multi_cuisine_default")


def _normalize_tag(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _normalized_values(raw_tag: str) -> list[str]:
    return [
        normalized
        for raw_value in re.split(r"[;,|]", raw_tag)
        if (normalized := _normalize_tag(raw_value))
    ]


def classify_from_raw_tag(raw_tag: str | None) -> tuple[str, RestaurantType, str]:
    """Classify cuisine and only those venue types explicitly present in input."""

    if not raw_tag or not raw_tag.strip():
        return DEFAULT

    values = _normalized_values(raw_tag)
    cuisine_matches: list[tuple[str, str]] = []
    seen_cuisines: set[str] = set()
    for value in values:
        match = CUISINE_TAG_MAP.get(value)
        if match is None:
            continue
        cuisine, theme_id = match
        if cuisine not in seen_cuisines:
            cuisine_matches.append(match)
            seen_cuisines.add(cuisine)

    type_tag = RestaurantType.unclassified
    for value in values:
        if value in TYPE_TAG_MAP:
            type_tag = TYPE_TAG_MAP[value]
            break

    if cuisine_matches:
        primary_cuisine, cuisine_theme = cuisine_matches[0]
        cuisine_tags = ", ".join(cuisine for cuisine, _ in cuisine_matches)
        theme_id = cuisine_theme
    else:
        primary_cuisine = "Multi-cuisine"
        cuisine_tags = primary_cuisine
        theme_id = "multi_cuisine_default"

    if type_tag == RestaurantType.fine_dine:
        theme_id = "fine_dine"
    elif type_tag == RestaurantType.cafe:
        theme_id = "cafe_bakery"
    elif type_tag == RestaurantType.bar_microbrewery:
        theme_id = "multi_cuisine_default"

    return cuisine_tags, type_tag, theme_id
