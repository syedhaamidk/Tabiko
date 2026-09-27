"""
v1 trust scoring — deliberately simple, rule-based checks you can run at
review-creation time. This is the seed of the GSRank-style fraud clustering
discussed earlier (timing, phrasing similarity, reviewer group size); start
here, then move the pattern-matching into a scheduled job once you have
enough review volume for clusters to be meaningful.
"""

import math
import re
from datetime import timedelta

from sqlalchemy.orm import Session

from . import models
from .models import utc_now

CHECKIN_RADIUS_METERS = 150
REGULAR_VISIT_THRESHOLD = 3

# Hygiene vocabulary, matched on whole words only.
#
# Every word here has to be about the *premises*, not the food. "Fresh" was in
# the positive list until this was exercised against real review text, where it
# turned out to be a false positive on almost every sentence: "the dosa was
# fresh off the tawa", "fresh filter coffee", "freshly ground masala" all scored
# a restaurant 5/5 on hygiene while saying nothing whatsoever about its kitchen.
# In a food review "fresh" describes the food roughly ten times for every time it
# describes the room, so it cannot be a hygiene signal.
#
# Word boundaries are equally load-bearing. Substring matching meant "roach"
# fired on "approach" and "encroach", "stale" fired on "stainless" and "install",
# "clean" fired on "unclean", and "fresh" fired on "refresh". A review saying
# "the staff took a practical approach" scored 0.0 -- a false negative and a
# false positive in the same sentence.
POSITIVE_HYGIENE_WORDS = (
    "clean",
    "hygienic",
    "hygiene",
    "spotless",
    "tidy",
    "sanitary",
    "immaculate",
    "immaculately",
)

NEGATIVE_HYGIENE_WORDS = (
    "dirty",
    "unhygienic",
    "filthy",
    "grimy",
    "cockroach",
    "roach",
    "roach(es)",
    "stale",
    "smelly",
    "insect",
    "insects",
    "flies",
    "greasy",
    "sticky",
)

_POSITIVE_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(word) for word in POSITIVE_HYGIENE_WORDS) + r")\b",
    re.IGNORECASE,
)
_NEGATIVE_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(word) for word in NEGATIVE_HYGIENE_WORDS) + r")\b",
    re.IGNORECASE,
)


def score_review(db: Session, review: models.Review) -> None:
    """Mutates review.fraud_flag / fraud_reason in place. Call before commit."""

    # Signal 1: unverified + extreme rating (1 or 5) is the weakest signal on its own,
    # but combine with others before flagging.
    suspicious_score = 0
    reasons: list[str] = []
    review.fraud_flag = False
    review.fraud_reason = None

    if review.verification_tier == models.VerificationTier.unverified:
        suspicious_score += 1

    if review.rating in (1.0, 5.0) and (not review.text or len(review.text) < 15):
        suspicious_score += 1
        reasons.append("extreme rating with little/no text")

    # Signal 2: burst detection is scoped to one reviewer at one restaurant.
    # A busy restaurant should not cause every normal review to be flagged.
    recent_window = utc_now() - timedelta(hours=1)
    recent_count = (
        db.query(models.Review)
        .filter(
            models.Review.user_id == review.user_id,
            models.Review.restaurant_id == review.restaurant_id,
            models.Review.created_at >= recent_window,
        )
        .count()
    )
    if recent_count >= 3:
        suspicious_score += 2
        reasons.append(
            f"{recent_count} rapid reviews from this user for this restaurant"
        )

    # A single weak signal is not enough for an automated visibility decision.
    if suspicious_score >= 3:
        review.fraud_flag = True
        review.fraud_reason = "; ".join(reasons) if reasons else "pattern-based flag"


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_meters = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * earth_radius_meters * math.asin(math.sqrt(a))


def resolve_verification_tier(
    restaurant: models.Restaurant,
    claimed_tier: models.VerificationTier,
    user_lat: float | None,
    user_lon: float | None,
) -> models.VerificationTier:
    """Re-derive a review tier instead of trusting a client-declared value.

    A check-in is device-reported and prevents naive remote claims, but it is
    not cryptographic proof of presence. Order confirmation stays unavailable
    until a receipt/order flow exists.
    """

    if user_lat is not None and user_lon is not None:
        distance = haversine_meters(
            user_lat, user_lon, restaurant.latitude, restaurant.longitude
        )
        if distance <= CHECKIN_RADIUS_METERS:
            return models.VerificationTier.checked_in
    return models.VerificationTier.unverified


def score_hygiene_mention(text: str | None) -> float | None:
    """Score how a review describes the premises' cleanliness.

    Returns None when the review says nothing about hygiene at all, which is the
    common case and must not be treated as neutral evidence. A restaurant's score
    is a mean over only the reviews that actually mentioned it, so one vague
    "nice place, tasty food" cannot drag a place down and one enthusiastic
    remark cannot carry it up.
    """

    if not text:
        return None
    positive_hits = len(_POSITIVE_PATTERN.findall(text))
    negative_hits = len(_NEGATIVE_PATTERN.findall(text))
    if positive_hits == 0 and negative_hits == 0:
        return None
    return (positive_hits - negative_hits) / (positive_hits + negative_hits)


def update_hygiene_score(db: Session, restaurant: models.Restaurant) -> None:
    reviews = (
        db.query(models.Review.text)
        .filter(
            models.Review.restaurant_id == restaurant.id,
            models.Review.fraud_flag.is_(False),
        )
        .order_by(models.Review.created_at.desc())
        .limit(100)
        .all()
    )
    signals = [
        signal
        for signal in (score_hygiene_mention(review.text) for review in reviews)
        if signal is not None
    ]
    if not signals:
        restaurant.hygiene_score = None
        return
    average_signal = sum(signals) / len(signals)
    restaurant.hygiene_score = round(2.5 + average_signal * 2.5, 1)


def is_regular_at_restaurant(db: Session, user_id: int, restaurant_id: int) -> bool:
    count = (
        db.query(models.Review)
        .filter(
            models.Review.user_id == user_id,
            models.Review.restaurant_id == restaurant_id,
            models.Review.verification_tier == models.VerificationTier.checked_in,
            models.Review.fraud_flag.is_(False),
        )
        .count()
    )
    return count >= REGULAR_VISIT_THRESHOLD
