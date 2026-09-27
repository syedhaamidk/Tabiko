from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr

from .models import NoiseLevel, RestaurantType, ReviewerType, VerificationTier


# ---------- Auth ----------

class UserRegister(BaseModel):
    name: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProfileUpdate(BaseModel):
    # reviewer_type is self-declared. cuisine_specialty only makes sense
    # alongside reviewer_type=cuisine_specialist but isn't enforced server-side
    # yet — garbage-in for a mismatched combo just won't render meaningfully
    # in the UI badge.
    reviewer_type: Optional[ReviewerType] = None
    cuisine_specialty: Optional[str] = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    is_founding_reviewer: bool
    reviewer_type: ReviewerType
    cuisine_specialty: Optional[str] = None
    is_critic_verified: bool


# ---------- Restaurants ----------

class RestaurantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    latitude: float
    longitude: float
    address: Optional[str] = None
    cuisine_tags: Optional[str] = None
    type_tag: RestaurantType
    dietary_flags: Optional[str] = None
    price_tier: Optional[int] = None
    hygiene_score: Optional[float] = None
    theme_id: Optional[str] = None
    noise_level: NoiseLevel
    good_for: Optional[str] = None
    accessibility_flags: Optional[str] = None
    menu_last_confirmed: Optional[datetime] = None


class CravingSearchResult(BaseModel):
    restaurant: RestaurantOut
    relevance: float


# ---------- Dishes ----------

class DishCreate(BaseModel):
    name: str
    tags: Optional[str] = None


class DishOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    restaurant_id: int
    name: str
    tags: Optional[str] = None
    avg_rating: float
    review_count: int


# ---------- Reviews ----------

class ReviewCreate(BaseModel):
    restaurant_id: int
    dish_id: Optional[int] = None
    rating: float
    text: Optional[str] = None
    # Client MAY claim a tier, but the server re-derives it — see trust.resolve_verification_tier.
    claimed_verification_tier: VerificationTier = VerificationTier.unverified
    # Optional device coordinates at time of posting, used to verify checked_in.
    user_lat: Optional[float] = None
    user_lon: Optional[float] = None


class ReviewerInfo(BaseModel):
    id: int
    name: str
    reviewer_type: ReviewerType
    is_critic_verified: bool
    cuisine_specialty: Optional[str] = None
    # Computed, not stored — see trust.is_regular_at_restaurant. True once this
    # user has enough GPS-verified visits to THIS restaurant specifically.
    is_regular_here: bool


class ReviewOut(BaseModel):
    id: int
    restaurant_id: int
    dish_id: Optional[int] = None
    rating: float
    text: Optional[str] = None
    verification_tier: VerificationTier
    fraud_flag: bool
    fraud_reason: Optional[str] = None
    created_at: datetime
    reviewer: ReviewerInfo
