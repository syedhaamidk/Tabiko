"""Craving ranking, judged on what a reader would expect to happen.

The scoring here is BM25 over field-weighted term counts, and both of those
choices came from watching the search get real dish text for the first time.

**Field weighting.** The corpus used to be one flat bag of words per venue, so
every term counted once. Against a real menu that ranked almost purely on the
venue NAME, because a name is one short field and a menu is not: "cold brew"
returned Cold Stone Creamery and Pizza Brew House, venues with "brew" in the name
and no cold brew on it.

**BM25 rather than cosine.** Cosine L2-normalises each document across all of
its terms, so a venue with ten dishes has each dish divided by the magnitude of
the whole menu. MTR lists ten dishes and scored each one below a shop called
"Dosa Corner", and searching "dosa" put none of the four venues that actually
serve dosa anywhere in the top twenty.

**Unweighted document length.** The first BM25 attempt was still wrong, because
BM25's length penalty was fed the weighted sum. That made a well-documented venue
look twenty times longer than average and divided away its own strongest
evidence, for exactly the same reason cosine did. Length has to measure how much
text there is, not how much the scorer thinks it is worth.

These tests assert the ranking properties that came out of all that, using the
venue names a real corpus is full of.
"""

from app import craving_search as cs
from app import models


def _venue(db, name, dishes=(), cuisine=None, reviews=()):
    restaurant = models.Restaurant(
        name=name,
        source="test",
        source_id=f"rank-{name}",
        latitude=12.99,
        longitude=77.55,
        cuisine_tags=cuisine,
    )
    db.add(restaurant)
    db.flush()
    for dish in dishes:
        db.add(models.Dish(restaurant_id=restaurant.id, name=dish))
    for text in reviews:
        db.add(
            models.Review(
                user_id=_user(db),
                restaurant_id=restaurant.id,
                rating=4.0,
                text=text,
                verification_tier=models.VerificationTier.checked_in,
            )
        )
    db.commit()
    db.refresh(restaurant)
    return restaurant


def _user(db):
    existing = db.query(models.User).filter_by(email="rank@example.com").first()
    if existing:
        return existing.id
    user = models.User(name="R", email="rank@example.com", password_hash="x")
    db.add(user)
    db.commit()
    return user.id


def _rank(db, query, limit=20):
    """Rebuild the index and rank, so each test starts from the real corpus."""

    cs.invalidate_index()
    return cs.search_by_craving(db, query, limit=limit)


# ---------- a menu beats a name ----------


def test_a_venue_that_serves_it_beats_a_venue_named_after_it(session_factory):
    """The headline fix.

    Before, "dosa" put Dosa Corner above every venue with a dosa on its menu,
    because a name and a menu entry each counted exactly once and the name
    document was shorter.
    """

    with session_factory() as db:
        named = _venue(db, "Dosa Corner")
        serves = _venue(db, "Hotel Kaveri", dishes=["Masala Dosa", "Idli", "Vada"])
        results = _rank(db, "dosa")

        names = [row[0].name for row in results]
        assert names.index("Hotel Kaveri") < names.index("Dosa Corner"), (
            f"menu match should outrank name match, got {names[:5]}"
        )
        assert serves.id and named.id


def test_a_single_dish_entry_outranks_a_venue_named_after_it(session_factory):
    """Even one dish, against a name that is nothing but the word."""

    with session_factory() as db:
        _venue(db, "Cold Stone Creamery")
        _venue(db, "Blue Tokai", dishes=["Cold Brew"])

        results = _rank(db, "cold brew")
        names = [row[0].name for row in results]

        assert names.index("Blue Tokai") < names.index("Cold Stone Creamery"), names[:5]


# ---------- a bigger menu is not a penalty ----------


def test_a_ten_dish_menu_is_not_diluted_by_its_own_breadth(session_factory):
    """The bug that survived the first fix.

    With weighted document length, MTR scored below a single-word venue for
    "dosa" because its ten dishes made it twenty times the average length.
    """

    with session_factory() as db:
        _venue(db, "Dosa Hut")
        _venue(
            db,
            "MTR 1924",
            dishes=[
                "Masala Dosa",
                "Rava Idli",
                "Medu Vada",
                "Mysore Pak",
                "Undhiyu",
                "Kesari Bath",
                "Filter Coffee",
                "Ghee Roast Dosa",
                "Bisi Bele Bath",
                "Khar Badam",
            ],
        )

        results = _rank(db, "dosa")
        names = [row[0].name for row in results]

        assert names[0] == "MTR 1924", f"expected the real menu first, got {names[:4]}"


def test_relevance_stays_within_the_range_the_client_expects(session_factory):
    """The endpoint contract: a non-negative number, ordered descending."""

    with session_factory() as db:
        _venue(db, "Dosa Hut")
        _venue(db, "MTR 1924", dishes=["Masala Dosa", "Filter Coffee"])

        results = _rank(db, "dosa")

        scores = [score for _, score, _ in results]
        assert all(score >= 0 for score in scores)
        assert scores == sorted(scores, reverse=True)


# ---------- field weights are ordered by how much they prove ----------


def test_a_dish_outranks_a_cuisine_tag_that_merely_names_it(session_factory):
    """A cuisine label is a hint; a dish on the menu is a statement.

    Both venues have the token "dosa" somewhere, so both are candidates -- the
    point is that the one with the dish on the menu wins.
    """

    with session_factory() as db:
        _venue(db, "Somewhere", cuisine="Dosa, South Indian")
        _venue(db, "Another Place", dishes=["Masala Dosa"])

        names = [row[0].name for row in _rank(db, "dosa")]

        assert names.index("Another Place") < names.index("Somewhere")


def test_a_review_mentioning_a_dish_surfaces_a_venue_with_no_such_name(session_factory):
    """A dish only named in prose is still findable.

    This is the case the whole contribution flow exists for: a reader writes
    "the gongura mutton here is the reason I keep coming back" and someone
    searching "gongura mutton" should find them, even though the venue is called
    nothing more memorable than "Sri Lakshmi".

    Note what this does NOT claim. When a venue is *named* after the same
    phrase, the name still wins: "Masala Dosa Point" outranks a review that
    mentions masala dosa. That is the right answer -- a shopfront sign is better
    evidence than a sentence -- and it is why the name weight is 1.0 rather than
    zero.
    """

    with session_factory() as db:
        _venue(
            db,
            "Sri Lakshmi",
            reviews=["The gongura mutton here is why I keep coming back."],
        )
        _venue(db, "Unrelated Cafe", dishes=["Sourdough Loaf"])

        names = [row[0].name for row in _rank(db, "gongura mutton")]

        assert names[0] == "Sri Lakshmi", names[:4]
        assert "Unrelated Cafe" not in names


def test_a_venue_named_after_the_phrase_still_beats_a_review_mention(session_factory):
    """The counterpart, pinned so the weight is not quietly changed later."""

    with session_factory() as db:
        _venue(db, "Masala Dosa Point")
        _venue(db, "Corner Cafe", reviews=["The masala dosa here is worth the walk."])

        names = [row[0].name for row in _rank(db, "masala dosa")]

        assert names[0] == "Masala Dosa Point", names[:4]


# ---------- what it must still refuse to do ----------


def test_a_term_absent_from_the_corpus_is_reported_not_guessed(session_factory):
    with session_factory() as db:
        _venue(db, "Food Court", cuisine="Multi-cuisine")
        _venue(db, "Dosa Hut")

        results = _rank(db, "gongura")

        assert all("gongura" in row[2] for row in results)


def test_a_query_of_only_unknown_terms_returns_nothing(session_factory):
    """The original sin this module was written to avoid.

    "comfort food" used to rank venues called Food and FOOD COURT, because the
    corpus had no word "comfort" and the query collapsed to "food".
    """

    with session_factory() as db:
        _venue(db, "Food Court", cuisine="Multi-cuisine")
        _venue(db, "Comfort Inn")

        assert _rank(db, "gongura poriyal") == []


def test_a_venue_with_no_matching_term_is_never_returned(session_factory):
    with session_factory() as db:
        _venue(db, "Dosa Hut")
        unrelated = _venue(db, "Bakery", dishes=["Sourdough Loaf"])

        ids = {row[0].id for row in _rank(db, "masala dosa")}

        assert unrelated.id not in ids
