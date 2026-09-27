"""Comma-joined tag matching.

These fields hold several tags in one string, so filtering means "contains this
whole tag". Two things go wrong easily here: matching a substring instead of a
tag, and treating the LIKE escaping as part of the literal value. The second one
silently made every value containing an underscore unfilterable.
"""

import pytest

from app.models import Restaurant


@pytest.fixture
def places(session_factory):
    rows = [
        # Underscores in the value, single tag.
        Restaurant(
            name="Step Free",
            source="test",
            source_id="tag-1",
            latitude=12.99,
            longitude=77.55,
            dietary_flags="non_veg",
            accessibility_flags="wheelchair_accessible",
        ),
        # Two tags, one of which shares a prefix with another valid value.
        Restaurant(
            name="Vegan And More",
            source="test",
            source_id="tag-2",
            latitude=12.991,
            longitude=77.551,
            dietary_flags="vegan,gluten_free",
            accessibility_flags="seating, wheelchair_accessible",
        ),
        # Spaced separators, which is how the OSM importer writes them.
        Restaurant(
            name="Spaced Tags",
            source="test",
            source_id="tag-3",
            latitude=12.992,
            longitude=77.552,
            good_for="outdoor, quick_bite",
        ),
    ]
    with session_factory() as db:
        db.add_all(rows)
        db.commit()
    return [row.name for row in rows]


def _names(client, **params) -> list[str]:
    response = client.get("/restaurants", params=params)
    assert response.status_code == 200
    return sorted(row["name"] for row in response.json())


def test_an_underscored_value_matches_exactly(client, places):
    # The regression: `non_veg` was escaped to `non\_veg` and then compared
    # against the raw column, so nothing could ever match it.
    assert _names(client, dietary="non_veg") == ["Step Free"]


def test_an_underscored_value_matches_inside_a_tag_list(client, places):
    assert _names(client, dietary="gluten_free") == ["Vegan And More"]


def test_every_accessibility_flag_is_reachable(client, places):
    assert _names(client, accessibility="wheelchair_accessible") == [
        "Step Free",
        "Vegan And More",
    ]
    assert _names(client, accessibility="seating") == ["Vegan And More"]
    assert _names(client, accessibility="not_wheelchair_accessible") == []


def test_a_tag_does_not_match_its_own_prefix(client, places):
    # `veg` must not return the vegan place: matching whole tags is the point.
    assert _names(client, dietary="veg") == []


def test_spaced_separators_are_matched(client, places):
    assert _names(client, good_for="outdoor") == ["Spaced Tags"]
    assert _names(client, good_for="quick_bite") == ["Spaced Tags"]


def test_matching_is_case_insensitive(client, places):
    assert _names(client, accessibility="Wheelchair_Accessible") == [
        "Step Free",
        "Vegan And More",
    ]


def test_a_wildcard_in_the_value_does_not_match_everything(client, places):
    # Escaping is what stops `%` from turning into a match-all.
    assert _names(client, dietary="%") == []
    assert _names(client, good_for="out%") == []


def test_an_empty_value_matches_nothing(client, places):
    assert _names(client, dietary=" ") == []


@pytest.mark.parametrize("group", ["cuisine", "dietary", "good_for", "accessibility"])
def test_advertised_counts_always_equal_what_the_filter_returns(
    client, session_factory, group
):
    """The count a menu shows must be the number of results it will get.

    This is the invariant that keeps a published vocabulary honest, and it is
    what caught the escaping bug in the first place.
    """

    _seed_with_every_value(session_factory, group)
    counts = client.get("/filter-options").json()["counts"][group]

    for value, advertised in counts.items():
        matched = client.get("/restaurants", params={group: value}).json()
        assert len(matched) == advertised, f"{group}={value}"


def _seed_with_every_value(session_factory, group: str) -> None:
    from app import schemas
    from app.models import Restaurant as R

    values = {
        "cuisine": ["Biryani", "Cafe/Bakery", "Multi-cuisine"],
        "dietary": list(schemas.DIETARY_FLAGS),
        "good_for": list(schemas.GOOD_FOR_TAGS),
        "accessibility": list(schemas.ACCESSIBILITY_FLAGS),
    }[group]

    field = {
        "cuisine": "cuisine_tags",
        "dietary": "dietary_flags",
        "good_for": "good_for",
        "accessibility": "accessibility_flags",
    }[group]

    with session_factory() as db:
        for index, value in enumerate(values):
            # A place carrying every value at once, so each filter must find it.
            db.add(
                R(
                    name=f"Carrier {index}",
                    source="test",
                    source_id=f"seed-{group}-{index}",
                    latitude=12.99,
                    longitude=77.55,
                    **{field: ", ".join(values)},
                )
            )
        db.commit()
