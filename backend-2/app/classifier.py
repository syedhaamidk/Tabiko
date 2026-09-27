"""
Classification pipeline — v1 is rule-based on the raw source tag (e.g. OSM's
"cuisine" value) just so the ingestion pipeline has something to populate
cuisine_tags / type_tag / theme_id with immediately.

Swap `classify_from_raw_tag` for an LLM-based classifier once you have menu
text and review content to work with (that's the RAG piece — same pattern
as Codex/Benkyo: embed the raw text, retrieve/prompt against a fixed
taxonomy, and only fall back to this rule table when the model is unsure).
"""

from .models import RestaurantType

# raw OSM/Foursquare cuisine string -> (cuisine_tags, type_tag, theme_id)
RAW_TAG_MAP = {
    "south_indian": ("South Indian", RestaurantType.darshini_qsr, "south_indian"),
    "indian": ("North Indian", RestaurantType.family_restaurant, "north_indian"),
    "north_indian": ("North Indian", RestaurantType.family_restaurant, "north_indian"),
    "chinese": ("Chinese", RestaurantType.family_restaurant, "chinese"),
    "cafe": ("Cafe", RestaurantType.cafe, "cafe_bakery"),
    "coffee_shop": ("Cafe", RestaurantType.cafe, "cafe_bakery"),
    "bakery": ("Bakery", RestaurantType.cafe, "cafe_bakery"),
    "street_food": ("Street Food", RestaurantType.food_court_stall, "street_food"),
    "italian": ("Italian", RestaurantType.family_restaurant, "continental_italian"),
    "pizza": ("Italian", RestaurantType.family_restaurant, "continental_italian"),
    "fine_dining": ("Multi-cuisine", RestaurantType.fine_dine, "fine_dine"),
    "bar": ("Multi-cuisine", RestaurantType.bar_microbrewery, "multi_cuisine_default"),
    "biergarten": ("Multi-cuisine", RestaurantType.bar_microbrewery, "multi_cuisine_default"),
}

DEFAULT = ("Multi-cuisine", RestaurantType.unclassified, "multi_cuisine_default")


def classify_from_raw_tag(raw_tag: str | None) -> tuple[str, RestaurantType, str]:
    if not raw_tag:
        return DEFAULT
    key = raw_tag.strip().lower().replace(" ", "_")
    return RAW_TAG_MAP.get(key, DEFAULT)
