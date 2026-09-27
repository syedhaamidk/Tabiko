"""Craving search.

The behaviour worth protecting here is not the ranking maths, which is ordinary
cosine similarity. It is the two things that only went wrong once the corpus was
real: the search used to rebuild its whole index on every query, and it used to
answer questions its corpus could not answer as though it could.
"""

import time

import pytest

from app import craving_search
from app.models import Dish, Restaurant, Review, User
from tests.conftest import TEST_EMAIL


@pytest.fixture(autouse=True)
def clear_index():
    # The index is process-wide, so a test that seeds rows must not inherit a
    # snapshot built by whichever test ran before it.
    craving_search.invalidate_index()
    yield
    craving_search.invalidate_index()


@pytest.fixture
def corpus(session_factory):
    with session_factory() as db:
        places = [
            Restaurant(
                name="Biryani House",
                source="test",
                source_id="craving-1",
                latitude=12.99,
                longitude=77.55,
                cuisine_tags="Biryani",
            ),
            Restaurant(
                name="Filter Coffee Stand",
                source="test",
                source_id="craving-2",
                latitude=12.991,
                longitude=77.551,
                cuisine_tags="Cafe/Bakery",
            ),
            Restaurant(
                name="Somewhere Else",
                source="test",
                source_id="craving-3",
                latitude=12.992,
                longitude=77.552,
            ),
        ]
        db.add_all(places)
        db.commit()
        for place in places:
            db.refresh(place)
        return {place.name: place.id for place in places}


def _search(client, query, **params):
    response = client.get("/search/craving", params={"q": query, **params})
    assert response.status_code == 200
    return response.json()


def test_a_word_in_the_name_ranks_that_place_first(client, corpus):
    results = _search(client, "biryani")

    assert results
    assert results[0]["restaurant"]["name"] == "Biryani House"
    assert results[0]["unmatched_terms"] == []


def test_a_term_the_corpus_never_contains_is_reported(client, corpus):
    results = _search(client, "biryani zzqx")

    assert results
    # The ranking still answers the part it can, but says what it could not use.
    assert results[0]["unmatched_terms"] == ["zzqx"]


def test_a_craving_word_absent_from_the_corpus_is_reported(client, corpus):
    # "comfort" is a real craving word that appears in no place name, dish or
    # review. It is still a term the corpus cannot answer, and saying so is the
    # whole point: exempting it is what let "comfort food" rank venues named
    # "Food" without the UI knowing the score was meaningless.
    results = _search(client, "comfort")

    assert all(result["unmatched_terms"] == ["comfort"] for result in results)


def test_a_multi_word_query_reports_only_the_unanswerable_terms(client, corpus):
    results = _search(client, "comfort biryani")

    assert results[0]["restaurant"]["name"] == "Biryani House"
    assert results[0]["unmatched_terms"] == ["comfort"]


def test_a_query_of_only_unknown_terms_returns_nothing_rather_than_junk(client, corpus):
    # The failure this prevents: "comfort food" collapsing to just "food" and
    # returning every venue with Food in its name, confidently ranked.
    assert _search(client, "zzqx") == []


def test_relevance_is_ordered(client, corpus):
    results = _search(client, "biryani coffee", limit=10)

    scores = [result["relevance"] for result in results]
    assert scores == sorted(scores, reverse=True)


def test_dish_text_is_searchable(client, session_factory, corpus):
    with session_factory() as db:
        place = db.query(Restaurant).filter_by(source_id="craving-3").one()
        db.add(Dish(restaurant_id=place.id, name="Mysore Pak", tags="sweet,snack"))
        db.commit()

    results = _search(client, "mysore pak")

    assert [result["restaurant"]["name"] for result in results] == ["Somewhere Else"]


def test_review_text_is_searchable(client, session_factory, corpus):
    with session_factory() as db:
        user = User(name="Reviewer", email="rev@example.com", password_hash="x")
        db.add(user)
        db.flush()
        place = db.query(Restaurant).filter_by(source_id="craving-3").one()
        db.add(
            Review(
                user_id=user.id,
                restaurant_id=place.id,
                rating=5,
                text="The gongura poriyal is outstanding.",
            )
        )
        db.commit()

    results = _search(client, "gongura poriyal")

    assert [result["restaurant"]["name"] for result in results] == ["Somewhere Else"]


def test_flagged_reviews_are_not_searchable(client, session_factory, corpus):
    with session_factory() as db:
        user = User(name="Spammer", email="spam@example.com", password_hash="x")
        db.add(user)
        db.flush()
        place = db.query(Restaurant).filter_by(source_id="craving-3").one()
        db.add(
            Review(
                user_id=user.id,
                restaurant_id=place.id,
                rating=1,
                text="kwzx spam voucher",
                fraud_flag=True,
            )
        )
        db.commit()

    assert _search(client, "kwzx") == []


def test_flagging_a_review_takes_its_text_out_of_the_index(
    client, session_factory, corpus
):
    with session_factory() as db:
        user = User(name="Poster", email="poster@example.com", password_hash="x")
        db.add(user)
        db.flush()
        place = db.query(Restaurant).filter_by(source_id="craving-3").one()
        review = Review(
            user_id=user.id,
            restaurant_id=place.id,
            rating=4,
            text="unmatchablemarmoset",
        )
        db.add(review)
        db.commit()
        review_id = review.id

    assert _search(client, "unmatchablemarmoset")

    # Flagging changes the searchable text without changing any row count, so
    # this is the case the count-based cache check cannot see.
    with session_factory() as db:
        # The client fixture authenticates as the shared test account, so that
        # is the one that needs the admin flag.
        db.query(User).filter_by(email=TEST_EMAIL).one().is_admin = True
        db.commit()

    response = client.patch(
        f"/reviews/{review_id}/moderation",
        json={"fraud_flag": True, "fraud_reason": "spam"},
    )
    assert response.status_code == 200

    assert _search(client, "unmatchablemarmoset") == []


def test_the_index_is_reused_between_searches(client, session_factory, corpus):
    _search(client, "biryani")

    with session_factory() as db:
        db.add(
            Restaurant(
                name="Late Addition",
                source="test",
                source_id="craving-late",
                latitude=12.993,
                longitude=77.553,
            )
        )
        db.commit()

    # The row count changed, so the cached snapshot is rebuilt and the new place
    # is searchable without any explicit invalidation.
    results = _search(client, "late addition")
    assert [result["restaurant"]["name"] for result in results] == ["Late Addition"]


def test_a_large_corpus_stays_fast(client, session_factory):
    """Guards the regression that made this endpoint unusable.

    Building the index per query meant loading every place plus its dishes and
    reviews on every search, which cost seconds once the city was loaded. The
    fix is a cached index plus eager loading, and this is the assertion that
    would catch its removal.
    """

    with session_factory() as db:
        db.add_all(
            Restaurant(
                name=f"Place Number {index}",
                source="test",
                source_id=f"perf-{index}",
                latitude=12.9 + index / 100_000,
                longitude=77.5,
            )
            for index in range(3000)
        )
        db.commit()

    # First search builds the index and is allowed to be the slow one.
    client.get("/search/craving", params={"q": "number"})

    started = time.perf_counter()
    response = client.get("/search/craving", params={"q": "number"})
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    # A generous ceiling, but far below the multi-second cost of a per-query
    # rebuild over this corpus.
    assert elapsed < 1.0, f"cached search took {elapsed:.2f}s"


def test_the_limit_is_honoured(client, corpus):
    assert len(_search(client, "biryani coffee somewhere", limit=2)) <= 2
