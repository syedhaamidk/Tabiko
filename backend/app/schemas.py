from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .models import NoiseLevel, RestaurantType, ReviewerType, VerificationTier

NonBlankString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
PositiveId = Annotated[int, Field(gt=0)]
Rating = Annotated[float, Field(ge=1, le=5)]
ReviewText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5_000)]
Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]

# Canonical values the restaurant filters accept. Published through
# GET /filter-options so the UI menu and the API cannot drift apart.
DIETARY_FLAGS: tuple[str, ...] = (
    "veg",
    "non_veg",
    "vegan",
    "jain",
    "halal",
    "egg",
    "gluten_free",
)

GOOD_FOR_TAGS: tuple[str, ...] = (
    "date",
    "solo",
    "group",
    "family",
    "work",
    "late_night",
    "outdoor",
    "pet_friendly",
    "budget",
    "quick_bite",
    "live_music",
)


def _known_tags(
    value: list[str] | None, allowed: tuple[str, ...], field: str
) -> list[str] | None:
    """Validate reader-supplied tags against a vocabulary.

    Unknown values are rejected rather than quietly stored. A tag outside the
    vocabulary is invisible to every filter and to the count that reports how
    many places match one, so storing it would look like coverage while being
    permanently unreachable. Duplicates are collapsed and order is preserved so
    the stored string is stable.
    """

    if value is None:
        return None
    unknown = [tag for tag in value if tag not in allowed]
    if unknown:
        raise ValueError(
            f"unknown {field} value(s): {', '.join(sorted(set(unknown)))}. "
            f"Allowed: {', '.join(allowed)}"
        )
    return list(dict.fromkeys(value))


# Access needs are stored per place but had no way to be asked for, even though
# over a thousand places carry them. Promoted to a filter group so the data is
# reachable rather than merely collected.
ACCESSIBILITY_FLAGS: tuple[str, ...] = (
    "wheelchair_accessible",
    "not_wheelchair_accessible",
    "seating",
)


class HealthOut(BaseModel):
    status: str
    database: str


class UserRegister(BaseModel):
    name: Annotated[NonBlankString, Field(max_length=255)]
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("password must not exceed 72 UTF-8 bytes")
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class TokenOut(BaseModel):
    """A short-lived access token plus the session that can renew it.

    `expires_in` is included so the client can refresh slightly before it lapses
    rather than discovering the expiry as a failed request.
    """

    access_token: str
    token_type: str = "bearer"
    # Only the digest of this is stored server-side, and it is what /auth/logout
    # revokes. Losing it means losing the session, not just the access token.
    refresh_token: str
    expires_in: int


class RefreshIn(BaseModel):
    refresh_token: Annotated[str, StringConstraints(min_length=20, max_length=200)]


class ProfileUpdate(BaseModel):
    reviewer_type: ReviewerType | None = None
    cuisine_specialty: Annotated[NonBlankString, Field(max_length=255)] | None = None

    @model_validator(mode="after")
    def validate_specialty(self) -> ProfileUpdate:
        if self.cuisine_specialty is not None and self.reviewer_type not in {
            None,
            ReviewerType.cuisine_specialist,
        }:
            raise ValueError(
                "cuisine_specialty requires reviewer_type=cuisine_specialist"
            )
        return self


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    is_founding_reviewer: bool
    is_admin: bool
    reviewer_type: ReviewerType
    cuisine_specialty: str | None = None
    is_critic_verified: bool
    created_at: datetime


class RestaurantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source: str
    source_id: str | None = None
    latitude: float
    longitude: float
    address: str | None = None
    cuisine_tags: str | None = None
    type_tag: RestaurantType
    dietary_flags: str | None = None
    price_tier: int | None = None
    hygiene_score: float | None = None
    theme_id: str | None = None
    noise_level: NoiseLevel
    good_for: str | None = None
    accessibility_flags: str | None = None
    menu_last_confirmed: datetime | None = None
    # Only populated when the request supplied an origin, so the UI can show
    # "820 m away" without a second round trip.
    distance_m: float | None = None


class CravingSearchResult(BaseModel):
    restaurant: RestaurantOut
    relevance: float
    # Query terms that appear nowhere in the indexed text. Non-empty means the
    # ranking covers only part of what was asked, which the UI must disclose
    # rather than present as a confident answer.
    unmatched_terms: tuple[str, ...] = ()


class RestaurantPointOut(BaseModel):
    """Minimal record for drawing map markers.

    A city-wide set is thousands of rows; sending the full `RestaurantOut` for
    each one is megabytes of addresses and review counts the map never reads.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    latitude: float
    longitude: float
    cuisine_tags: str | None = None
    type_tag: RestaurantType
    distance_m: float | None = None


class DishCreate(BaseModel):
    name: Annotated[NonBlankString, Field(max_length=255)]
    tags: Annotated[NonBlankString, Field(max_length=255)] | None = None
    # Set from a completed upload. Only paths this service issued are accepted;
    # see `app.main._validated_image_url`.
    image_url: Annotated[str, Field(max_length=500)] | None = None

    @field_validator("tags", mode="before")
    @classmethod
    def blank_tags_mean_no_tags(cls, value: object) -> object:
        """Treat an empty or whitespace-only `tags` as absent.

        An HTML form with an untouched text box submits `""`, not `null`, and
        `NonBlankString` rejects the empty string even though the field is
        declared optional. That made the single "Add dish" button 422 on every
        submission where the reader left the tags box alone -- which is nearly
        all of them, and the whole reason the bulk paste exists.

        The unit tests never caught it because the test helper passes
        `tags=None`, so it posts `null`. Only driving the real form found it.

        Applied to `tags` only. A blank dish *name* is a genuine mistake and is
        still rejected, as is a blank `cuisine_specialty` or `fraud_reason`.
        """

        if isinstance(value, str) and not value.strip():
            return None
        return value


class DishBulkCreate(BaseModel):
    """A pasted menu.

    Free text rather than a structured list, because the reader has a menu board
    in front of them and not a JSON editor. One dish per line, tags after a comma.
    """

    text: Annotated[str, StringConstraints(min_length=1, max_length=20000)]


class UploadOut(BaseModel):
    """A stored image, addressed by the path it is served from."""

    url: str
    content_type: str
    size: int


class DishContributor(BaseModel):
    """Whoever added the dish.

    `is_critic_verified` is surfaced so the UI can mark a menu that came from
    someone the project already vouches for.
    """

    id: int
    name: str
    is_critic_verified: bool


class DishBulkResult(BaseModel):
    """What a paste actually did.

    `skipped` is returned rather than raised as an error, because a list that
    overlaps the existing menu is the normal case and refusing the batch would
    throw away the new dishes along with the duplicates.
    """

    added: list[DishOut]
    skipped: list[str]


class DishOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    restaurant_id: int
    name: str
    tags: str | None = None
    avg_rating: float
    review_count: int
    image_url: str | None = None
    added_by: DishContributor | None = None


class ReviewCreate(BaseModel):
    restaurant_id: PositiveId
    dish_id: PositiveId | None = None
    rating: Rating
    text: ReviewText | None = None
    client_request_id: UUID | None = None
    claimed_verification_tier: VerificationTier = VerificationTier.unverified
    user_lat: Latitude | None = None
    user_lon: Longitude | None = None

    # Occasion and diet tags supplied by the reader.
    #
    # These are the two emptiest dimensions in the whole app -- `good_for` sits
    # at 3.7% of places and dietary flags at 8.7% -- and no amount of re-ingestion
    # will fill them, because OpenStreetMap does not record whether somewhere is
    # good for a date or serves vegan food. The only people who know are the ones
    # who were just there, and they are already typing a review.
    #
    # Both default to None, so an existing client that sends neither is
    # unaffected. Unknown values are rejected rather than stored, because a tag
    # outside the vocabulary is invisible to every filter and would look like
    # data while being unreachable.
    good_for: list[str] | None = None
    dietary: list[str] | None = None
    # A path returned by a completed upload, not an arbitrary URL. A client that
    # could set this to anything would be able to make the app render an image
    # from anywhere, which is a tracking pixel at best.
    image_url: Annotated[str, Field(max_length=500)] | None = None

    @field_validator("good_for")
    @classmethod
    def good_for_must_be_known(cls, value: list[str] | None) -> list[str] | None:
        return _known_tags(value, GOOD_FOR_TAGS, "good_for")

    @field_validator("dietary")
    @classmethod
    def dietary_must_be_known(cls, value: list[str] | None) -> list[str] | None:
        return _known_tags(value, DIETARY_FLAGS, "dietary")

    @model_validator(mode="after")
    def coordinates_must_be_paired(self) -> ReviewCreate:
        if (self.user_lat is None) != (self.user_lon is None):
            raise ValueError("user_lat and user_lon must be provided together")
        return self


class ReviewerInfo(BaseModel):
    id: int
    name: str
    reviewer_type: ReviewerType
    is_critic_verified: bool
    cuisine_specialty: str | None = None
    is_regular_here: bool


class ReviewModerationUpdate(BaseModel):
    fraud_flag: bool
    fraud_reason: Annotated[NonBlankString, Field(max_length=255)] | None = None

    @model_validator(mode="after")
    def require_reason_when_flagging(self) -> ReviewModerationUpdate:
        if self.fraud_flag and self.fraud_reason is None:
            raise ValueError("fraud_reason is required when flagging a review")
        return self


class ReviewOut(BaseModel):
    id: int
    user_id: int
    restaurant_id: int
    dish_id: int | None = None
    client_request_id: UUID | None = None
    rating: float
    text: str | None = None
    verification_tier: VerificationTier
    fraud_flag: bool
    fraud_reason: str | None = None
    created_at: datetime
    image_url: str | None = None
    reviewer: ReviewerInfo


class PublicUser(BaseModel):
    """Another reader, as far as anyone else needs to know about them.

    Deliberately thin: a display name, what they call themselves, and the two
    counts the follow button needs. No email, no location, nothing that would
    make a public directory of readers.
    """

    id: int
    name: str
    reviewer_type: ReviewerType
    is_critic_verified: bool
    cuisine_specialty: str | None = None
    follower_count: int = 0
    following_count: int = 0
    is_following: bool = False


class FollowStatus(BaseModel):
    is_following: bool
    follower_count: int
    following_count: int


class FollowingOut(BaseModel):
    users: list[PublicUser]
    count: int


class FeedEntry(BaseModel):
    """One review in the following feed, with enough of its place to render it."""

    review: ReviewOut
    restaurant_name: str
    restaurant_cuisine: str | None = None
    restaurant_latitude: float | None = None
    restaurant_longitude: float | None = None


class FeedOut(BaseModel):
    entries: list[FeedEntry]
    count: int


class FavoriteOut(BaseModel):
    """A saved place.

    Carries restaurant_id rather than the whole record: the card list already
    has the details, and a shortlist is read alongside one. `saved_at` lets the
    UI say when a place was bookmarked without a second request.
    """

    id: int
    user_id: int
    restaurant_id: int
    created_at: datetime


class RestaurantStatsOut(BaseModel):
    # Average and review_count describe reviews included in public aggregates.
    average_rating: float | None
    review_count: int
    submitted_review_count: int
    trusted_review_count: int
    flagged_review_count: int
