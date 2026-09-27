"""
Database models for the archived Tabiko app draft.

Design notes:
- Restaurant: the venue itself. cuisine_tags / type_tag / dietary_flags are
  filled in by the classification pipeline, not trusted from raw source data.
- Dish: individual menu items get their own rating, separate from the
  restaurant-level aggregate.
- Review: tied to either a dish or a restaurant. verification_tier is what
  makes a review count toward trust score.
- ThemeToken: one row per cuisine/type "family" — the frontend fetches this
  to decide which visual theme to render.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base


class RestaurantType(str, enum.Enum):
    cafe = "cafe"
    family_restaurant = "family_restaurant"
    fine_dine = "fine_dine"
    cloud_kitchen = "cloud_kitchen"
    darshini_qsr = "darshini_qsr"
    bar_microbrewery = "bar_microbrewery"
    food_court_stall = "food_court_stall"
    unclassified = "unclassified"


class VerificationTier(str, enum.Enum):
    unverified = "unverified"       # posted with no proof
    checked_in = "checked_in"       # location-confirmed visit
    order_confirmed = "order_confirmed"  # linked to an order/receipt


class NoiseLevel(str, enum.Enum):
    quiet = "quiet"
    moderate = "moderate"
    loud = "loud"
    unknown = "unknown"


class ReviewerType(str, enum.Enum):
    normal = "normal"                    # everyday diner — the default
    food_critic = "food_critic"          # self-declared; only badge-verified once is_critic_verified is set
    cuisine_specialist = "cuisine_specialist"  # declares a cuisine focus via cuisine_specialty


class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, index=True)
    source = Column(String(50), nullable=False)          # "overpass", "foursquare", "manual"
    source_id = Column(String(100), unique=True, nullable=True)

    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    address = Column(String(500), nullable=True)

    # Raw tag from the source (e.g. OSM's "cuisine" value) — kept for reference,
    # NOT shown to users directly. The classifier reconciles this with menu/review text.
    raw_cuisine_tag = Column(String(255), nullable=True)

    # Classifier output — the fields the app actually trusts and displays.
    cuisine_tags = Column(String(500), nullable=True)     # comma-separated for now
    type_tag = Column(Enum(RestaurantType), default=RestaurantType.unclassified)
    dietary_flags = Column(String(255), nullable=True)    # comma-separated: veg,non_veg,vegan,jain,halal

    price_tier = Column(Integer, nullable=True)           # 1 (cheap) - 4 (expensive)
    hygiene_score = Column(Float, nullable=True)           # derived from review text, 0-5
    theme_id = Column(String(50), nullable=True)           # points into theme_tokens.json

    # Pain points from the original brainstorm, now first-class fields
    noise_level = Column(Enum(NoiseLevel), default=NoiseLevel.unknown)
    good_for = Column(String(255), nullable=True)          # comma-separated: date,solo,group,work
    accessibility_flags = Column(String(255), nullable=True)  # comma-separated: ramp,seating,quiet_space

    menu_last_confirmed = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    dishes = relationship("Dish", back_populates="restaurant", cascade="all, delete-orphan")
    reviews = relationship("Review", back_populates="restaurant", cascade="all, delete-orphan")


class Dish(Base):
    __tablename__ = "dishes"

    id = Column(Integer, primary_key=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    name = Column(String(255), nullable=False)
    tags = Column(String(255), nullable=True)  # e.g. "spicy,veg,bestseller"
    avg_rating = Column(Float, default=0.0)
    review_count = Column(Integer, default=0)

    restaurant = relationship("Restaurant", back_populates="dishes")
    reviews = relationship("Review", back_populates="dish", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_founding_reviewer = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)

    # Reviewer identity — helps readers weigh a review appropriately.
    # reviewer_type is self-declared at signup/profile-edit time. food_critic
    # is NOT trusted just because someone picks it: is_critic_verified stays
    # False until an admin confirms it (no admin UI yet — see README), so the
    # frontend should show "self-identified critic" vs "verified critic"
    # differently until that exists.
    reviewer_type = Column(Enum(ReviewerType), default=ReviewerType.normal, nullable=False)
    cuisine_specialty = Column(String(255), nullable=True)  # e.g. "South Indian" — only meaningful if cuisine_specialist
    is_critic_verified = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    reviews = relationship("Review", back_populates="user")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    dish_id = Column(Integer, ForeignKey("dishes.id"), nullable=True)

    rating = Column(Float, nullable=False)   # 1-5
    text = Column(Text, nullable=True)

    verification_tier = Column(
        Enum(VerificationTier), default=VerificationTier.unverified, nullable=False
    )
    fraud_flag = Column(Boolean, default=False)
    fraud_reason = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="reviews")
    restaurant = relationship("Restaurant", back_populates="reviews")
    dish = relationship("Dish", back_populates="reviews")
