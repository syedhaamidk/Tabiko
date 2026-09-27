"""The fraud scorer, against realistic usage rather than synthetic strings.

The brief for this was specific: a small group of friends reviewing places over
a few days should NOT be flagged. The burst rule as written looks alarming on
paper -- "3 reviews from this user for this restaurant in the last hour scores +2,
and +1 is enough on its own to reach the flag threshold once combined with an
unverified tier" -- so whether it false-positives on ordinary behaviour is a
question about the arithmetic, not about taste.

It is scoped to one user at one restaurant, which is the right scoping: a busy
venue should not get every honest review flagged, and a user reviewing eight
different places is not a burst.
"""

from datetime import timedelta

import pytest

from app import models, trust


@pytest.fixture
def restaurant(session_factory):
    with session_factory() as db:
        row = models.Restaurant(
            name="Fraud Test Kitchen",
            source="test",
            source_id="fraud-1",
            latitude=12.99,
            longitude=77.55,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        yield row.id
        db.query(models.Review).filter_by(restaurant_id=row.id).delete()
        db.commit()


@pytest.fixture
def user(session_factory):
    with session_factory() as db:
        row = models.User(name="Tester", email="fraud@example.com", password_hash="x")
        db.add(row)
        db.commit()
        db.refresh(row)
        yield row.id
        db.query(models.User).filter_by(id=row.id).delete()
        db.commit()


def _review(
    session, user_id, restaurant_id, *, text, rating=4.0, tier="checked_in", age=0
):
    """Add a review and run the real scorer over it."""

    review = models.Review(
        user_id=user_id,
        restaurant_id=restaurant_id,
        rating=rating,
        text=text,
        verification_tier=models.VerificationTier(tier),
        created_at=models.utc_now() - timedelta(hours=age),
        client_request_id=str(__import__("uuid").uuid4()),
    )
    session.add(review)
    session.flush()
    trust.score_review(session, review)
    session.flush()
    return review


GOOD_TEXT = (
    "Went on a weekday lunch, the place was clean and the service was quick. "
    "Worth the price for what you get."
)


# ---------- the case that must not fire ----------


def test_five_ordinary_reviews_over_five_days_are_not_flagged(
    session_factory, user, restaurant
):
    """The headline requirement: friends reviewing over a few days, unflagged.

    Every one of these is a 4.0 with real text, so the "extreme rating" signal
    never fires, and they are spaced a day apart so the one-hour burst window is
    empty each time.
    """

    with session_factory() as db:
        flagged = []
        for day in range(5):
            review = _review(
                db, user, restaurant, text=GOOD_TEXT, rating=4.0, age=day * 24
            )
            if review.fraud_flag:
                flagged.append((day, review.fraud_reason))
        db.commit()

    assert flagged == [], f"ordinary usage was flagged: {flagged}"


def test_a_user_reviewing_eight_different_places_is_not_a_burst(
    session_factory, user, restaurant
):
    """The burst rule is scoped to one restaurant on purpose.

    Someone who eats out eight times in an hour is enthusiastic, not fraudulent.
    """

    with session_factory() as db:
        places = []
        for index in range(8):
            other = models.Restaurant(
                name=f"Place {index}",
                source="test",
                source_id=f"burst-{index}",
                latitude=12.99,
                longitude=77.55,
            )
            db.add(other)
            db.commit()
            db.refresh(other)
            places.append(other.id)

        for place_id in places:
            review = _review(db, user, place_id, text=GOOD_TEXT, rating=4.0)
            assert not review.fraud_flag, (
                f"flagged at {place_id}: {review.fraud_reason}"
            )

        db.query(models.Restaurant).filter(
            models.Restaurant.source_id.like("burst-%")
        ).delete(synchronize_session=False)
        db.commit()


def test_a_long_honest_rant_at_a_middling_rating_is_not_fraud(
    session_factory, user, restaurant
):
    """Low ratings are not evidence of fraud. Plenty of good reviews are angry."""

    with session_factory() as db:
        review = _review(
            db,
            user,
            restaurant,
            text=(
                "Waited 40 minutes for a table we had booked, the dosa was overcooked "
                "and the raita was watery. Staff were apologetic but it was a bad "
                "evening. Will try again on a weekday."
            ),
            rating=2.0,
        )
        db.commit()

    assert not review.fraud_flag
    assert review.fraud_reason is None


# ---------- the case that must ----------


def test_a_lone_empty_extreme_review_scores_two_and_is_not_flagged(
    session_factory, user, restaurant
):
    """Documenting the threshold, because it is stricter than it first reads.

    Signals are +1 unverified, +1 extreme-rating-with-no-text, +2 burst, and the
    flag needs 3. An unverified one-word five-star review therefore scores 2 and
    is not flagged. Every flagging path goes through the burst signal.

    That is defensible -- auto-hiding a review is a visibility decision and the
    module's stated rule is that one weak signal is not enough -- but it was not
    obvious from reading the code, and it means a lone spam review from an
    unverified account is simply shown.
    """

    with session_factory() as db:
        review = _review(
            db, user, restaurant, text="Great", rating=5.0, tier="unverified"
        )
        db.commit()

    assert not review.fraud_flag
    assert review.fraud_reason is None


def test_two_weak_signals_still_do_not_flag(session_factory, user, restaurant):
    """The arithmetic that the test above pins down, stated directly."""

    with session_factory() as db:
        review = _review(
            db, user, restaurant, text="Good", rating=1.0, tier="unverified"
        )
        db.commit()

    # unverified (+1) plus extreme-with-no-text (+1) is 2, and 2 < 3.
    assert not review.fraud_flag


def test_a_burst_from_an_unverified_account_is_flagged_on_the_third_review(
    session_factory, user, restaurant
):
    """The realistic spam pattern: the same account, one place, minutes apart."""

    with session_factory() as db:
        outcomes = []
        for _ in range(3):
            review = _review(
                db, user, restaurant, text="Nice", rating=5.0, tier="unverified", age=0
            )
            outcomes.append((review.fraud_flag, review.fraud_reason))
        db.commit()

    assert [flagged for flagged, _ in outcomes] == [False, False, True]
    assert "rapid reviews" in outcomes[-1][1]


def test_four_rapid_reviews_of_one_place_are_flagged(session_factory, user, restaurant):
    """The burst rule, and the reason it is scoped to a single restaurant."""

    with session_factory() as db:
        results = []
        for index in range(4):
            review = _review(
                db,
                user,
                restaurant,
                text=GOOD_TEXT,
                rating=4.0,
                tier="unverified",
                age=0,
            )
            results.append((index, review.fraud_flag, review.fraud_reason))
        db.commit()

    # The first two are clean: an unverified tier alone is one weak signal.
    assert results[0][1] is False
    assert results[1][1] is False
    # The third trips the burst window, and by the fourth the reason is on record.
    assert any(flagged for _, flagged, _ in results)
    assert any("rapid reviews" in (reason or "") for _, _, reason in results)


def test_a_single_extreme_rated_review_with_real_text_is_not_flagged(
    session_factory, user, restaurant
):
    """Genuine enthusiasm is not spam. 5 stars plus a paragraph is a good review."""

    with session_factory() as db:
        review = _review(
            db,
            user,
            restaurant,
            text=(
                "Honestly one of the best meals I have had in Bengaluru this year. "
                "The filter coffee is roasted in house and the dosa is fermented "
                "properly. Prices are fair for the neighbourhood."
            ),
            rating=5.0,
        )
        db.commit()

    assert not review.fraud_flag
