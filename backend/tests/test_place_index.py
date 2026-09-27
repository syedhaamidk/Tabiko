"""The in-memory place index.

It is only allowed to exist because it returns exactly what the database would.
These tests assert that equivalence directly rather than testing the index against
itself, because a cache that quietly disagreed with the source would be worse than
no cache at all.
"""

import pytest

from app import models, place_index

# Roughly greater Bengaluru, so a bounding box actually excludes something.
CITY = (12.75, 77.45, 13.15, 77.80)


@pytest.fixture(autouse=True)
def clear_index():
    place_index.invalidate()
    yield
    place_index.invalidate()


def _seed(session_factory) -> None:
    with session_factory() as db:
        db.add_all(
            [
                models.Restaurant(
                    name="Biryani House",
                    source="test",
                    source_id="idx-1",
                    latitude=12.99,
                    longitude=77.55,
                    address="12th Main",
                    cuisine_tags="Biryani, Multi-cuisine",
                    dietary_flags="veg, jain",
                    good_for="outdoor",
                    accessibility_flags="wheelchair_accessible, seating",
                    type_tag=models.RestaurantType.family_restaurant,
                ),
                models.Restaurant(
                    name="Vegan Cafe",
                    source="test",
                    source_id="idx-2",
                    latitude=12.98,
                    longitude=77.56,
                    address="Church Street",
                    cuisine_tags="Cafe/Bakery",
                    dietary_flags="vegan",
                    type_tag=models.RestaurantType.cafe,
                ),
                models.Restaurant(
                    name="Far Diner",
                    source="test",
                    source_id="idx-3",
                    latitude=13.10,
                    longitude=77.75,
                    cuisine_tags="Multi-cuisine",
                    type_tag=models.RestaurantType.family_restaurant,
                ),
                models.Restaurant(
                    name="No Tags At All",
                    source="test",
                    source_id="idx-4",
                    latitude=12.97,
                    longitude=77.57,
                ),
            ]
        )
        db.commit()


def _sql_ids(session_factory, **params) -> set[int]:
    """What the database answers, via the same helpers the endpoint uses."""

    from app.main import _apply_restaurant_filters

    with session_factory() as db:
        query = _apply_restaurant_filters(
            db.query(models.Restaurant),
            cuisine=params.get("cuisine"),
            type_tag=params.get("type_tag"),
            dietary=params.get("dietary"),
            good_for=params.get("good_for"),
            accessibility=params.get("accessibility"),
            search=params.get("search"),
        )
        return {row.id for row in query.all()}


def _index_ids(session_factory, **params) -> set[int]:
    # The session must come from the test engine, not the module-level
    # SessionLocal, or this would quietly read the real city database.
    with session_factory() as session:
        return {
            entry.row.id
            for entry in place_index.select_rows(
                place_index.all_rows(session),
                cuisine=params.get("cuisine"),
                type_tag=params.get("type_tag"),
                dietary=params.get("dietary"),
                good_for=params.get("good_for"),
                accessibility=params.get("accessibility"),
                search=params.get("search"),
            )
        }


FILTERS = [
    {},
    {"cuisine": "Biryani"},
    {"cuisine": "Multi-cuisine"},
    {"cuisine": "Cafe/Bakery"},
    {"type_tag": models.RestaurantType.cafe},
    {"dietary": "veg"},
    {"dietary": "vegan"},
    {"dietary": "jain"},
    {"good_for": "outdoor"},
    {"accessibility": "wheelchair_accessible"},
    {"accessibility": "seating"},
    {"search": "biryani"},
    {"search": "12th main"},
    {"search": "CHURCH"},
    {"search": "nothing matches this"},
    {"cuisine": "Biryani", "dietary": "veg"},
    {"cuisine": "Multi-cuisine", "accessibility": "seating"},
]


@pytest.mark.parametrize("params", FILTERS, ids=lambda p: ",".join(p) or "none")
def test_the_index_agrees_with_the_database(session_factory, params):
    _seed(session_factory)
    assert _index_ids(session_factory, **params) == _sql_ids(session_factory, **params)


def test_the_index_agrees_with_the_database_for_a_bounding_box(session_factory):
    _seed(session_factory)
    with session_factory() as session:
        entries = place_index.all_rows(session)
        inside = place_index.within_bounds(entries, 12.96, 77.54, 13.00, 77.58)
        assert {entry.row.name for entry in inside} == {
            "Biryani House",
            "Vegan Cafe",
            "No Tags At All",
        }


def test_underscored_tags_match_through_the_index(session_factory):
    # The escaping bug that made `non_veg` and every access flag unfilterable
    # would be reintroduced here if the tags were compared any other way.
    _seed(session_factory)
    assert _index_ids(session_factory, dietary="veg") == _sql_ids(
        session_factory, dietary="veg"
    )


def test_a_whole_tag_never_matches_a_prefix(session_factory):
    _seed(session_factory)
    # `Vegan Cafe` is tagged vegan, not veg, so it must not answer a veg filter.
    assert _index_ids(session_factory, dietary="veg") == {
        1  # Biryani House
    }
    assert _index_ids(session_factory, dietary="vegan") == {2}


def test_a_wildcard_is_matched_literally(session_factory):
    _seed(session_factory)
    # A `%` in a search term must not behave as a match-all.
    assert _index_ids(session_factory, search="%") == set()


def test_the_index_is_reused_between_calls(session_factory):
    _seed(session_factory)
    with session_factory() as session:
        first = place_index.all_rows(session)
    with session_factory() as session:
        second = place_index.all_rows(session)
    # Identity, not equality: the second call must not rebuild anything.
    assert first is second


def test_the_index_picks_up_a_new_place(session_factory):
    _seed(session_factory)
    with session_factory() as session:
        before = {entry.row.id for entry in place_index.all_rows(session)}
    assert len(before) == 4

    with session_factory() as db:
        db.add(
            models.Restaurant(
                name="Late Arrival",
                source="test",
                source_id="idx-late",
                latitude=12.96,
                longitude=77.58,
            )
        )
        db.commit()

    with session_factory() as session:
        after = {entry.row.id for entry in place_index.all_rows(session)}
    assert len(after) == 5
    assert after - before == {max(before) + 1}


def test_invalidate_drops_the_snapshot(session_factory):
    _seed(session_factory)
    with session_factory() as session:
        first = place_index.all_rows(session)
    place_index.invalidate()
    with session_factory() as session:
        assert place_index.all_rows(session) is not first


def test_rows_carry_every_field_the_map_returns(session_factory):
    _seed(session_factory)
    with session_factory() as session:
        entry = next(
            e for e in place_index.all_rows(session) if e.row.name == "Biryani House"
        )
    assert entry.row.latitude == 12.99
    assert entry.row.longitude == 77.55
    assert entry.row.cuisine_tags == "Biryani, Multi-cuisine"
    assert entry.row.type_tag is models.RestaurantType.family_restaurant


def test_the_index_does_not_accumulate_across_repeated_reads(session_factory):
    # A shape check rather than a leak check: repeated reads must not append.
    _seed(session_factory)
    for _ in range(5):
        with session_factory() as session:
            assert len(place_index.all_rows(session)) == 4
