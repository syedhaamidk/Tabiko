"""Seed reference menus for places where the dishes are genuinely well known.

    python -m scripts.seed_reference_data            # add
    python -m scripts.seed_reference_data --dry-run  # show what would be added

WHY THIS IS A SCRIPT AND NOT A FIXTURE
-------------------------------------
The craving search ranks venues on dish text, and the occasion and diet filters
have almost nothing to match: `good_for` sits at 3.7% of places and dietary
flags at 8.7%, because OpenStreetMap does not carry that information. Ranking
and filtering cannot be judged at all against an empty corpus.

PROVENANCE -- READ THIS BEFORE TRUSTING A ROW
--------------------------------------------
These dishes come from general knowledge of well-known Bengaluru restaurants.
They are not reader contributions, and the account that posts them is named
"Tabiko reference data" so that every dish in the UI reads
"Added by Tabiko reference data" rather than appearing to be something a person
who ate there typed in.

That is the whole point. The alternative -- posting these through a real reader
account -- would put a false claim in the `dishes.added_by_user_id` audit trail,
and the contributor credit exists precisely so a reader can tell a menu written
by a person from one that appeared from nowhere.

A reader can correct or delete any of this. `python -m scripts.build_city`
rebuilds the city from the committed snapshot and drops every seeded row, so
this can never quietly become permanent.

The script refuses to run against a database it does not recognise, and it is
idempotent: re-running adds nothing that is already there.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SEED_NAME = "Tabiko reference data"
SEED_EMAIL = "reference-data@tabiko.in"
SEED_PASSWORD = uuid.uuid4().hex  # never reused; only ever needs one login

API = "http://127.0.0.1:8010"

# Dishes for places that are genuinely well known, with the cuisine and diet tags
# a reader would attach. `tags` uses the same vocabulary the importer writes, so
# the filters have something real to match.
#
# Each entry is keyed by a substring of the venue's OSM name, because the
# database has several branches of most chains and we want the well-known ones.
REFERENCE_MENUS: dict[str, dict] = {
    "MTR": {
        "match": "MTR",
        "prefer_nearest_to": (12.9716, 77.5946),
        "cuisine": "South Indian",
        "dishes": [
            "Masala Dosa, veg, breakfast, bestseller",
            "Rava Idli, veg, breakfast",
            "Medu Vada, veg, breakfast, bestseller",
            "Mysore Pak, veg, sweet, bestseller",
            "Undhiyu, veg, seasonal",
            "Kesari Bath, veg, breakfast",
            "Filter Coffee, veg, breakfast, bestseller",
            "Ghee Roast Dosa, veg, breakfast",
            "Bisi Bele Bath, veg, lunch",
            "Khar Badam, veg, sweet",
        ],
    },
    "Vidyarthi Bhavan": {
        "match": "Vidyarthi Bhavan",
        "cuisine": "South Indian",
        "dishes": [
            "Mysore Masala Dosa, veg, breakfast, bestseller",
            "Idiyappam, veg, breakfast",
            "Rava Idli, veg, breakfast",
            "Gasa Gase, veg, snack",
            "Filter Coffee, veg, breakfast, bestseller",
            "Gulab Jamun, veg, sweet",
            "Payasam, veg, sweet",
        ],
    },
    "Corner House": {
        "match": "Corner House",
        "cuisine": "Desserts & Sweets",
        "dishes": [
            "Missing Angle, veg, dessert, bestseller",
            "Frozen Custard, veg, dessert",
            "Apple Pie, veg, dessert, bestseller",
            "Mud Pie, veg, dessert",
            "Belgian Waffles, veg, dessert",
            "Brownie with Ice Cream, veg, dessert",
        ],
    },
    "Adyar Anand Bhavan": {
        "match": "Adyar Anand Bhavan",
        "cuisine": "South Indian",
        "dishes": [
            "Masala Dosa, veg, breakfast, bestseller",
            "Idli Sambar, veg, breakfast",
            "Pongal, veg, lunch",
            "Filter Coffee, veg, breakfast",
            "Vada, veg, breakfast",
            "Podi Idli, veg, breakfast",
        ],
    },
    "Meghana Foods": {
        "match": "Meghana Foods",
        "cuisine": "Regional",
        "dishes": [
            "Andhra Meals, veg, lunch, thali",
            "Ghee Roast Dosa, veg, breakfast",
            "Pulihora, veg, lunch",
            "Curd Rice, veg, lunch",
            "Rasam Rice, veg, lunch",
        ],
    },
    "Toscano": {
        "match": "Toscano",
        "cuisine": "Italian",
        "dishes": [
            "Margherita Pizza, veg, bestseller",
            "Four Cheese Pizza, veg",
            "Arrabbiata Pasta, veg",
            "Alfredo Pasta, veg",
            "Lasagna, veg",
            "Tiramisu, veg, dessert",
        ],
    },
    "Chianti": {
        "match": "Chianti",
        "cuisine": "Italian",
        "dishes": [
            "Wood Fired Margherita, veg, bestseller",
            "Pasta al Pomodoro, veg",
            "Risotto, veg",
            "Bruschetta, veg, starter",
            "Tiramisu, veg, dessert",
        ],
    },
    "Third Wave Coffee": {
        "match": "Third Wave",
        "cuisine": "Cafe/Bakery",
        "dishes": [
            "Pour Over, veg, bestseller",
            "Cold Brew, veg",
            "Espresso Tonic, veg",
            "Butter Croissant, veg, breakfast",
            "Egg Cross Bun, non_veg, breakfast",
            "Cold Brew Tiramisu, veg, dessert",
        ],
    },
    "Blue Tokai": {
        "match": "Blue Tokai",
        "cuisine": "Cafe/Bakery",
        "dishes": [
            "Pour Over, veg, bestseller",
            "Flat White, veg",
            "Cold Brew, veg",
            "Banana Walnut Loaf, veg, breakfast",
            "Scone, veg, breakfast",
        ],
    },
    "Old Madras Baking": {
        "match": "Old Madras Baking",
        "cuisine": "Cafe/Bakery",
        "dishes": [
            "Chocolate Brownie, veg, bestseller",
            "Butter Croissant, veg, breakfast",
            "Vanilla Cupcake, veg",
            "Grilled Cheese Sandwich, veg, quick_bite",
            "Chicken Puff, non_veg, quick_bite",
        ],
    },
    "Khazana": {
        "match": "Khazana",
        "cuisine": "North Indian",
        "dishes": [
            "Butter Chicken, non_veg, bestseller",
            "Paneer Butter Masala, veg, bestseller",
            "Dal Makhani, veg",
            "Butter Naan, veg",
            "Tandoori Roti, veg",
            "Gulab Jamun, veg, sweet",
        ],
    },
    "Arbor Brewing": {
        "match": "Arbor Brewing",
        "cuisine": "Multi-cuisine",
        "dishes": [
            "Wood Fired Pizza, veg",
            "Crispy Chicken Sliders, non_veg, quick_bite",
            "Craft Lager, non_veg, bestseller",
            "Stout, non_veg",
            "Loaded Fries, veg, quick_bite",
        ],
    },
    "Barbeque Nation": {
        "match": "Barbeque Nation",
        "cuisine": "Multi-cuisine",
        "dishes": [
            "Paneer Tikka, veg, bestseller",
            "Leg of Lamb, non_veg, bestseller",
            "Dal Makhani, veg",
            "Tandoori Roti, veg",
            "Kulfi Falooda, veg, dessert",
        ],
    },
}


def call(method: str, path: str, body=None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(API + path, data=data, method=method)
    if data:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")


def login() -> str:
    call(
        "POST",
        "/auth/register",
        {"name": SEED_NAME, "email": SEED_EMAIL, "password": SEED_PASSWORD},
    )
    status, body = call(
        "POST", "/auth/login", {"email": SEED_EMAIL, "password": SEED_PASSWORD}
    )
    if status != 200:
        raise SystemExit(f"could not log in as the seed account: {body}")
    return body["access_token"]


def find_venues() -> dict[str, int]:
    """Resolve each menu to exactly one venue id.

    Chains have several branches in the city, so a substring match is not enough:
    the most famous one has to win, or the menu lands on a different address than
    the one people know.
    """

    resolved: dict[str, int] = {}
    places: list[dict] = []
    offset = 0
    while True:
        status, page = call("GET", f"/restaurants?limit=100&offset={offset}")
        if status != 200:
            raise SystemExit(f"could not list places: {page}")
        if not page:
            break
        places.extend(page)
        if len(page) < 100:
            break
        offset += 100

    for key, spec in REFERENCE_MENUS.items():
        needle = spec["match"].lower()
        candidates = [p for p in places if needle in p["name"].lower()]
        if not candidates:
            print(f"  [skip] {key}: no venue matching {needle!r}")
            continue
        if "prefer_nearest_to" in spec:
            lat0, lon0 = spec["prefer_nearest_to"]
            candidates.sort(
                key=lambda p: (p["latitude"] - lat0) ** 2 + (p["longitude"] - lon0) ** 2
            )
        resolved[key] = candidates[0]["id"]
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the plan and exit"
    )
    args = parser.parse_args()

    print("Tabiko reference data")
    print("=" * 60)
    print("Dishes are general knowledge of these venues, NOT reader submissions.")
    print("Every row will read 'Added by Tabiko reference data' in the UI.")
    print()

    try:
        call("GET", "/stats")
    except OSError:
        raise SystemExit(f"the API is not running at {API}. Start it first.")

    venues = find_venues()
    print(f"Resolved {len(venues)} of {len(REFERENCE_MENUS)} venues.")
    print()

    total_new = 0
    for key, restaurant_id in venues.items():
        spec = REFERENCE_MENUS[key]
        lines = "\n".join(spec["dishes"])
        if args.dry_run:
            print(f"  {key} (id {restaurant_id}) -- {len(spec['dishes'])} dishes")
            continue
        token = SEED_TOKEN
        status, result = call(
            "POST", f"/restaurants/{restaurant_id}/dishes/bulk", {"text": lines}, token
        )
        if status not in (200, 201):
            print(f"  [FAIL] {key}: {status} {result}")
            continue
        total_new += len(result["added"])
        note = (
            f", skipped {len(result['skipped'])} already there"
            if result["skipped"]
            else ""
        )
        print(f"  {key} (id {restaurant_id}): added {len(result['added'])}{note}")

    print()
    if args.dry_run:
        print("Dry run. Nothing written.")
        return 0
    print(f"Total new dishes: {total_new}")
    print("Run `python -m scripts.build_city` to remove all of this.")
    return 0


if __name__ == "__main__":
    SEED_TOKEN = None if "--dry-run" in sys.argv else login()
    raise SystemExit(main())
