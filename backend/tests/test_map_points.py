"""Contract tests for the lightweight map-points endpoint.

The map draws every place in the filtered set, so this endpoint carries the
bulk of the data. Two things matter: it must never be larger than it needs to
be, and it must agree with /restaurants about what a filter means.
"""

from app import models
from app.models import Restaurant

PLACES = [
    ("Point Cafe", 12.99, 77.55, "Cafe/Bakery", models.RestaurantType.cafe, "veg"),
    (
        "Point Biryani",
        12.97,
        77.60,
        "Biryani",
        models.RestaurantType.family_restaurant,
        None,
    ),
    (
        "Point Diner",
        13.10,
        77.45,
        "Multi-cuisine",
        models.RestaurantType.darshini_qsr,
        None,
    ),
]


def _seed(session_factory) -> None:
    with session_factory() as db:
        for name, lat, lon, cuisine, venue, diet in PLACES:
            db.add(
                Restaurant(
                    name=name,
                    source="test",
                    source_id=f"test-{name}",
                    latitude=lat,
                    longitude=lon,
                    cuisine_tags=cuisine,
                    type_tag=venue,
                    dietary_flags=diet,
                )
            )
        db.commit()


def test_points_returns_every_place_without_paging(client, session_factory):
    _seed(session_factory)

    response = client.get("/restaurants/points")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 3
    assert {row["name"] for row in payload} == {
        "Point Cafe",
        "Point Biryani",
        "Point Diner",
    }


def test_point_payload_carries_only_what_the_map_needs(client, session_factory):
    _seed(session_factory)

    row = client.get("/restaurants/points").json()[0]

    # A full RestaurantOut row is several times the size; the map must not pay
    # for addresses, review counts, or hygiene scores.
    assert set(row) == {
        "id",
        "name",
        "latitude",
        "longitude",
        "cuisine_tags",
        "type_tag",
        "distance_m",
    }
    for heavy in ("address", "hygiene_score", "theme_id", "accessibility_flags"):
        assert heavy not in row
    # No origin was supplied, so there is no distance to report.
    assert row["distance_m"] is None


def test_points_report_distance_when_given_an_origin(client, session_factory):
    _seed(session_factory)

    response = client.get(
        "/restaurants/points",
        params={"origin_lat": 12.99, "origin_lon": 77.55, "sort": "distance"},
    )

    assert response.status_code == 200
    rows = response.json()
    assert rows[0]["name"] == "Point Cafe"
    # The cafe sits on the origin, so its distance rounds to ~0 m.
    assert rows[0]["distance_m"] < 1
    distances = [row["distance_m"] for row in rows]
    assert distances == sorted(distances)


def test_points_and_restaurants_agree_on_filters(client, session_factory):
    _seed(session_factory)

    for query in (
        {"cuisine": "Biryani"},
        {"type_tag": "cafe"},
        {"dietary": "veg"},
        {"good_for": "outdoor"},
        {"search": "diner"},
    ):
        points = client.get("/restaurants/points", params=query).json()
        full = client.get("/restaurants", params={**query, "limit": 100}).json()
        assert {row["id"] for row in points} == {row["id"] for row in full}, query


def test_points_and_restaurants_agree_on_a_radius(client, session_factory):
    _seed(session_factory)

    query = {"origin_lat": 12.99, "origin_lon": 77.55, "radius_m": 400}
    points = client.get("/restaurants/points", params=query).json()
    full = client.get("/restaurants", params={**query, "limit": 100}).json()

    assert {row["id"] for row in points} == {row["id"] for row in full}


def test_points_support_a_bounding_box(client, session_factory):
    _seed(session_factory)

    response = client.get(
        "/restaurants/points",
        params={"south": 12.98, "west": 77.54, "north": 13.0, "east": 77.56},
    )

    assert response.status_code == 200
    assert [row["name"] for row in response.json()] == ["Point Cafe"]


def test_a_bounding_box_returns_the_same_ids_as_the_unbounded_query(
    client, session_factory
):
    """The viewport path is served from a cache, so it must not disagree.

    The map is built from a bounded request, and so is every assertion a reader
    makes about it, but the unbounded path is what the counts and the cards are
    checked against. If the two drifted, the map would quietly be a different
    dataset from the list beside it.
    """

    _seed(session_factory)
    box = {"south": 12.9, "west": 77.5, "north": 13.05, "east": 77.6}

    bounded = client.get("/restaurants/points", params=box).json()
    everything = client.get("/restaurants/points").json()

    assert {row["id"] for row in bounded} <= {row["id"] for row in everything}
    assert len(bounded) < len(everything)


def test_a_bounding_box_honours_every_filter(client, session_factory):
    _seed(session_factory)
    box = {"south": 12.9, "west": 77.5, "north": 13.05, "east": 77.6}

    for params in ({"cuisine": "Biryani"}, {"type_tag": "cafe"}, {"dietary": "veg"}):
        bounded = client.get("/restaurants/points", params={**box, **params}).json()
        unbounded = client.get("/restaurants/points", params=params).json()
        assert {row["id"] for row in bounded} == {row["id"] for row in unbounded}, (
            params
        )


def test_a_bounding_box_ranks_by_distance_when_given_an_origin(client, session_factory):
    _seed(session_factory)

    response = client.get(
        "/restaurants/points",
        params={
            "south": 12.9,
            "west": 77.5,
            "north": 13.05,
            "east": 77.6,
            "origin_lat": 12.99,
            "origin_lon": 77.55,
            "sort": "distance",
        },
    )

    rows = response.json()
    assert response.status_code == 200
    distances = [row["distance_m"] for row in rows]
    assert distances == sorted(distances)
    assert rows[0]["name"] == "Point Cafe"


def test_a_bounding_box_applies_a_radius(client, session_factory):
    _seed(session_factory)
    box = {"south": 12.9, "west": 77.5, "north": 13.05, "east": 77.6}

    response = client.get(
        "/restaurants/points",
        params={
            **box,
            "origin_lat": 12.99,
            "origin_lon": 77.55,
            "radius_m": 300,
            "sort": "distance",
        },
    )

    assert response.status_code == 200
    assert [row["name"] for row in response.json()] == ["Point Cafe"]


def test_a_bounding_box_still_rejects_a_distance_order_without_an_origin(
    client, session_factory
):
    _seed(session_factory)
    box = {"south": 12.9, "west": 77.5, "north": 13.05, "east": 77.6}

    response = client.get("/restaurants/points", params={**box, "sort": "distance"})

    assert response.status_code == 422
    assert "origin_lat" in response.json()["detail"]


def test_partial_bounding_box_is_rejected(client, session_factory):
    _seed(session_factory)

    response = client.get("/restaurants/points", params={"south": 12.98})

    assert response.status_code == 422
    assert "supplied together" in response.json()["detail"]


def test_points_route_is_not_shadowed_by_the_id_route(client, session_factory):
    # "points" must never be parsed as a restaurant id.
    response = client.get("/restaurants/points")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_points_reject_an_unknown_venue_type(client, session_factory):
    _seed(session_factory)

    response = client.get("/restaurants/points", params={"type_tag": "food_truck"})

    assert response.status_code == 422


def test_points_respect_the_declared_limit(client, session_factory):
    _seed(session_factory)

    response = client.get("/restaurants/points", params={"limit": 2})

    assert response.status_code == 200
    assert len(response.json()) == 2
    assert client.get("/restaurants/points", params={"limit": 0}).status_code == 422
