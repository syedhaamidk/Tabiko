"""Trust scoring, checked against realistic review text.

Every case in this file was written from how people actually write about eating
out in Bengaluru, not from the vocabulary the scorer happens to contain. The two
bugs it guards against were both found by running the scorer over real sentences
and being surprised:

"fresh" was in the positive list, so "the dosa was fresh off the tawa" scored a
restaurant 5/5 on hygiene while saying nothing about its kitchen. And matching
was done with `word in text`, so "roach" fired inside "approach" -- a review
saying the staff "took a practical approach" scored 0.0, which is a false
negative and a false positive in the same sentence.
"""

import pytest

from app import trust

# ---------- what counts as a hygiene signal ----------


@pytest.mark.parametrize(
    "text",
    [
        "The dosa was fresh off the tawa and the batter was light.",
        "Fresh filter coffee, hot and well made. Staff were friendly.",
        "Freshly ground masala in the dosa, you can taste the difference.",
        "Service was quick, biryani was fresh and the raita was cool.",
        "Everything was fresh, the coffee was refreshing on a hot day.",
    ],
)
def test_fresh_food_is_not_a_hygiene_signal(text):
    """ "Fresh" describes the food roughly ten times for every time it describes
    the room. Counting it made almost every positive review a 5/5 cleanliness
    score."""

    assert trust.score_hygiene_mention(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "The staff took a practical approach to the queue, and the dosa was fine.",
        "We installed no new tiles, but the service counter was usable.",
        "The place encroaches on the footpath outside, worth knowing.",
    ],
)
def test_keywords_do_not_match_inside_longer_words(text):
    """`roach` inside `approach`, `stale` inside `install`, `roach` inside
    `encroach`. Substring matching made all of these fire."""

    assert trust.score_hygiene_mention(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ambience was clean and the washrooms were spotless.", 1.0),
        ("Hygienic and well maintained throughout.", 1.0),
        ("The tables were immaculate.", 1.0),
        ("Sticky tables and a stale smell near the kitchen.", -1.0),
        ("Found a cockroach next to the sink.", -1.0),
        ("The floor was grimy and there were flies on the counter.", -1.0),
    ],
)
def test_real_hygiene_mentions_are_still_detected(text, expected):
    """The fix must not have blunted the scorer along with the false positives."""

    assert trust.score_hygiene_mention(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "Nice place, tasty food, would visit again.",
        "Great value for money. Service was quick.",
        "Must try the chicken biryani here.",
    ],
)
def test_a_review_that_says_nothing_about_hygiene_contributes_nothing(text):
    """None, not 0.0.

    The restaurant score is a mean over only the reviews that mentioned hygiene,
    so one vague remark cannot drag a place down. Treating silence as neutral
    would let a single 5-star food review set the score to 3.75 by accident.
    """

    assert trust.score_hygiene_mention(text) is None


def test_conflicting_mentions_cancel_out():
    assert trust.score_hygiene_mention(
        "Clean hall, but there was a stale smell and a cockroach."
    ) == pytest.approx(-1 / 3)


def test_repeating_a_word_counts_more_than_once():
    """A review that keeps coming back to dirtiness is saying something."""

    assert (
        trust.score_hygiene_mention("Dirty floor, dirty counter, dirty glassware.")
        == -1.0
    )


# ---------- the restaurant-level score ----------


def test_hygiene_score_is_the_mean_of_reviews_that_mentioned_it(session_factory):
    """Two opposite reviews cancel; three that said nothing are ignored."""

    from app import models

    with session_factory() as db:
        restaurant = models.Restaurant(
            name="Test Kitchen",
            source="test",
            source_id="hygiene-1",
            latitude=12.99,
            longitude=77.55,
        )
        db.add(restaurant)
        db.commit()
        db.refresh(restaurant)

        user = models.User(name="R", email="r@example.com", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)

        for text in (
            "Spotless throughout, very hygienic.",  # +1.0
            "Sticky tables, stale smell, a cockroach.",  # -1.0
            "Great dosa.",  # ignored
            "Good coffee.",  # ignored
        ):
            db.add(
                models.Review(
                    user_id=user.id,
                    restaurant_id=restaurant.id,
                    rating=4.0,
                    text=text,
                    verification_tier=models.VerificationTier.checked_in,
                )
            )
        db.flush()
        trust.update_hygiene_score(db, restaurant)
        db.commit()

        # +1.0 and -1.0 average to zero, which maps to the neutral midpoint.
        assert restaurant.hygiene_score == 2.5


def test_a_clean_restaurant_reaches_the_top_of_the_scale(session_factory):
    from app import models

    with session_factory() as db:
        restaurant = models.Restaurant(
            name="Spotless",
            source="test",
            source_id="hygiene-2",
            latitude=12.99,
            longitude=77.55,
        )
        db.add(restaurant)
        user = models.User(name="R2", email="r2@example.com", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(restaurant)
        db.refresh(user)

        db.add(
            models.Review(
                user_id=user.id,
                restaurant_id=restaurant.id,
                rating=5.0,
                text="Immaculate and spotless, very clean and hygienic.",
                verification_tier=models.VerificationTier.checked_in,
            )
        )
        db.flush()
        trust.update_hygiene_score(db, restaurant)
        db.commit()

        assert restaurant.hygiene_score == 5.0


def test_a_restaurant_with_no_hygiene_mentions_has_no_score(session_factory):
    """None rather than 3.75. An unmentioned dimension is unknown, not average."""

    from app import models

    with session_factory() as db:
        restaurant = models.Restaurant(
            name="Silent",
            source="test",
            source_id="hygiene-3",
            latitude=12.99,
            longitude=77.55,
        )
        db.add(restaurant)
        user = models.User(name="R3", email="r3@example.com", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(restaurant)
        db.refresh(user)

        db.add(
            models.Review(
                user_id=user.id,
                restaurant_id=restaurant.id,
                rating=5.0,
                text="Best dosa in the city.",
                verification_tier=models.VerificationTier.checked_in,
            )
        )
        db.flush()
        trust.update_hygiene_score(db, restaurant)
        db.commit()

        assert restaurant.hygiene_score is None


def test_flagged_reviews_do_not_move_the_hygiene_score(session_factory):
    """A review the fraud scorer rejected is not evidence about the kitchen."""

    from app import models

    with session_factory() as db:
        restaurant = models.Restaurant(
            name="Flagged",
            source="test",
            source_id="hygiene-4",
            latitude=12.99,
            longitude=77.55,
        )
        db.add(restaurant)
        user = models.User(name="R4", email="r4@example.com", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(restaurant)
        db.refresh(user)

        db.add(
            models.Review(
                user_id=user.id,
                restaurant_id=restaurant.id,
                rating=1.0,
                text="Filthy, grimy, cockroaches everywhere.",
                verification_tier=models.VerificationTier.checked_in,
                fraud_flag=True,
            )
        )
        db.flush()
        trust.update_hygiene_score(db, restaurant)
        db.commit()

        assert restaurant.hygiene_score is None
