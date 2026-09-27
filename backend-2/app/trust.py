"""
v1 trust scoring — deliberately simple, rule-based checks you can run at
review-creation time. This is the seed of the GSRank-style fraud clustering
discussed earlier (timing, phrasing similarity, reviewer group size); start
here, then move the pattern-matching into a scheduled job once you have
enough review volume for clusters to be meaningful.
"""

import math
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from . import models

# Distance within which a submitted lat/lon is trusted as "actually there".
# 150m covers GPS drift plus being anywhere on a large property/mall floor.
CHECKIN_RADIUS_METERS = 150

# How many GPS-verified visits to ONE restaurant before we call someone
# a "regular" there. Deliberately restaurant-specific, not a global user
# stat — being a regular at your campus canteen says nothing about whether
# you've been to a cafe across town.
REGULAR_VISIT_THRESHOLD = 3

POSITIVE_HYGIENE_WORDS = ["clean", "hygienic", "spotless", "fresh", "tidy"]
NEGATIVE_HYGIENE_WORDS = ["dirty", "unhygienic", "cockroach", "stale", "smell", "insect", "filthy", "roach"]


def score_review(db: Session, review: models.Review) -> None:
    """Mutates review.fraud_flag / fraud_reason in place. Call before commit."""

    suspicious_score = 0
    reasons = []

    if review.verification_tier == models.VerificationTier.unverified:
        suspicious_score += 1

    if review.rating in (1.0, 5.0) and (not review.text or len(review.text) < 15):
        suspicious_score += 1
        reasons.append("extreme rating with little/no text")

    # Signal: burst detection — many reviews for the same restaurant in a short window.
    recent_window = datetime.utcnow() - timedelta(hours=1)
    recent_count = (
        db.query(models.Review)
        .filter(
            models.Review.restaurant_id == review.restaurant_id,
            models.Review.created_at >= recent_window,
        )
        .count()
    )
    if recent_count >= 5:
        suspicious_score += 2
        reasons.append(f"{recent_count} reviews for this restaurant in the last hour")

    if suspicious_score >= 2:
        review.fraud_flag = True
        review.fraud_reason = "; ".join(reasons) if reasons else "pattern-based flag"


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in meters."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def resolve_verification_tier(
    restaurant: models.Restaurant,
    claimed_tier: models.VerificationTier,
    user_lat: float | None,
    user_lon: float | None,
) -> models.VerificationTier:
    """
    Never trust a client-declared tier directly — a client can claim anything.
    checked_in is only granted if the submitted coordinates are actually
    within range of the restaurant. order_confirmed isn't implementable
    without a real receipt/order-upload flow, so it's downgraded here until
    that exists (see README) rather than silently trusted.
    """
    if claimed_tier == models.VerificationTier.order_confirmed:
        # No receipt-verification pipeline yet — don't let the client just assert this.
        claimed_tier = models.VerificationTier.unverified

    if user_lat is not None and user_lon is not None:
        distance = haversine_meters(user_lat, user_lon, restaurant.latitude, restaurant.longitude)
        if distance <= CHECKIN_RADIUS_METERS:
            return models.VerificationTier.checked_in

    return models.VerificationTier.unverified


def score_hygiene_mention(text: str | None) -> float | None:
    """
    Returns a -1..+1 signal from hygiene-related keywords in review text,
    or None if the text doesn't mention hygiene at all (so it doesn't drag
    the restaurant's score toward neutral just because most reviews don't
    bring it up).
    """
    if not text:
        return None
    lowered = text.lower()
    pos_hits = sum(1 for w in POSITIVE_HYGIENE_WORDS if w in lowered)
    neg_hits = sum(1 for w in NEGATIVE_HYGIENE_WORDS if w in lowered)
    if pos_hits == 0 and neg_hits == 0:
        return None
    total = pos_hits + neg_hits
    return (pos_hits - neg_hits) / total


def update_hygiene_score(db: Session, restaurant: models.Restaurant) -> None:
    """
    Recomputes hygiene_score (0-5) from all reviews that actually mention
    hygiene, weighted toward recent ones. Cheap keyword approach — swap for
    the LLM/embedding classifier later, same as cuisine classification.
    """
    reviews = (
        db.query(models.Review)
        .filter(models.Review.restaurant_id == restaurant.id)
        .order_by(models.Review.created_at.desc())
        .limit(100)
        .all()
    )
    signals = [score_hygiene_mention(r.text) for r in reviews]
    signals = [s for s in signals if s is not None]
    if not signals:
        return  # leave hygiene_score as None — no data, don't fabricate one
    avg_signal = sum(signals) / len(signals)  # -1..+1
    restaurant.hygiene_score = round(2.5 + avg_signal * 2.5, 1)  # map to 0-5


def is_regular_at_restaurant(db: Session, user_id: int, restaurant_id: int) -> bool:
    """A 'regular' here means real, GPS-verified visit history at THIS
    restaurant — never self-claimed, since that's exactly the kind of trust
    signal that's worthless if anyone can just assert it."""
    count = (
        db.query(models.Review)
        .filter(
            models.Review.user_id == user_id,
            models.Review.restaurant_id == restaurant_id,
            models.Review.verification_tier == models.VerificationTier.checked_in,
        )
        .count()
    )
    return count >= REGULAR_VISIT_THRESHOLD
