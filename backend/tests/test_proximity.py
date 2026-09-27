"""Proximity and radius behaviour.

With a whole city of places loaded, "what is near me" has to be a real query,
not something the client guesses. Distance is computed server-side so the cards,
the map, and any future client all agree on the numbers.
"""

import pytest

from app.models import Restaurant

# Three places stepping east from the origin by roughly 0.001 degrees longitude
# (~104 m at this latitude), so ordering is unambiguous.
PROXIMITY_PLACES = [
    ("Near One", 12.9900, 77.5500),
    ("Near Two", 12.9900, 77.5510),
    ("Far Away", 12.9900, 77.6000),
]


@pytest.fixture
def proximity_data(session_factory):
    with session_factory() as db:
        for index, (name, lat, lon) in enumerate(PROXIMITY_PLACES):
            db.add(
                Restaurant(
                    name=name,
                    source="test",
                    source_id=f"prox-{index}",
                    latitude=lat,
                    longitude=lon,
                    cuisine_tags="Multi-cuisine",
                )
            )
        db.commit()


ORIGIN = {"origin_lat": 12.9900, "origin_lon": 77.5500}


def test_distance_sort_puts_the_closest_place_first(client, proximity_data):
    response = client.get("/restaurants", params={**ORIGIN, "sort": "distance"})

    assert response.status_code == 200
    names = [row["name"] for row in response.json()]
    assert names == ["Near One", "Near Two", "Far Away"]


def test_distance_is_reported_and_monotonic(client, proximity_data):
    rows = client.get("/restaurants", params={**ORIGIN, "sort": "distance"}).json()

    distances = [row["distance_m"] for row in rows]
    assert distances[0] < 1
    assert 100 < distances[1] < 130
    assert distances[1] < distances[2]
    assert rows[2]["distance_m"] > 4000


def test_radius_filters_out_distant_places(client, proximity_data):
    response = client.get(
        "/restaurants", params={**ORIGIN, "sort": "distance", "radius_m": 500}
    )

    assert response.status_code == 200
    assert [row["name"] for row in response.json()] == ["Near One", "Near Two"]


def test_total_count_header_reports_matches_before_paging(client, proximity_data):
    response = client.get(
        "/restaurants",
        params={**ORIGIN, "sort": "distance", "limit": 1, "radius_m": 500},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.headers["X-Total-Count"] == "2"


def test_name_sort_is_unchanged_without_an_origin(client, proximity_data):
    response = client.get("/restaurants", params={"sort": "name"})

    assert [row["name"] for row in response.json()] == [
        "Far Away",
        "Near One",
        "Near Two",
    ]
    assert response.json()[0]["distance_m"] is None


def test_distance_sort_requires_an_origin(client, proximity_data):
    response = client.get("/restaurants", params={"sort": "distance"})

    assert response.status_code == 422
    assert "origin_lat" in response.json()["detail"]


def test_radius_requires_an_origin(client, proximity_data):
    response = client.get("/restaurants", params={"radius_m": 500})

    assert response.status_code == 422
    assert "origin_lat" in response.json()["detail"]


def test_half_a_origin_pair_is_rejected(client, proximity_data):
    response = client.get("/restaurants", params={"origin_lat": 12.99})

    assert response.status_code == 422
    assert "supplied together" in response.json()["detail"]


def test_unknown_sort_value_is_rejected(client, proximity_data):
    assert client.get("/restaurants", params={"sort": "random"}).status_code == 422


def test_proximity_combines_with_other_filters(client, session_factory):
    with session_factory() as db:
        db.add_all(
            [
                Restaurant(
                    name="Close Cafe",
                    source="test",
                    source_id="prox-cafe",
                    latitude=12.9900,
                    longitude=77.5500,
                    cuisine_tags="Cafe/Bakery",
                ),
                Restaurant(
                    name="Close Diner",
                    source="test",
                    source_id="prox-diner",
                    latitude=12.9901,
                    longitude=77.5501,
                    cuisine_tags="Multi-cuisine",
                ),
            ]
        )
        db.commit()

    response = client.get("/restaurants", params={**ORIGIN, "cuisine": "Cafe/Bakery"})

    assert [row["name"] for row in response.json()] == ["Close Cafe"]


def test_search_combines_with_proximity(client, session_factory):
    with session_factory() as db:
        db.add_all(
            [
                Restaurant(
                    name="Filter Coffee Bar",
                    source="test",
                    source_id="prox-search-1",
                    latitude=12.9900,
                    longitude=77.5500,
                ),
                Restaurant(
                    name="Biryani Palace",
                    source="test",
                    source_id="prox-search-2",
                    latitude=12.9901,
                    longitude=77.5501,
                ),
            ]
        )
        db.commit()

    response = client.get(
        "/restaurants", params={**ORIGIN, "search": "biryani", "sort": "distance"}
    )

    assert [row["name"] for row in response.json()] == ["Biryani Palace"]
