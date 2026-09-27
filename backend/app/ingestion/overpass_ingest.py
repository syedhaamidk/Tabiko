"""Ingest restaurants and food venues from OpenStreetMap via Overpass.

The importer upserts OSM nodes, ways, and relations around a center point.  It
uses a descriptive User-Agent, retries transient Overpass failures, and can fall
back to public mirrors so a busy primary endpoint does not break local setup.

Usage:
    python -m app.ingestion.overpass_ingest --lat 13.1682 --lon 77.5354 --radius 5000
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
import time
from collections.abc import Sequence
from typing import Any

import requests
from sqlalchemy.orm import Session

from ..classifier import classify_from_raw_tag
from ..database import Base, SessionLocal, engine
from ..models import NoiseLevel, Restaurant, RestaurantType
from ..schemas import GOOD_FOR_TAGS

OVERPASS_URL = os.getenv(
    "TABIKO_OVERPASS_URL", "https://overpass-api.de/api/interpreter"
)
OVERPASS_MIRRORS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
USER_AGENT = os.getenv(
    "TABIKO_USER_AGENT",
    "tabiko/0.5 (Bengaluru food radar; local development)",
)
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}

# OSM amenity/shop tags worth pulling in for a food-discovery app. Kept broad so
# the cuisine, venue, and diet filters all have something to match.
FOOD_TAGS = (
    "amenity=restaurant",
    "amenity=cafe",
    "amenity=fast_food",
    "amenity=bar",
    "amenity=pub",
    "amenity=biergarten",
    "amenity=ice_cream",
    "amenity=food_court",
    "amenity=diner",
    "amenity=bbq",
    "shop=bakery",
    "shop=confectionery",
    "shop=juice_bar",
    "shop=coffee",
    "shop=tea",
    "shop=pastry",
)


def build_query(lat: float, lon: float, radius_m: int, timeout_s: int = 60) -> str:
    clauses = "\n".join(
        f"  nwr[{food_tag}](around:{radius_m},{lat},{lon});" for food_tag in FOOD_TAGS
    )
    return f"""
    [out:json][timeout:{timeout_s}];
    (
    {clauses}
    );
    out center;
    """


def build_bbox_query(
    south: float, west: float, north: float, east: float, timeout_s: int = 300
) -> str:
    """Area query for city-scale ingestion.

    A radius query over a whole metropolis is far slower in Overpass than an
    equivalent bounding box, because `around:` has to walk every indexed node.
    """
    clauses = "\n".join(
        f"  nwr[{food_tag}]({south},{west},{north},{east});" for food_tag in FOOD_TAGS
    )
    return f"""
    [out:json][timeout:{timeout_s}];
    (
    {clauses}
    );
    out center;
    """


def tile_bbox(
    bbox: tuple[float, float, float, float], rows: int, columns: int
) -> list[tuple[float, float, float, float]]:
    """Split a bounding box into a grid of smaller ones.

    A single city-wide Overpass query is the shape that reliably times out: the
    free endpoints rate-limit by cost, and one query returning every food venue
    in a metropolis is expensive. A grid of small queries is individually cheap,
    so each is more likely to be answered, and a tile that fails costs one tile
    rather than the whole city.
    """

    south, west, north, east = bbox
    if rows < 1 or columns < 1:
        raise ValueError("rows and columns must both be at least 1")

    lat_step = (north - south) / rows
    lon_step = (east - west) / columns
    return [
        (
            south + row * lat_step,
            west + column * lon_step,
            south + (row + 1) * lat_step,
            west + (column + 1) * lon_step,
        )
        for row in range(rows)
        for column in range(columns)
    ]


def fetch_bbox_tiled(
    bbox: tuple[float, float, float, float],
    *,
    rows: int = 4,
    columns: int = 4,
    urls: Sequence[str] | None = None,
    attempts_per_url: int = 2,
    request_timeout: float = 180.0,
    on_tile: Any = None,
) -> list[dict[str, Any]]:
    """Fetch a whole area as a grid of small queries and merge the results.

    Tiles overlap at the edges in OSM's own indexing, so the same object can
    appear in two of them. Deduplication is by `type-id`, which is stable across
    Overpass responses, so a place on a tile boundary is stored once.

    `on_tile` is called with `(index, total, count)` after each tile so a caller
    can report progress on a run that takes several minutes.
    """

    tiles = tile_bbox(bbox, rows, columns)
    merged: dict[str, dict[str, Any]] = {}
    total = len(tiles)

    for index, tile in enumerate(tiles, start=1):
        if on_tile is not None:
            on_tile(index, total, 0)
        elements = fetch_elements(
            build_bbox_query(*tile, timeout_s=180),
            urls=urls,
            attempts_per_url=attempts_per_url,
            request_timeout=request_timeout,
        )
        for element in elements:
            source_id = _osm_source_id(element)
            if source_id is not None and source_id in merged:
                continue
            if source_id is not None:
                merged[source_id] = element
            else:
                # Keep unidentifiable elements rather than dropping them: they
                # cannot be upserted anyway, but discarding them here would make
                # the tile count a lie.
                merged[f"unidentified-{index}-{len(merged)}"] = element
        if on_tile is not None:
            on_tile(index, total, len(merged))

    return list(merged.values())


def fetch_places(
    lat: float,
    lon: float,
    radius_m: int,
    *,
    urls: Sequence[str] | None = None,
    attempts_per_url: int = 2,
    backoff_seconds: float = 1.0,
    request_timeout: float = 90.0,
) -> list[dict[str, Any]]:
    """Fetch OSM elements around a point, retrying transient errors."""

    return fetch_elements(
        build_query(lat, lon, radius_m),
        urls=urls,
        attempts_per_url=attempts_per_url,
        backoff_seconds=backoff_seconds,
        request_timeout=request_timeout,
    )


def fetch_elements(
    query: str,
    *,
    urls: Sequence[str] | None = None,
    attempts_per_url: int = 2,
    backoff_seconds: float = 1.0,
    request_timeout: float = 90.0,
) -> list[dict[str, Any]]:
    """Run a prepared Overpass query against each endpoint until one answers."""

    endpoints = list(urls or dict.fromkeys((OVERPASS_URL, *OVERPASS_MIRRORS)))
    errors: list[str] = []

    for endpoint in endpoints:
        for attempt in range(1, attempts_per_url + 1):
            try:
                response = requests.post(
                    endpoint,
                    data={"data": query},
                    headers={"User-Agent": USER_AGENT},
                    timeout=request_timeout,
                )
            except requests.RequestException as exc:
                errors.append(f"{endpoint}: {exc}")
                if attempt < attempts_per_url:
                    time.sleep(backoff_seconds * (2 ** (attempt - 1)))
                    continue
                break

            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError as exc:
                    errors.append(f"{endpoint}: invalid JSON ({exc})")
                    break
                if isinstance(payload, dict) and payload.get("remark"):
                    errors.append(
                        f"{endpoint}: partial Overpass response: "
                        f"{str(payload['remark'])[:180]}"
                    )
                    break
                elements = (
                    payload.get("elements") if isinstance(payload, dict) else None
                )
                if not isinstance(elements, list):
                    errors.append(f"{endpoint}: response has no elements list")
                    break
                # Invalid members are skipped rather than aborting an otherwise
                # usable response; upsert performs the remaining shape checks.
                return [element for element in elements if isinstance(element, dict)]

            detail = response.text.strip().replace("\n", " ")[:180]
            errors.append(f"{endpoint}: HTTP {response.status_code} {detail}")
            if (
                response.status_code in RETRYABLE_STATUS_CODES
                and attempt < attempts_per_url
            ):
                time.sleep(backoff_seconds * (2 ** (attempt - 1)))
                continue
            break

    summary = "; ".join(errors) or "no Overpass endpoints configured"
    raise requests.RequestException(f"All Overpass requests failed: {summary}")


def _osm_source_id(element: Any) -> str | None:
    if not isinstance(element, dict):
        return None
    element_id = element.get("id")
    element_type = element.get("type")
    if element_id is None or element_type not in {"node", "way", "relation"}:
        return None
    return f"osm-{element_type}-{element_id}"


def _element_coordinates(element: dict[str, Any]) -> tuple[float, float] | None:
    latitude = element.get("lat")
    longitude = element.get("lon")
    if latitude is None or longitude is None:
        center = element.get("center")
        if isinstance(center, dict):
            latitude = center.get("lat")
            longitude = center.get("lon")
    if latitude is None or longitude is None:
        return None
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return None
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        return None
    return latitude, longitude


def _tag_value(tags: dict[str, Any], key: str) -> str:
    value = tags.get(key, "")
    return value.strip().lower() if isinstance(value, str) else ""


def _dietary_flags(tags: dict[str, Any]) -> str | None:
    flags: list[str] = []
    vegetarian = _tag_value(tags, "diet:vegetarian")
    if vegetarian in {"yes", "vegetarian", "only"}:
        flags.append("veg")
    elif vegetarian in {"no", "non_vegetarian"}:
        flags.append("non_veg")

    if _tag_value(tags, "diet:vegan") in {"yes", "only"}:
        flags.append("vegan")
    if _tag_value(tags, "diet:jain") in {"yes", "only"}:
        flags.append("jain")
    if _tag_value(tags, "diet:halal") in {"yes", "only"}:
        flags.append("halal")

    return ", ".join(dict.fromkeys(flags)) or None


def _noise_level(tags: dict[str, Any]) -> NoiseLevel:
    value = _tag_value(tags, "noise_level") or _tag_value(tags, "noise")
    if value in {"quiet", "silent"}:
        return NoiseLevel.quiet
    if value in {"moderate", "normal"}:
        return NoiseLevel.moderate
    if value in {"loud", "noisy"}:
        return NoiseLevel.loud
    return NoiseLevel.unknown


def _accessibility_flags(tags: dict[str, Any]) -> str | None:
    flags: list[str] = []
    wheelchair = _tag_value(tags, "wheelchair")
    if wheelchair in {"yes", "limited"}:
        flags.append("wheelchair_accessible")
    elif wheelchair == "no":
        flags.append("not_wheelchair_accessible")
    if _tag_value(tags, "step_free") in {"yes", "true", "1"}:
        flags.append("step_free")
    if _tag_value(tags, "indoor_seating") in {"yes", "true", "1"}:
        flags.append("seating")
    return ", ".join(dict.fromkeys(flags)) or None


def _good_for(tags: dict[str, Any]) -> str | None:
    """Collect occasion tags, preferring explicit `good_for` values.

    A few unambiguous OSM tags are mapped onto occasion labels so the filter has
    something to match; nothing here is inferred from the place name.
    """

    values: list[str] = []

    raw = _tag_value(tags, "good_for")
    if raw:
        values.extend(value.strip().lower() for value in re.split(r"[;,|]", raw))

    if _tag_value(tags, "outdoor_seating") in {"yes", "true", "1"}:
        values.append("outdoor")
    if _tag_value(tags, "dog") in {"yes", "friendly", "true", "1"}:
        values.append("pet_friendly")
    if _tag_value(tags, "child_friendly") in {"yes", "true", "1"}:
        values.append("family")
    if _tag_value(tags, "kids") in {"yes", "true", "1"}:
        values.append("family")
    if _tag_value(tags, "takeaway") == "yes" and _tag_value(tags, "delivery") == "no":
        values.append("quick_bite")

    allowed = set(GOOD_FOR_TAGS)
    return ", ".join(dict.fromkeys(v for v in values if v in allowed)) or None


def upsert_restaurant(db: Session, element: Any) -> bool:
    """Insert or update one place. Return whether a named place was upserted."""

    if not isinstance(element, dict):
        return False
    tags = element.get("tags", {})
    if not isinstance(tags, dict):
        return False
    name_value = tags.get("name", "")
    name = name_value.strip()[:255] if isinstance(name_value, str) else ""
    coordinates = _element_coordinates(element)
    source_id = _osm_source_id(element)
    if not name or coordinates is None or source_id is None:
        return False

    existing = db.query(Restaurant).filter_by(source_id=source_id).first()

    raw_cuisine_value = tags.get("cuisine")
    raw_cuisine = (
        raw_cuisine_value[:255] if isinstance(raw_cuisine_value, str) else None
    )
    cuisine_tags, type_tag, theme_id = classify_from_raw_tag(raw_cuisine)

    derived_cuisine = None
    if not raw_cuisine and cuisine_tags == "Multi-cuisine":
        derived_cuisine = _derived_cuisine(tags)
        if derived_cuisine:
            cuisine_tags = derived_cuisine
            theme_id = DERIVED_CUISINE_THEME.get(derived_cuisine, theme_id)

    # A venue type from the OSM amenity/shop tag wins over the cuisine-derived
    # guess, and carries the matching visual theme.
    venue_type = _venue_type(tags)
    if venue_type is not None:
        type_tag = venue_type
        theme_id = VENUE_THEME.get(venue_type, theme_id)

    latitude, longitude = coordinates
    address_parts = [
        tags.get("addr:housenumber", ""),
        tags.get("addr:street", ""),
        tags.get("addr:suburb", ""),
        tags.get("addr:city", "Bengaluru"),
    ]
    normalized_address_parts = [
        part.strip() for part in address_parts if isinstance(part, str) and part.strip()
    ]
    address = ", ".join(normalized_address_parts)[:500] or None
    dietary_flags = _dietary_flags(tags)
    noise_level = _noise_level(tags)
    good_for = _good_for(tags)
    accessibility_flags = _accessibility_flags(tags)

    if existing is not None:
        existing.name = name
        existing.latitude = latitude
        existing.longitude = longitude
        existing.address = address
        if existing.source == "overpass":
            existing.raw_cuisine_tag = raw_cuisine
            if raw_cuisine and cuisine_tags != "Multi-cuisine":
                existing.cuisine_tags = cuisine_tags
                if existing.type_tag == RestaurantType.unclassified:
                    existing.type_tag = type_tag
                if existing.theme_id == "multi_cuisine_default":
                    existing.theme_id = theme_id
            elif derived_cuisine and existing.cuisine_tags == "Multi-cuisine":
                # Fill in a cuisine the venue type makes obvious, but only where
                # there is nothing better recorded already.
                existing.cuisine_tags = derived_cuisine
                existing.theme_id = DERIVED_CUISINE_THEME.get(
                    derived_cuisine, existing.theme_id
                )
            if (
                venue_type is not None
                and existing.type_tag == RestaurantType.unclassified
            ):
                # Upgrade our own weak default, but never overwrite a type that
                # was set from stronger evidence or curated by hand.
                existing.type_tag = type_tag
                existing.theme_id = theme_id
            if dietary_flags:
                existing.dietary_flags = dietary_flags
            if noise_level != NoiseLevel.unknown:
                existing.noise_level = noise_level
            if good_for:
                existing.good_for = good_for
            if accessibility_flags:
                existing.accessibility_flags = accessibility_flags
    else:
        db.add(
            Restaurant(
                name=name,
                source="overpass",
                source_id=source_id,
                latitude=latitude,
                longitude=longitude,
                address=address,
                raw_cuisine_tag=raw_cuisine,
                cuisine_tags=cuisine_tags,
                type_tag=type_tag,
                dietary_flags=dietary_flags,
                theme_id=theme_id,
                noise_level=noise_level,
                good_for=good_for,
                accessibility_flags=accessibility_flags,
            )
        )
    return True


# The OSM amenity/shop is a stronger venue-type signal than a free-form cuisine
# value, and it is the only signal most places carry. Without this the venue
# filter has nothing to match: in a typical neighbourhood most places would be
# `unclassified`.
AMENITY_TYPE_MAP: dict[str, RestaurantType] = {
    "restaurant": RestaurantType.family_restaurant,
    "diner": RestaurantType.family_restaurant,
    "cafe": RestaurantType.cafe,
    "fast_food": RestaurantType.darshini_qsr,
    "bbq": RestaurantType.darshini_qsr,
    "bar": RestaurantType.bar_microbrewery,
    "pub": RestaurantType.bar_microbrewery,
    "biergarten": RestaurantType.bar_microbrewery,
    "ice_cream": RestaurantType.cafe,
    "food_court": RestaurantType.food_court_stall,
}

SHOP_TYPE_MAP: dict[str, RestaurantType] = {
    "bakery": RestaurantType.cafe,
    "coffee": RestaurantType.cafe,
    "tea": RestaurantType.cafe,
    "juice_bar": RestaurantType.cafe,
    "confectionery": RestaurantType.cafe,
    "pastry": RestaurantType.cafe,
}

# Venues whose look should follow their format rather than their cuisine.
VENUE_THEME = {
    RestaurantType.cafe: "cafe_bakery",
    RestaurantType.bar_microbrewery: "multi_cuisine_default",
    RestaurantType.food_court_stall: "street_food",
    RestaurantType.darshini_qsr: "street_food",
}


# Venues whose OSM amenity is itself a cuisine signal, used only when the place
# carries no `cuisine` tag at all. Most OSM places have none, which is why so
# many were landing on "Multi-cuisine": a shop=bakery is a bakery and
# amenity=cafe is a cafe, and that is worth recording.
#
# This is derivation, not OSM data. `raw_cuisine_tag` stays empty on these rows
# so a derived value is never mistaken for something the source actually said.
DERIVED_VENUE_CUISINE: dict[str, str] = {
    "amenity=cafe": "Cafe/Bakery",
    "shop=bakery": "Cafe/Bakery",
    "shop=coffee": "Cafe/Bakery",
    "shop=tea": "Cafe/Bakery",
    "shop=juice_bar": "Cafe/Bakery",
    "amenity=ice_cream": "Desserts & Sweets",
    "shop=confectionery": "Desserts & Sweets",
    "shop=pastry": "Desserts & Sweets",
}

# The theme vocabulary only has eight palettes, so derived cuisines borrow the
# closest existing one rather than inventing a theme id nothing can render.
DERIVED_CUISINE_THEME: dict[str, str] = {
    "Cafe/Bakery": "cafe_bakery",
    "Desserts & Sweets": "cafe_bakery",
}


def _derived_cuisine(tags: dict[str, Any]) -> str | None:
    for key in ("amenity", "shop"):
        value = _tag_value(tags, key)
        if value:
            match = DERIVED_VENUE_CUISINE.get(f"{key}={value}")
            if match:
                return match
    return None


def _venue_type(tags: dict[str, Any]) -> RestaurantType | None:
    amenity = _tag_value(tags, "amenity")
    if amenity in AMENITY_TYPE_MAP:
        return AMENITY_TYPE_MAP[amenity]
    shop = _tag_value(tags, "shop")
    if shop in SHOP_TYPE_MAP:
        return SHOP_TYPE_MAP[shop]
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest Tabiko restaurant data from OSM Overpass API"
    )
    parser.add_argument("--lat", type=float, default=12.9915, help="Center latitude")
    parser.add_argument("--lon", type=float, default=77.5520, help="Center longitude")
    parser.add_argument(
        "--radius", type=int, default=5000, help="Search radius in meters"
    )
    parser.add_argument(
        "--url", help="Use only this Overpass endpoint instead of mirrors"
    )
    parser.add_argument(
        "--attempts", type=int, default=2, help="Attempts per Overpass endpoint"
    )
    parser.add_argument(
        "--bbox",
        help=(
            "Ingest an area instead of a radius: SOUTH,WEST,NORTH,EAST. "
            "Preferred for city-scale runs, e.g. 12.75,77.45,13.15,77.80"
        ),
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing overpass rows in the area before ingesting",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if not -90 <= args.lat <= 90 or not -180 <= args.lon <= 180:
        parser.error("--lat and --lon must be valid geographic coordinates")
    if not 1 <= args.radius <= 25_000:
        parser.error("--radius must be between 1 and 25000 meters")
    if not 1 <= args.attempts <= 5:
        parser.error("--attempts must be between 1 and 5")

    bbox: tuple[float, float, float, float] | None = None
    if args.bbox:
        parts = args.bbox.split(",")
        if len(parts) != 4:
            parser.error("--bbox must be SOUTH,WEST,NORTH,EAST")
        try:
            south, west, north, east = (float(part) for part in parts)
        except ValueError:
            parser.error("--bbox values must be numbers")
        if not -90 <= south < north <= 90 or not -180 <= west < east <= 180:
            parser.error("--bbox must be SOUTH<NORTH and WEST<EAST within valid ranges")
        bbox = (south, west, north, east)

    Base.metadata.create_all(bind=engine)
    endpoints = [args.url] if args.url else None

    if bbox is not None:
        print(f"Fetching places inside bbox {bbox}...", flush=True)
        try:
            elements = fetch_elements(
                build_bbox_query(*bbox),
                urls=endpoints,
                attempts_per_url=args.attempts,
                request_timeout=300.0,
            )
        except requests.RequestException as exc:
            print(f"Overpass request failed: {exc}", file=sys.stderr)
            return 1
    else:
        print(
            f"Fetching places within {args.radius}m of ({args.lat}, {args.lon})...",
            flush=True,
        )
        try:
            elements = fetch_places(
                args.lat,
                args.lon,
                args.radius,
                urls=endpoints,
                attempts_per_url=args.attempts,
            )
        except requests.RequestException as exc:
            print(f"Overpass request failed: {exc}", file=sys.stderr)
            return 1

    print(
        f"Got {len(elements)} raw OSM elements. Filtering and upserting...",
        flush=True,
    )
    count = 0
    seen_source_ids: set[str] = set()
    db = SessionLocal()
    try:
        if args.replace and bbox is not None:
            south, west, north, east = bbox
            removed = (
                db.query(Restaurant)
                .filter(
                    Restaurant.source == "overpass",
                    Restaurant.latitude >= south,
                    Restaurant.latitude <= north,
                    Restaurant.longitude >= west,
                    Restaurant.longitude <= east,
                )
                .delete(synchronize_session=False)
            )
            db.commit()
            print(f"Removed {removed} existing rows inside the bbox.", flush=True)

        for element in elements:
            source_id = _osm_source_id(element)
            if source_id is not None and source_id in seen_source_ids:
                continue
            if source_id is not None:
                seen_source_ids.add(source_id)
            if upsert_restaurant(db, element):
                count += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(f"Done. Upserted {count} named restaurants/venues.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
