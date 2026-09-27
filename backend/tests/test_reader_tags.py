"""Letting a reader fill in what OpenStreetMap does not carry.

`good_for` matched 3.7% of places and dietary flags 8.7%, and re-ingesting cannot
move either number by a single row. OpenStreetMap does not record whether a
restaurant is good for a date, whether it has outdoor seating at the venue rather
than on a tag, or whether the kitchen can do Jain food without touching a
frying pan. Nobody tags that, because there is no vocabulary for it.

The people who know are the ones who just ate there, and they are already typing
a review. So the review form asks, and the answer is merged onto the place.

Merged, not replaced. A reader confirming "fine for families" must not erase an
`outdoor_seating=yes` the importer recorded from the tag, and two readers who
disagree should accumulate rather than have the last write win.
"""

import uuid

import pytest

from app import models
from app.schemas import DIETARY_FLAGS, GOOD_FOR_TAGS


@pytest.fixture(autouse=True)
def clear_limiters():
    from app import ratelimit

    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def place(session_factory):
    with session_factory() as db:
        restaurant = models.Restaurant(
            name="Tag Test Kitchen",
            source="test",
            source_id="tags-1",
            latitude=12.99,
            longitude=77.55,
        )
        db.add(restaurant)
        db.commit()
        db.refresh(restaurant)
        yield restaurant.id
        db.query(models.Review).filter_by(restaurant_id=restaurant.id).delete()
        db.commit()


def _review(client, place_id, **extra):
    payload = {
        "restaurant_id": place_id,
        "rating": 4.0,
        "text": "A perfectly ordinary review with enough words to be a review.",
        "client_request_id": str(uuid.uuid4()),
        **extra,
    }
    return client.post("/reviews", json=payload)


# ---------- the happy path ----------


def test_a_reader_can_tag_an_occasion(client, place):
    response = _review(client, place, good_for=["date", "group"])

    assert response.status_code == 201
    with_client = client.get(f"/restaurants/{place}")
    assert set(with_client.json()["good_for"].split(", ")) == {"date", "group"}


def test_a_reader_can_tag_diet(client, place):
    _review(client, place, dietary=["vegan", "jain"])

    payload = client.get(f"/restaurants/{place}").json()
    assert set(payload["dietary_flags"].split(", ")) == {"vegan", "jain"}


def test_no_tags_leaves_the_place_untouched(client, place):
    """The common case must not write an empty string over real data."""

    _review(client, place)

    payload = client.get(f"/restaurants/{place}").json()
    assert payload["good_for"] is None
    assert payload["dietary_flags"] is None


def test_a_tagged_review_also_makes_the_occasion_filter_match(client, place):
    """The whole point: the filter has to start matching.

    `date`, `family` and eight other occasions report a count of zero, and the
    UI labels those "none yet". A reader tagging one has to move that number, or
    the prompt is asking for something the app cannot then use.
    """

    options = client.get("/filter-options").json()
    assert options["counts"]["good_for"]["family"] == 0

    _review(client, place, good_for=["family"])

    after = client.get("/filter-options").json()
    assert after["counts"]["good_for"]["family"] == 1
    assert "family" in after["good_for"]


# ---------- merging rather than overwriting ----------


def test_reader_tags_merge_with_what_the_importer_recorded(
    client, place, session_factory
):
    """A reader confirming a fact must not delete a different recorded fact."""

    with session_factory() as db:
        restaurant = db.get(models.Restaurant, place)
        restaurant.good_for = "outdoor"
        db.commit()

    _review(client, place, good_for=["date"])

    payload = client.get(f"/restaurants/{place}").json()
    assert set(payload["good_for"].split(", ")) == {"outdoor", "date"}


def test_two_readers_accumulate_rather_than_overwrite(client, place):
    _review(client, place, good_for=["date"])
    _review(client, place, good_for=["work"])

    payload = client.get(f"/restaurants/{place}").json()
    assert set(payload["good_for"].split(", ")) == {"date", "work"}


def test_the_same_tag_twice_is_stored_once(client, place):
    _review(client, place, good_for=["solo", "solo", "solo"])

    payload = client.get(f"/restaurants/{place}").json()
    assert payload["good_for"] == "solo"


# ---------- validation ----------


def test_an_unknown_occasion_is_rejected(client, place):
    """An out-of-vocabulary tag is invisible to every filter.

    Storing it would look like coverage while being permanently unreachable, so
    it is refused rather than written.
    """

    response = _review(client, place, good_for=["romantic_dinner_for_two"])

    assert response.status_code == 422


def test_an_unknown_diet_flag_is_rejected(client, place):
    assert _review(client, place, dietary=["keto"]).status_code == 422


def test_an_empty_tag_list_is_accepted_and_does_nothing(client, place):
    response = _review(client, place, good_for=[], dietary=[])

    assert response.status_code == 201
    assert client.get(f"/restaurants/{place}").json()["good_for"] is None


def test_every_occasion_the_prompt_offers_is_accepted(client, place):
    """Guards the frontend list against drifting from the backend vocabulary.

    The form hard-codes eleven labels; if the backend gains or loses one, a
    reader picking it gets a 422 and does not find out why.
    """

    response = _review(client, place, good_for=list(GOOD_FOR_TAGS))

    assert response.status_code == 201


def test_every_diet_flag_the_prompt_offers_is_accepted(client, place):
    response = _review(client, place, dietary=list(DIETARY_FLAGS))

    assert response.status_code == 201


def test_a_review_is_still_possible_with_no_text_at_all(client, place):
    """Tagging must not become a side quest that blocks rating a place."""

    response = client.post(
        "/reviews",
        json={
            "restaurant_id": place,
            "rating": 3.0,
            "client_request_id": str(uuid.uuid4()),
            "good_for": ["quick_bite"],
        },
    )

    assert response.status_code == 201
