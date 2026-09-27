"""Contract tests for the published filter vocabulary.

The frontend builds its dropdown menus from GET /filter-options. These tests make
sure every value the endpoint advertises is actually accepted by the
/restaurants filters, so a menu can never offer an option the API would reject.
"""

from app import classifier, models, schemas

VOCABULARY_GROUPS = ("cuisine", "type_tag", "dietary", "good_for", "accessibility")


def test_filter_options_expose_every_group(client):
    response = client.get("/filter-options")

    assert response.status_code == 200
    payload = response.json()
    assert set(VOCABULARY_GROUPS) <= set(payload)
    for group in VOCABULARY_GROUPS:
        values = payload[group]
        assert values, f"{group} must not be empty"
        assert len(values) == len(set(values)), f"{group} contains duplicates"


def test_every_advertised_group_has_a_count_for_every_value(client):
    """A count is what stops the menu advertising a filter that cannot match.

    The vocabulary is a promise, and 22 of the 51 values it used to publish had no
    rows at all. Every value must therefore be present in `counts`, including the
    ones at zero — a missing key would read as "unknown" rather than "none".
    """

    payload = client.get("/filter-options").json()

    assert "counts" in payload
    for group in VOCABULARY_GROUPS:
        counts = payload["counts"][group]
        assert set(counts) == set(payload[group]), group
        assert all(isinstance(value, int) and value >= 0 for value in counts.values())


def test_counts_match_what_the_filter_actually_returns(client, session_factory):
    from app.models import Restaurant

    with session_factory() as db:
        db.add_all(
            [
                Restaurant(
                    name="Counted Cafe",
                    source="test",
                    source_id="count-1",
                    latitude=12.99,
                    longitude=77.55,
                    cuisine_tags="Cafe/Bakery",
                    accessibility_flags="wheelchair_accessible,seating",
                ),
                Restaurant(
                    name="Uncounted Diner",
                    source="test",
                    source_id="count-2",
                    latitude=12.991,
                    longitude=77.551,
                    cuisine_tags="Multi-cuisine",
                ),
            ]
        )
        db.commit()

    payload = client.get("/filter-options").json()

    assert payload["counts"]["cuisine"]["Cafe/Bakery"] == 1
    assert payload["counts"]["accessibility"]["wheelchair_accessible"] == 1
    assert payload["counts"]["accessibility"]["seating"] == 1
    assert payload["counts"]["accessibility"]["not_wheelchair_accessible"] == 0
    assert payload["total_places"] == 2

    # A place carrying two accessibility tags must be counted under both, since
    # the field is comma-joined and the filter matches per tag.
    matched = client.get(
        "/restaurants", params={"accessibility": "wheelchair_accessible"}
    ).json()
    assert [row["name"] for row in matched] == ["Counted Cafe"]


def test_accessibility_is_filterable_and_counts_agree(client, session_factory):
    from app.models import Restaurant

    with session_factory() as db:
        db.add(
            Restaurant(
                name="Step Free",
                source="test",
                source_id="access-1",
                latitude=12.99,
                longitude=77.55,
                accessibility_flags="wheelchair_accessible",
            )
        )
        db.commit()

    payload = client.get("/filter-options").json()
    assert payload["accessibility"] == list(schemas.ACCESSIBILITY_FLAGS)

    for value in payload["accessibility"]:
        response = client.get("/restaurants", params={"accessibility": value})
        assert response.status_code == 200, value
        advertised = payload["counts"]["accessibility"][value]
        assert len(response.json()) == advertised, value


def test_every_advertised_cuisine_is_accepted_by_the_filter(client):
    cuisines = client.get("/filter-options").json()["cuisine"]

    for cuisine in cuisines:
        response = client.get("/restaurants", params={"cuisine": cuisine})
        assert response.status_code == 200, cuisine


def test_every_advertised_venue_type_is_accepted_by_the_filter(client):
    types = client.get("/filter-options").json()["type_tag"]

    for venue_type in types:
        response = client.get("/restaurants", params={"type_tag": venue_type})
        assert response.status_code == 200, venue_type


def test_advertised_cuisines_match_the_classifier_contract():
    # The classifier must never emit a label the filter menu does not offer.
    emitted = {label for label, _ in classifier.CUISINE_TAG_MAP.values()}

    assert emitted <= set(classifier.CANONICAL_CUISINES)
    assert set(classifier.CANONICAL_CUISINES) == emitted


def test_advertised_venue_types_match_the_enum():
    advertised = {item.value for item in models.RestaurantType}

    # Every type the classifier can assign must exist in the enum, otherwise a
    # classified restaurant could not be filtered on.
    assigned = {str(value.value) for value in classifier.TYPE_TAG_MAP.values()}

    assert assigned <= advertised


def test_diet_and_good_for_values_match_the_schema_contract(client):
    payload = client.get("/filter-options").json()

    assert payload["dietary"] == list(schemas.DIETARY_FLAGS)
    assert payload["good_for"] == list(schemas.GOOD_FOR_TAGS)

    for value in payload["dietary"]:
        assert client.get("/restaurants", params={"dietary": value}).status_code == 200
    for value in payload["good_for"]:
        assert client.get("/restaurants", params={"good_for": value}).status_code == 200


def test_points_agree_with_cards_on_every_advertised_filter(client):
    """The map and the cards read the same filters, including accessibility.

    The card endpoint pages and the points endpoint does not, so the comparison
    is against the first page of points rather than all of them.
    """

    for group in VOCABULARY_GROUPS:
        for value in client.get("/filter-options").json()[group]:
            cards = client.get(
                "/restaurants", params={group: value, "limit": 100}
            ).json()
            points = client.get("/restaurants/points", params={group: value}).json()
            assert {row["id"] for row in points[: len(cards)]} == {
                row["id"] for row in cards
            }, (group, value)


def test_unknown_venue_type_is_rejected(client):
    # Guards the reason the menu is generated from the API rather than hardcoded.
    assert (
        client.get("/restaurants", params={"type_tag": "food_truck"}).status_code == 422
    )
