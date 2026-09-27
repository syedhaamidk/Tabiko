"""
Pulls restaurants/cafes/fast_food nodes from OpenStreetMap via the Overpass
API, bounded to a radius around a center point in Bengaluru, and upserts
them into the local DB with a first-pass classification.

Usage:
    python -m app.ingestion.overpass_ingest --lat 13.1682 --lon 77.5354 --radius 5000

Default center is Presidency University, Rajanakunte, Bengaluru.
Radius is in meters. Start small (3000-5000m) to keep the dataset dense
and manageable while you're seeding your first real reviews.
"""

import argparse
import sys
import time

import requests

from ..database import Base, SessionLocal, engine
from ..classifier import classify_from_raw_tag
from ..models import Restaurant

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# OSM amenity/shop tags worth pulling in for a food-discovery app
FOOD_TAGS = ["amenity=restaurant", "amenity=cafe", "amenity=fast_food", "amenity=bar", "shop=bakery"]


def build_query(lat: float, lon: float, radius_m: int) -> str:
    clauses = "\n".join(f'  node[{tag}](around:{radius_m},{lat},{lon});' for tag in FOOD_TAGS)
    return f"""
    [out:json][timeout:60];
    (
    {clauses}
    );
    out body;
    """


def fetch_places(lat: float, lon: float, radius_m: int) -> list[dict]:
    query = build_query(lat, lon, radius_m)
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=90)
    resp.raise_for_status()
    return resp.json().get("elements", [])


def upsert_restaurant(db, element: dict) -> None:
    tags = element.get("tags", {})
    name = tags.get("name")
    if not name:
        return  # skip unnamed nodes, not useful for discovery

    source_id = f"osm-{element['id']}"
    existing = db.query(Restaurant).filter_by(source_id=source_id).first()

    raw_cuisine = tags.get("cuisine")
    cuisine_tags, type_tag, theme_id = classify_from_raw_tag(raw_cuisine)

    # amenity=cafe / shop=bakery override the classifier's type guess,
    # since OSM's own amenity tag is more reliable than the free-text cuisine field
    if tags.get("amenity") == "cafe" or tags.get("shop") == "bakery":
        from ..models import RestaurantType
        type_tag = RestaurantType.cafe
        theme_id = "cafe_bakery"

    address_parts = [
        tags.get("addr:housenumber", ""),
        tags.get("addr:street", ""),
        tags.get("addr:suburb", ""),
        tags.get("addr:city", "Bengaluru"),
    ]
    address = ", ".join(p for p in address_parts if p) or None

    if existing:
        existing.name = name
        existing.latitude = element["lat"]
        existing.longitude = element["lon"]
        existing.address = address
        existing.raw_cuisine_tag = raw_cuisine
        existing.cuisine_tags = cuisine_tags
        existing.type_tag = type_tag
        existing.theme_id = theme_id
    else:
        db.add(
            Restaurant(
                name=name,
                source="overpass",
                source_id=source_id,
                latitude=element["lat"],
                longitude=element["lon"],
                address=address,
                raw_cuisine_tag=raw_cuisine,
                cuisine_tags=cuisine_tags,
                type_tag=type_tag,
                theme_id=theme_id,
            )
        )


def main():
    parser = argparse.ArgumentParser(description="Ingest Bengaluru restaurant data from OSM Overpass API")
    parser.add_argument("--lat", type=float, default=13.1682, help="Center latitude (default: Presidency University)")
    parser.add_argument("--lon", type=float, default=77.5354, help="Center longitude")
    parser.add_argument("--radius", type=int, default=5000, help="Search radius in meters")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    print(f"Fetching places within {args.radius}m of ({args.lat}, {args.lon})...")
    try:
        elements = fetch_places(args.lat, args.lon, args.radius)
    except requests.RequestException as e:
        print(f"Overpass request failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Got {len(elements)} raw nodes from OSM. Filtering + upserting...")
    count = 0
    for el in elements:
        if el.get("type") != "node":
            continue
        upsert_restaurant(db, el)
        count += 1

    db.commit()
    db.close()
    print(f"Done. Upserted {count} candidate restaurants (unnamed nodes skipped).")


if __name__ == "__main__":
    main()
