"""
Database models for the Tabiko app.

Design notes:
- Restaurant: the venue itself. cuisine_tags / type_tag / dietary_flags are
  filled in by the classification pipeline, not trusted from raw source data.
- Dish: individual menu items get their own rating, separate from the
  restaurant-level aggregate. review_count excludes fraud-flagged ratings.
- Review: tied to either a dish or a restaurant. verification_tier is what
  makes a review count toward trusted aggregates.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


def utc_now() -> datetime:
    """Return naive UTC for consistency with SQLAlchemy's portable DateTime."""

    return datetime.now(timezone.utc).replace(tzinfo=None)


class RestaurantType(str, enum.Enum):
    cafe = "cafe"
    family_restaurant = "family_restaurant"
    fine_dine = "fine_dine"
    cloud_kitchen = "cloud_kitchen"
    darshini_qsr = "darshini_qsr"
    bar_microbrewery = "bar_microbrewery"
    food_court_stall = "food_court_stall"
    canteen = "canteen"
    dhaba = "dhaba"
    street_stall = "street_stall"
    hotel_restaurant = "hotel_restaurant"
    takeaway = "takeaway"
    unclassified = "unclassified"


class VerificationTier(str, enum.Enum):
    unverified = "unverified"  # posted with no proof
    checked_in = "checked_in"  # device-reported location confirmation
    order_confirmed = "order_confirmed"  # linked to an order/receipt


class NoiseLevel(str, enum.Enum):
    quiet = "quiet"
    moderate = "moderate"
    loud = "loud"
    unknown = "unknown"


class ReviewerType(str, enum.Enum):
    normal = "normal"
    food_critic = "food_critic"
    cuisine_specialist = "cuisine_specialist"


class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, index=True)
    source = Column(String(50), nullable=False)  # "overpass", "foursquare", "manual"
    source_id = Column(String(100), unique=True, nullable=True)

    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    address = Column(String(500), nullable=True)

    # Raw tag from the source (e.g. OSM's "cuisine" value) — kept for reference,
    # NOT shown to users directly. The classifier reconciles this with menu/review text.
    raw_cuisine_tag = Column(String(255), nullable=True)

    # Classifier output — the fields the app actually trusts and displays.
    cuisine_tags = Column(String(500), nullable=True)  # comma-separated for now
    type_tag = Column(
        Enum(RestaurantType),
        nullable=False,
        default=RestaurantType.unclassified,
    )
    # comma-separated: veg, non_veg, vegan, jain, halal
    dietary_flags = Column(String(255), nullable=True)

    price_tier = Column(
        Integer,
        CheckConstraint("price_tier >= 1 AND price_tier <= 4", name="ck_price_tier"),
        nullable=True,
    )  # 1 (cheap) - 4 (expensive)
    hygiene_score = Column(
        Float,
        CheckConstraint(
            "hygiene_score >= 0 AND hygiene_score <= 5", name="ck_hygiene_score"
        ),
        nullable=True,
    )  # derived from review text, 0-5
    theme_id = Column(String(50), nullable=True)  # points into theme_tokens.json

    noise_level = Column(Enum(NoiseLevel), nullable=False, default=NoiseLevel.unknown)
    # comma-separated: date, solo, group, work
    good_for = Column(String(255), nullable=True)
    # comma-separated: ramp, seating, quiet_space
    accessibility_flags = Column(String(255), nullable=True)

    menu_last_confirmed = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    dishes = relationship(
        "Dish", back_populates="restaurant", cascade="all, delete-orphan"
    )
    reviews = relationship(
        "Review", back_populates="restaurant", cascade="all, delete-orphan"
    )
    favorites = relationship(
        "Favorite", back_populates="restaurant", cascade="all, delete-orphan"
    )


class Dish(Base):
    __tablename__ = "dishes"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "name", name="uq_dish_restaurant_name"),
        CheckConstraint("review_count >= 0", name="ck_dish_review_count"),
    )

    id = Column(Integer, primary_key=True)
    restaurant_id = Column(
        Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False)
    tags = Column(String(255), nullable=True)  # e.g. "spicy,veg,bestseller"
    avg_rating = Column(Float, nullable=False, default=0.0)
    review_count = Column(Integer, nullable=False, default=0)
    # A URL, never the bytes. See migration 0008 for why the image is a file on
    # the same volume rather than a blob in this table.
    image_url = Column(String(500), nullable=True)
    # Whoever typed it in. Nullable because dishes can be imported or seeded, and
    # a dish nobody claimed is honest to show as unattributed rather than invented.
    added_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Set when the person is the one who should be believed about this menu, which
    # for now means a verified critic rather than an owner claim we do not have.
    created_at = Column(DateTime, nullable=False, default=utc_now)

    restaurant = relationship("Restaurant", back_populates="dishes")
    added_by = relationship("User", back_populates="dishes")
    reviews = relationship("Review", back_populates="dish", passive_deletes=True)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    # Nullable only for legacy rows created before real authentication existed.
    password_hash = Column(String(255), nullable=True)
    # The stable subject Google issues for this account in this project. Unique
    # and nullable: most readers never have one. Set exactly once, on first
    # Google sign-in — by verified-email link or by account creation. Indexed
    # like email, because the per-login lookup is by subject.
    google_sub = Column(String(255), unique=True, nullable=True, index=True)
    is_founding_reviewer = Column(Boolean, nullable=False, default=False)
    is_admin = Column(Boolean, nullable=False, default=False)
    reviewer_type = Column(
        Enum(ReviewerType), nullable=False, default=ReviewerType.normal
    )
    cuisine_specialty = Column(String(255), nullable=True)
    is_critic_verified = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    reviews = relationship("Review", back_populates="user")
    favorites = relationship(
        "Favorite", back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    dishes = relationship("Dish", back_populates="added_by")
    # Two relationships to the same table, so they need telling apart explicitly.
    # `following` is who this reader follows, `followers` who follows them.
    following = relationship(
        "Follow",
        foreign_keys="Follow.follower_id",
        back_populates="follower",
        cascade="all, delete-orphan",
    )
    followers = relationship(
        "Follow",
        foreign_keys="Follow.followed_id",
        back_populates="followed",
        cascade="all, delete-orphan",
    )


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_review_rating"),
        UniqueConstraint("user_id", "client_request_id", name="uq_review_user_request"),
        Index("ix_reviews_restaurant_created", "restaurant_id", "created_at"),
        Index("ix_reviews_user_created", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    restaurant_id = Column(
        Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )
    dish_id = Column(
        Integer, ForeignKey("dishes.id", ondelete="SET NULL"), nullable=True
    )
    # Optional caller-generated key used to reject duplicate review submissions.
    client_request_id = Column(String(36), nullable=True)

    rating = Column(Float, nullable=False)  # 1-5
    text = Column(Text, nullable=True)

    verification_tier = Column(
        Enum(VerificationTier), default=VerificationTier.unverified, nullable=False
    )
    fraud_flag = Column(Boolean, nullable=False, default=False)
    fraud_reason = Column(String(255), nullable=True)

    created_at = Column(DateTime, nullable=False, default=utc_now)

    # A URL, never the bytes, for the same reason as `Dish.image_url`.
    image_url = Column(String(500), nullable=True)

    user = relationship("User", back_populates="reviews")
    restaurant = relationship("Restaurant", back_populates="reviews")
    dish = relationship("Dish", back_populates="reviews")


class RefreshToken(Base):
    """A session, held by the digest of a long-lived refresh token.

    Only the SHA-256 is stored, so reading this table does not hand anyone a
    usable credential. Rotation is what makes theft recoverable: `rotated_at`
    marks a spent token, and `replaced_by_token_hash` keeps the chain so a replay
    can be told apart from the client's own concurrent refresh.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        # Lookups are always "this digest", and the listing is "my live sessions".
        Index("ix_refresh_tokens_user_revoked", "user_id", "revoked_at"),
        Index("ix_refresh_tokens_expires", "expires_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    # Set when the token is exchanged, and when the session is ended. Both are
    # kept rather than deleted so a replay is detectable instead of merely absent.
    rotated_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    replaced_by_token_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    user = relationship("User", back_populates="refresh_tokens")


class Favorite(Base):
    """A place a reader has saved for later.

    The unique pair is what makes saving idempotent: tapping the button twice, or
    retrying a flaky request, cannot produce a duplicate row.
    """

    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "restaurant_id", name="uq_favorite_user_restaurant"
        ),
        # Listing a reader's saves is always "newest first for this reader", which
        # is the same query the index serves.
        Index("ix_favorites_user_created", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    restaurant_id = Column(
        Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime, nullable=False, default=utc_now)

    user = relationship("User", back_populates="favorites")
    restaurant = relationship("Restaurant", back_populates="favorites")


class Follow(Base):
    """One reader following another. Immediate, no approval, no requests.

    The unique pair is the whole feature: it makes following idempotent, so the
    endpoint needs no read-before-write and a retried request cannot double up.
    The check constraint is the only place a self-follow cannot be written from.
    """

    __tablename__ = "follows"
    __table_args__ = (
        UniqueConstraint("follower_id", "followed_id", name="uq_follow_pair"),
        CheckConstraint("follower_id != followed_id", name="ck_follow_not_self"),
        # "Who do I follow" and "who follows me" are the only two questions
        # asked, and both are asked on every page that renders a reviewer.
        Index("ix_follows_follower_created", "follower_id", "created_at"),
        Index("ix_follows_followed", "followed_id"),
    )

    id = Column(Integer, primary_key=True)
    follower_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    followed_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime, nullable=False, default=utc_now)

    follower = relationship(
        "User", foreign_keys=[follower_id], back_populates="following"
    )
    followed = relationship(
        "User", foreign_keys=[followed_id], back_populates="followers"
    )


class RateLimit(Base):
    """One fixed window of one rate-limit bucket.

    The window is part of the primary key, so a new minute is a new row rather
    than a reset-and-race. `count` is maintained by a single atomic
    `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`, which is what lets several
    worker processes share one allowance instead of each enforcing its own.
    """

    __tablename__ = "rate_limits"
    __table_args__ = (
        # The sweep that clears expired windows looks up by age alone; nothing
        # else queries the table without also constraining the scope and key.
        Index("ix_rate_limits_window_start", "window_start"),
    )

    scope = Column(String(64), primary_key=True)
    client_key = Column(String(255), primary_key=True)
    window_start = Column(Integer, primary_key=True)
    count = Column(Integer, nullable=False, default=0, server_default="0")
