import sys
from unittest.mock import Mock, patch

import pytest
import requests

import app.ingestion.overpass_ingest as ingestion
from app.ingestion.overpass_ingest import (
    FOOD_TAGS,
    USER_AGENT,
    build_query,
    fetch_places,
    upsert_restaurant,
)
from app.models import Restaurant, RestaurantType


def test_build_query_includes_nodes_ways_relations_and_centers():
    query = build_query(12.9716, 77.5946, 2_000)

    # One clause per food tag, and every configured tag must be requested.
    assert query.count("nwr[") == len(FOOD_TAGS)
    for food_tag in FOOD_TAGS:
        assert f"nwr[{food_tag}](around:2000,12.9716,77.5946);" in query
    assert "out center;" in query


def test_fetch_places_uses_user_agent_and_falls_back_after_server_error():
    unavailable = Mock(status_code=504, text="busy")
    available = Mock(status_code=200)
    available.json.return_value = {"elements": [{"type": "node", "id": 1}, "malformed"]}

    with patch(
        "app.ingestion.overpass_ingest.requests.post",
        side_effect=[unavailable, available],
    ) as post:
        elements = fetch_places(
            12.97,
            77.59,
            500,
            urls=["https://primary.example/api", "https://mirror.example/api"],
            attempts_per_url=1,
            backoff_seconds=0,
        )

    assert elements == [{"type": "node", "id": 1}]
    assert post.call_count == 2
    assert post.call_args_list[0].kwargs["headers"]["User-Agent"] == USER_AGENT


def test_fetch_places_raises_a_clear_error_for_invalid_payload():
    invalid = Mock(status_code=200)
    invalid.json.return_value = {"message": "no data"}

    with (
        patch("app.ingestion.overpass_ingest.requests.post", return_value=invalid),
        pytest.raises(requests.RequestException, match="no elements list"),
    ):
        fetch_places(
            12.97,
            77.59,
            500,
            urls=["https://primary.example/api"],
            attempts_per_url=1,
        )


def test_fetch_places_rejects_partial_overpass_responses():
    partial = Mock(status_code=200)
    partial.json.return_value = {
        "elements": [{"type": "node", "id": 1}],
        "remark": "runtime error: query timed out",
    }

    with (
        patch("app.ingestion.overpass_ingest.requests.post", return_value=partial),
        pytest.raises(requests.RequestException, match="partial Overpass response"),
    ):
        fetch_places(
            12.97,
            77.59,
            500,
            urls=["https://primary.example/api"],
            attempts_per_url=1,
        )


def test_upsert_supports_way_centers_and_updates_existing_places(session_factory):
    element = {
        "type": "way",
        "id": 42,
        "center": {"lat": 13.01, "lon": 77.02},
        "tags": {
            "name": "Test Bakery",
            "shop": "bakery",
            "cuisine": "bakery; coffee_shop",
            "diet:vegetarian": "yes",
        },
    }

    with session_factory() as db:
        assert upsert_restaurant(db, element) is True
        db.commit()
        created = db.query(Restaurant).one()

    element["center"] = {"lat": 13.011, "lon": 77.021}
    with session_factory() as db:
        assert upsert_restaurant(db, element) is True
        db.commit()
        updated = db.query(Restaurant).one()

    assert created.source_id == "osm-way-42"
    assert created.latitude == 13.01
    assert updated.latitude == 13.011
    assert updated.type_tag == RestaurantType.cafe
    assert updated.theme_id == "cafe_bakery"
    assert updated.dietary_flags == "veg"


def test_venue_type_comes_from_the_osm_amenity_not_just_cuisine(session_factory):
    # Most places carry no cuisine tag, so a cuisine-only classifier leaves the
    # venue filter with almost nothing to match.
    cases = [
        ({"amenity": "restaurant"}, RestaurantType.family_restaurant),
        ({"amenity": "diner"}, RestaurantType.family_restaurant),
        ({"amenity": "fast_food"}, RestaurantType.darshini_qsr),
        ({"amenity": "cafe"}, RestaurantType.cafe),
        ({"amenity": "bar"}, RestaurantType.bar_microbrewery),
        ({"amenity": "pub"}, RestaurantType.bar_microbrewery),
        ({"amenity": "food_court"}, RestaurantType.food_court_stall),
        ({"shop": "bakery"}, RestaurantType.cafe),
        ({"shop": "coffee"}, RestaurantType.cafe),
    ]

    with session_factory() as db:
        for index, (tags, expected) in enumerate(cases):
            upsert_restaurant(
                db,
                {
                    "type": "node",
                    "id": 900 + index,
                    "lat": 12.99,
                    "lon": 77.55,
                    "tags": {"name": f"Place {index}", **tags},
                },
            )
        db.commit()
        stored = {r.name: r.type_tag for r in db.query(Restaurant).all()}

    for index, (_, expected) in enumerate(cases):
        assert stored[f"Place {index}"] == expected


def test_reingestion_upgrades_a_previously_unclassified_venue(session_factory):
    element = {
        "type": "node",
        "id": 777,
        "lat": 12.99,
        "lon": 77.55,
        "tags": {"name": "Late Tagging Diner", "cuisine": "regional"},
    }

    with session_factory() as db:
        upsert_restaurant(db, element)
        db.commit()
        assert db.query(Restaurant).one().type_tag == RestaurantType.unclassified

    element["tags"]["amenity"] = "restaurant"
    with session_factory() as db:
        upsert_restaurant(db, element)
        db.commit()
        assert db.query(Restaurant).one().type_tag == RestaurantType.family_restaurant


def test_upsert_skips_unnamed_or_unlocated_elements(session_factory):
    with session_factory() as db:
        assert (
            upsert_restaurant(db, {"type": "node", "id": 1, "lat": 1, "lon": 2})
            is False
        )
        assert (
            upsert_restaurant(
                db, {"type": "way", "id": 2, "tags": {"name": "No point"}}
            )
            is False
        )


def test_ingestion_deduplicates_duplicate_source_ids(
    session_factory, db_engine, monkeypatch
):
    element = {
        "type": "node",
        "id": 99,
        "lat": 13.0,
        "lon": 77.0,
        "tags": {"name": "Duplicate OSM Place", "amenity": "restaurant"},
    }
    monkeypatch.setattr(ingestion, "engine", db_engine)
    monkeypatch.setattr(ingestion, "SessionLocal", session_factory)
    monkeypatch.setattr(
        ingestion, "fetch_places", lambda *args, **kwargs: [element, element]
    )
    monkeypatch.setattr(sys, "argv", ["overpass_ingest", "--radius", "500"])

    assert ingestion.main() == 0
    with session_factory() as db:
        assert db.query(Restaurant).count() == 1


def test_reingestion_without_evidence_preserves_curated_fields(session_factory):
    original = {
        "type": "node",
        "id": 100,
        "lat": 13.0,
        "lon": 77.0,
        "tags": {
            "name": "Curated Place",
            "cuisine": "italian",
            "diet:vegetarian": "yes",
        },
    }
    with session_factory() as db:
        assert upsert_restaurant(db, original) is True
        db.commit()
        restaurant = db.query(Restaurant).one()
        restaurant.cuisine_tags = "Italian"
        restaurant.type_tag = RestaurantType.fine_dine
        restaurant.dietary_flags = "vegan"
        restaurant.theme_id = "fine_dine"
        db.commit()

        sparse_refresh = {
            "type": "node",
            "id": 100,
            "lat": 13.001,
            "lon": 77.001,
            "tags": {"name": "Curated Place"},
        }
        assert upsert_restaurant(db, sparse_refresh) is True
        db.commit()
        db.refresh(restaurant)

        assert restaurant.cuisine_tags == "Italian"
        assert restaurant.type_tag == RestaurantType.fine_dine
        assert restaurant.dietary_flags == "vegan"
        assert restaurant.theme_id == "fine_dine"
