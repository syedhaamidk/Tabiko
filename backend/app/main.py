from __future__ import annotations

import json
import math
import os
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, NamedTuple

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import and_, case, false, func, or_, select, text
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from . import (
    auth,
    classifier,
    craving_search,
    models,
    place_index,
    ratelimit,
    schemas,
    trust,
    uploads,
)
from .database import Base, engine, get_db
from .models import utc_now

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[models.User, Depends(auth.get_current_user)]
AdminUser = Annotated[models.User, Depends(auth.require_admin)]
ApiKeyHeader = Annotated[str | None, Header(alias="X-API-Key")]
API_KEY = os.getenv("TABIKO_API_KEY")
AUTO_CREATE_SCHEMA = os.getenv("TABIKO_AUTO_CREATE_SCHEMA", "true").lower() not in {
    "0",
    "false",
    "no",
}


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if AUTO_CREATE_SCHEMA:
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Tabiko API",
    version="0.5.0",
    description="Tabiko food radar: discovery, craving search, reviews, and trust signals.",
    lifespan=lifespan,
)

default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
configured_origins = os.getenv("TABIKO_CORS_ORIGINS")
allowed_origins = (
    [origin.strip() for origin in configured_origins.split(",") if origin.strip()]
    if configured_origins
    else default_origins
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Baseline headers on every response.

    None of these stop a determined attacker, and none of them substitute for a
    real origin. They close the cheap gaps: MIME sniffing, framing, referrer
    leakage, and the browser caching an authenticated response on a shared machine.
    """

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # The API returns JSON and the shell is a static file, so nothing here needs
    # to execute inline. 'unsafe-inline' for styles is required by the festival
    # styling, and 'unsafe-eval' is not permitted at all.
    #
    # Google Identity Services is the one exception, and only when this
    # deployment actually configured it: its script, its button iframe, and its
    # session-state requests all come from accounts.google.com. Without these
    # three the button silently never loads — and only in production, because
    # the Vite dev server does not send these headers. Gating on the client ID
    # keeps deployments without Google sign-in at the strict policy.
    google_sources = " https://accounts.google.com" if auth.GOOGLE_CLIENT_ID else ""
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        f"script-src 'self'{google_sources}; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        f"connect-src 'self'{google_sources}; "
        "object-src 'none'; "
        "base-uri 'self'; "
        f"frame-src 'self'{google_sources}; "
        "frame-ancestors 'none'",
    )
    if request.url.scheme == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    # Authenticated responses must not sit in a shared cache. Both spellings are
    # checked because the `/api` prefix is added by middleware in production and
    # by the dev proxy in development, so the path here depends on the deployment.
    path = request.url.path
    if any(
        path.startswith(prefix)
        for prefix in ("/favorites", "/auth", "/api/favorites", "/api/auth")
    ):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


THEME_TOKENS_PATH = Path(__file__).parent / "themes" / "theme_tokens.json"
with THEME_TOKENS_PATH.open(encoding="utf-8") as theme_file:
    THEME_TOKENS = json.load(theme_file)

# Anonymous request ceilings, per client address per minute. Deliberately modest:
# a person signs in rarely, so anything higher only widens the window for guessing
# a password. Note the counters are per worker process, so with `--workers 4` the
# real ceiling is about four times this. See `app/ratelimit.py`.
LOGIN_RATE_LIMIT = int(os.getenv("TABIKO_LOGIN_RATE_LIMIT", "10"))
REGISTER_RATE_LIMIT = int(os.getenv("TABIKO_REGISTER_RATE_LIMIT", "5"))
REFRESH_RATE_LIMIT = int(os.getenv("TABIKO_REFRESH_RATE_LIMIT", "30"))
# Google sign-in is anonymous and cheap like a login, so it is capped like one.
GOOGLE_RATE_LIMIT = int(os.getenv("TABIKO_GOOGLE_RATE_LIMIT", "10"))
# Bulk dish entry is the one write a reader can repeat, so it gets its own cap.
DISH_BULK_RATE_LIMIT = int(os.getenv("TABIKO_DISH_BULK_RATE_LIMIT", "20"))
# A real menu is 20-30 lines. Beyond this someone is bulk generating, not
# transcribing a board.
MAX_DISHES_PER_REQUEST = int(os.getenv("TABIKO_MAX_DISHES_PER_REQUEST", "80"))

# Following people. Both caps exist so the endpoints cannot be turned into a
# directory of every reader in the database.
#
# The search cap is generous for the current scale -- a city of 7,683 places has
# almost no readers yet -- and deliberately not a ranking. Suggesting people
# would be the first step toward the algorithmic timeline this feature exists to
# avoid; a reader types a name, or does not find them.
USER_SEARCH_LIMIT = int(os.getenv("TABIKO_USER_SEARCH_LIMIT", "25"))
# ~50 as specified. A chronological feed that paginates would be fine, but a
# page of nothing is not useful, and the alternative is the "load more" machinery
# for a feed nobody has 200 entries in.
FEED_LIMIT = int(os.getenv("TABIKO_FEED_LIMIT", "50"))


def _require_api_key(api_key: ApiKeyHeader = None) -> None:
    if API_KEY is None:
        return
    if api_key is None or not secrets.compare_digest(api_key, API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid X-API-Key header is required",
            headers={"WWW-Authenticate": "ApiKey"},
        )


WriteAccess = Annotated[None, Depends(_require_api_key)]


def _restaurant_or_404(db: Session, restaurant_id: int) -> models.Restaurant:
    restaurant = db.get(models.Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(
            status_code=404, detail="That flavor spot is not on the radar"
        )
    return restaurant


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _tag_membership(column, value: str):
    """Match one tag inside a comma-joined field, without matching a substring.

    The field is normalised to bare comma separators so both `a, b` and `a,b`
    match, and each pattern is anchored to a whole tag so `veg` cannot match
    `vegan`.

    The equality branch deliberately compares the *unescaped* value. LIKE escaping
    is only for the wildcard patterns, and reusing the escaped token here made
    every value containing an underscore — `non_veg`, `gluten_free`, and every
    accessibility flag — unmatchable no matter what was stored.
    """

    literal = value.strip().lower()
    if not literal:
        return false()
    token = _escape_like(literal)
    normalized = func.replace(func.lower(column), ", ", ",")
    return or_(
        normalized == literal,
        normalized.like(f"{token},%", escape="\\"),
        normalized.like(f"%,{token}", escape="\\"),
        normalized.like(f"%,{token},%", escape="\\"),
    )


def _serialize_review(db: Session, review: models.Review) -> schemas.ReviewOut:
    reviewer = review.user
    return schemas.ReviewOut(
        id=review.id,
        user_id=review.user_id,
        restaurant_id=review.restaurant_id,
        dish_id=review.dish_id,
        client_request_id=review.client_request_id,
        rating=review.rating,
        text=review.text,
        verification_tier=review.verification_tier,
        fraud_flag=review.fraud_flag,
        fraud_reason=review.fraud_reason,
        created_at=review.created_at,
        image_url=review.image_url,
        reviewer=schemas.ReviewerInfo(
            id=reviewer.id,
            name=reviewer.name,
            reviewer_type=reviewer.reviewer_type,
            is_critic_verified=reviewer.is_critic_verified,
            cuisine_specialty=reviewer.cuisine_specialty,
            is_regular_here=trust.is_regular_at_restaurant(
                db, reviewer.id, review.restaurant_id
            ),
        ),
    )


# ---------- Following people ----------


def _follower_count(db: Session, user_id: int) -> int:
    return db.query(models.Follow).filter_by(followed_id=user_id).count()


def _following_count(db: Session, user_id: int) -> int:
    return db.query(models.Follow).filter_by(follower_id=user_id).count()


def _public_user(
    db: Session, user: models.User, viewer_id: int | None
) -> schemas.PublicUser:
    return schemas.PublicUser(
        id=user.id,
        name=user.name,
        reviewer_type=user.reviewer_type,
        is_critic_verified=user.is_critic_verified,
        cuisine_specialty=user.cuisine_specialty,
        follower_count=_follower_count(db, user.id),
        following_count=_following_count(db, user.id),
        is_following=(
            db.query(models.Follow)
            .filter_by(follower_id=viewer_id, followed_id=user.id)
            .first()
            is not None
            if viewer_id is not None
            else False
        ),
    )


@app.get("/users/search", response_model=list[schemas.PublicUser])
def search_users(
    q: Annotated[str, Query(min_length=1, max_length=60)],
    db: DbSession,
    current_user: CurrentUser,
) -> list[schemas.PublicUser]:
    """Find readers by name, for the follow button to attach to.

    Capped and excludes self. A city of 7,683 places has almost no readers
    today, so this returns what exists and no more -- it is deliberately not a
    "suggested people" algorithm, because a ranking of people would be the
    beginning of the timeline this feature exists to avoid.
    """

    term = q.strip()
    if not term:
        return []
    rows = (
        db.query(models.User)
        .filter(
            models.User.id != current_user.id,
            models.User.name.ilike(f"%{term}%"),
        )
        .order_by(models.User.name)
        .limit(USER_SEARCH_LIMIT)
        .all()
    )
    return [_public_user(db, user, current_user.id) for user in rows]


@app.post("/users/{user_id}/follow", response_model=schemas.FollowStatus)
def follow_user(
    user_id: int, db: DbSession, current_user: CurrentUser
) -> schemas.FollowStatus:
    """Follow someone. Idempotent, and never yourself."""

    if user_id == current_user.id:
        raise HTTPException(
            status_code=422,
            detail="You cannot follow yourself, however much you want to.",
        )
    target = db.get(models.User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="No such reader")

    # The unique pair makes this idempotent, so a retried request that the first
    # one already accepted does not need a read-before-write or a lock.
    existing = (
        db.query(models.Follow)
        .filter_by(follower_id=current_user.id, followed_id=user_id)
        .first()
    )
    if existing is None:
        db.add(models.Follow(follower_id=current_user.id, followed_id=user_id))
        try:
            db.commit()
        except IntegrityError:
            # Lost a race with a concurrent tap. The state the caller wanted is
            # the state it is in, so this is a success.
            db.rollback()

    return schemas.FollowStatus(
        is_following=True,
        follower_count=_follower_count(db, user_id),
        following_count=_following_count(db, current_user.id),
    )


@app.delete("/users/{user_id}/follow", response_model=schemas.FollowStatus)
def unfollow_user(
    user_id: int, db: DbSession, current_user: CurrentUser
) -> schemas.FollowStatus:
    """Stop following. Idempotent, including for someone never followed."""

    if user_id == current_user.id:
        raise HTTPException(status_code=422, detail="You cannot unfollow yourself.")

    # Idempotent including for someone never followed, so a DELETE on a
    # relationship that is not there is a success rather than a 404. The button
    # can then be clicked twice, or a retried request can land, without the UI
    # having to reconcile an error.
    (
        db.query(models.Follow)
        .filter_by(follower_id=current_user.id, followed_id=user_id)
        .delete(synchronize_session=False)
    )
    db.commit()

    return schemas.FollowStatus(
        is_following=False,
        follower_count=_follower_count(db, user_id),
        following_count=_following_count(db, current_user.id),
    )


@app.get("/users/{user_id}/follow-status", response_model=schemas.FollowStatus)
def follow_status(
    user_id: int, db: DbSession, current_user: CurrentUser
) -> schemas.FollowStatus:
    target = db.get(models.User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="No such reader")
    return schemas.FollowStatus(
        is_following=(
            db.query(models.Follow)
            .filter_by(follower_id=current_user.id, followed_id=user_id)
            .first()
            is not None
        ),
        follower_count=_follower_count(db, user_id),
        following_count=_following_count(db, user_id),
    )


@app.get("/users/me/following", response_model=schemas.FollowingOut)
def my_following(db: DbSession, current_user: CurrentUser) -> schemas.FollowingOut:
    """Everyone this reader follows, newest follow first."""

    followed = (
        db.query(models.User)
        .join(models.Follow, models.Follow.followed_id == models.User.id)
        .filter(models.Follow.follower_id == current_user.id)
        .order_by(models.Follow.created_at.desc(), models.User.id)
        .all()
    )
    return schemas.FollowingOut(
        users=[_public_user(db, user, current_user.id) for user in followed],
        count=len(followed),
    )


def _followed_ids(db: Session, user_id: int) -> set[int]:
    return {
        row[0]
        for row in db.query(models.Follow.followed_id)
        .filter(models.Follow.follower_id == user_id)
        .all()
    }


@app.get("/feed/following", response_model=schemas.FeedOut)
def following_feed(db: DbSession, current_user: CurrentUser) -> schemas.FeedOut:
    """Reviews by people this reader follows, newest first.

    Strictly chronological. There is no ranking, no weighting, no "because you
    follow people who follow people who..." -- the point of the feature is that
    it is predictable, and a feed you cannot explain is a feed you cannot trust.
    """

    followed = _followed_ids(db, current_user.id)
    if not followed:
        return schemas.FeedOut(entries=[], count=0)

    reviews = (
        db.query(models.Review)
        .filter(
            models.Review.user_id.in_(followed),
            models.Review.fraud_flag.is_(False),
        )
        .order_by(models.Review.created_at.desc(), models.Review.id.desc())
        .limit(FEED_LIMIT)
        .all()
    )

    places = {
        place.id: place
        for place in db.query(models.Restaurant)
        .filter(models.Restaurant.id.in_({review.restaurant_id for review in reviews}))
        .all()
    }

    entries = [
        schemas.FeedEntry(
            review=_serialize_review(db, review),
            restaurant_name=(
                places[review.restaurant_id].name
                if review.restaurant_id in places
                else "A place that has since been removed"
            ),
            restaurant_cuisine=(
                places[review.restaurant_id].cuisine_tags
                if review.restaurant_id in places
                else None
            ),
            restaurant_latitude=(
                places[review.restaurant_id].latitude
                if review.restaurant_id in places
                else None
            ),
            restaurant_longitude=(
                places[review.restaurant_id].longitude
                if review.restaurant_id in places
                else None
            ),
        )
        for review in reviews
    ]
    return schemas.FeedOut(entries=entries, count=len(entries))


# ---------- Saved places ----------


@app.get("/favorites", response_model=list[schemas.FavoriteOut])
def list_favorites(
    db: DbSession,
    current_user: CurrentUser,
) -> list[models.Favorite]:
    """One reader's shortlist, newest save first."""

    return (
        db.query(models.Favorite)
        .filter(models.Favorite.user_id == current_user.id)
        .order_by(models.Favorite.created_at.desc(), models.Favorite.id.desc())
        .all()
    )


@app.get("/favorites/places", response_model=list[schemas.RestaurantOut])
def list_favorite_places(
    db: DbSession,
    current_user: CurrentUser,
) -> list[models.Restaurant]:
    """The saved places themselves, newest save first.

    A shortlist has to survive a reload, so it is served from the database rather
    than filtered out of whatever page of city-wide results happens to be loaded.
    Places removed since being saved are simply absent, not a 404 for the list.
    """

    rows = (
        db.query(models.Favorite, models.Restaurant)
        .join(models.Restaurant, models.Restaurant.id == models.Favorite.restaurant_id)
        .filter(models.Favorite.user_id == current_user.id)
        .order_by(models.Favorite.created_at.desc(), models.Favorite.id.desc())
        .all()
    )
    return [restaurant for _, restaurant in rows]


@app.put("/favorites/{restaurant_id}", response_model=schemas.FavoriteOut)
def save_favorite(
    restaurant_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> models.Favorite:
    """Save a place. Idempotent: saving twice leaves one row, not two."""

    _restaurant_or_404(db, restaurant_id)
    existing = (
        db.query(models.Favorite)
        .filter(
            models.Favorite.user_id == current_user.id,
            models.Favorite.restaurant_id == restaurant_id,
        )
        .one_or_none()
    )
    if existing is not None:
        return existing
    favorite = models.Favorite(user_id=current_user.id, restaurant_id=restaurant_id)
    db.add(favorite)
    db.commit()
    db.refresh(favorite)
    return favorite


@app.delete("/favorites/{restaurant_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(
    restaurant_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> Response:
    """Unsave a place. Also idempotent, so a double tap cannot 404."""

    deleted = (
        db.query(models.Favorite)
        .filter(
            models.Favorite.user_id == current_user.id,
            models.Favorite.restaurant_id == restaurant_id,
        )
        .delete(synchronize_session=False)
    )
    if deleted:
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health", response_model=schemas.HealthOut)
def health(db: DbSession) -> schemas.HealthOut:
    try:
        db.execute(text("SELECT 1 FROM restaurants LIMIT 1"))
        bind = db.get_bind()
        if bind.dialect.name == "sqlite":
            if bool(db.execute(text("PRAGMA query_only")).scalar()):
                raise SQLAlchemyError("SQLite connection is read-only")
        elif bind.dialect.name == "postgresql":
            writable = db.execute(
                text(
                    "SELECT has_table_privilege(current_user, 'restaurants', 'INSERT')"
                )
            ).scalar()
            if not writable:
                raise SQLAlchemyError("Database user lacks write privileges")
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return schemas.HealthOut(status="ok", database="ok")


@app.post(
    "/auth/register",
    response_model=schemas.TokenOut,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: schemas.UserRegister,
    request: Request,
    db: DbSession,
) -> schemas.TokenOut:
    # Anonymous and expensive, so it is capped before any work is done.
    ratelimit.enforce(
        request,
        limit=REGISTER_RATE_LIMIT,
        bucket=ratelimit.client_key(request),
        scope="register",
    )
    if db.query(models.User).filter_by(email=payload.email).first() is not None:
        raise HTTPException(status_code=409, detail="That email already has a seat")

    user = models.User(
        name=payload.name,
        email=payload.email,
        password_hash=auth.hash_password(payload.password),
        is_admin=payload.email in auth.ADMIN_EMAILS,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="That email already has a seat"
        ) from exc
    db.refresh(user)
    access, refresh = auth.issue_session(db, user)
    db.commit()
    return schemas.TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=auth.ACCESS_TOKEN_SECONDS,
    )


@app.post("/auth/login", response_model=schemas.TokenOut)
def login(
    payload: schemas.UserLogin,
    request: Request,
    db: DbSession,
) -> schemas.TokenOut:
    # Checked before the password is hashed, so the limit bounds the work rather
    # than merely counting it afterwards.
    ratelimit.enforce(
        request,
        limit=LOGIN_RATE_LIMIT,
        bucket=ratelimit.client_key(request),
        scope="login",
    )
    user = db.query(models.User).filter_by(email=payload.email).first()
    if user is None or not auth.verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access, refresh = auth.issue_session(db, user)
    db.commit()
    return schemas.TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=auth.ACCESS_TOKEN_SECONDS,
    )


@app.post("/auth/google", response_model=schemas.TokenOut)
def login_with_google(
    payload: schemas.GoogleLoginIn,
    request: Request,
    db: DbSession,
) -> schemas.TokenOut:
    """Sign in with a Google ID token from Google Identity Services.

    The browser proves who the reader is to Google; Google proves it to this
    endpoint by signing the token. All this endpoint does is check that
    signature (audience, issuer, expiry — via Google's own verifier) and then
    hand out exactly the session a password login would: same access token,
    same rotating refresh token, same revocation. Nothing downstream knows or
    cares which front door the reader came through.

    Three cases, in order. A known subject signs straight in. An unknown
    subject with a *verified* email either links to the matching account —
    keeping its reviews, saves and follows — or creates a passwordless one.
    An unverified email proves nothing about that address and gets a 401,
    because accepting it would let anyone claim anyone else's account by
    typing their address into a Google signup form.
    """

    ratelimit.enforce(
        request,
        limit=GOOGLE_RATE_LIMIT,
        bucket=ratelimit.client_key(request),
        scope="google",
    )
    if not auth.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured on this server.",
        )
    try:
        claims = auth.verify_google_token(payload.id_token)
    except ValueError:
        # Deliberately one answer for every failure: expired, forged,
        # wrong audience, wrong issuer. Distinguishing them teaches an
        # attacker which forgeries get how far.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="That Google sign-in was not accepted. Try again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    subject = claims.get("sub")
    email = str(claims.get("email", "")).strip().lower()
    if not subject or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="That Google sign-in was not accepted. Try again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not claims.get("email_verified"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="That Google account's email is not verified.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(models.User).filter_by(google_sub=subject).first()
    if user is None:
        user = db.query(models.User).filter_by(email=email).first()
        if user is not None:
            user.google_sub = subject
        else:
            user = models.User(
                name=str(claims.get("name") or email.split("@")[0])[:255],
                email=email,
                password_hash=None,
                google_sub=subject,
                is_admin=email in auth.ADMIN_EMAILS,
            )
            db.add(user)
        try:
            db.commit()
        except IntegrityError:
            # Lost a race: a concurrent sign-in created or linked the same
            # identity first. Re-read rather than fail — the desired state is
            # the state it is in.
            db.rollback()
            user = (
                db.query(models.User).filter_by(google_sub=subject).first()
                or db.query(models.User).filter_by(email=email).first()
            )
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="That Google sign-in was not accepted. Try again.",
                    headers={"WWW-Authenticate": "Bearer"},
                ) from None

    access, refresh = auth.issue_session(db, user)
    db.commit()
    return schemas.TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=auth.ACCESS_TOKEN_SECONDS,
    )


@app.get("/auth/providers", response_model=schemas.AuthProvidersOut)
def auth_providers() -> schemas.AuthProvidersOut:
    """Which front doors exist. Public, because the client needs it before it
    has any credentials — and a client ID is public by design anyway."""

    return schemas.AuthProvidersOut(
        google_enabled=bool(auth.GOOGLE_CLIENT_ID),
        google_client_id=auth.GOOGLE_CLIENT_ID or None,
    )


@app.post("/auth/refresh", response_model=schemas.TokenOut)
def refresh_session(
    payload: schemas.RefreshIn,
    request: Request,
    db: DbSession,
) -> schemas.TokenOut:
    """Exchange a refresh token for a new pair, invalidating the old one.

    Capped like the other anonymous routes: an attacker guessing a refresh token
    should not be able to make this expensive either.
    """

    ratelimit.enforce(
        request,
        limit=REFRESH_RATE_LIMIT,
        bucket=ratelimit.client_key(request),
        scope="refresh",
    )
    result = auth.rotate_session(db, payload.refresh_token)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="That session has expired. Sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # rotate_session has already signed a fresh access token for the resolved user.
    _, access, raw_refresh = result
    return schemas.TokenOut(
        access_token=access,
        refresh_token=raw_refresh,
        expires_in=auth.ACCESS_TOKEN_SECONDS,
    )


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: schemas.RefreshIn, db: DbSession) -> Response:
    """End one session.

    Idempotent, and deliberately unauthenticated: a reader whose access token has
    already expired must still be able to sign out, and reporting whether a token
    was valid would leak that detail for no benefit.
    """

    auth.revoke_session(db, payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/auth/me", response_model=schemas.UserOut)
def get_profile(current_user: CurrentUser) -> models.User:
    return current_user


@app.patch("/auth/me", response_model=schemas.UserOut)
def update_profile(
    payload: schemas.ProfileUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> models.User:
    if payload.reviewer_type is not None:
        current_user.reviewer_type = payload.reviewer_type
    if "cuisine_specialty" in payload.model_fields_set:
        current_user.cuisine_specialty = (
            payload.cuisine_specialty
            if current_user.reviewer_type == models.ReviewerType.cuisine_specialist
            else None
        )
    db.commit()
    db.refresh(current_user)
    return current_user


# One statement covering every counted column. These fields are comma-joined, so
# a place tagged `Biryani, Multi-cuisine` belongs in both counts; splitting in
# Python keeps that to a single pass instead of a query per option.
_TAG_COLUMNS = (
    models.Restaurant.cuisine_tags,
    models.Restaurant.type_tag,
    models.Restaurant.dietary_flags,
    models.Restaurant.good_for,
    models.Restaurant.accessibility_flags,
)


def _count_column(rows, index: int, values: list[str]) -> dict[str, int]:
    """Count places per tag, starting every option at zero.

    Zero is the point: an option with no rows has to appear as zero rather than
    be missing, so the menu can say so instead of quietly dropping it.
    """

    tally = dict.fromkeys(values, 0)
    for row in rows:
        for tag in (row[index] or "").split(","):
            name = tag.strip()
            if name in tally:
                tally[name] += 1
    return tally


def _count_enum(rows, values: list[str]) -> dict[str, int]:
    """Same idea for the venue type, which is a single enum rather than a tag list."""

    tally = dict.fromkeys(values, 0)
    for row in rows:
        name = row[1].value if hasattr(row[1], "value") else str(row[1])
        if name in tally:
            tally[name] += 1
    return tally


@app.get("/filter-options")
def filter_options(db: DbSession) -> dict[str, object]:
    """Canonical values accepted by the restaurant filters, and how many match.

    The UI builds its dropdowns from this so the menu can never offer a value
    the API would reject, and cuisine options always match what the classifier
    can actually store.

    The counts exist because a vocabulary is a promise. Of the 51 values the
    menus used to advertise, 22 could never match anything: `date`, `group`,
    `family`, `work`, `late_night`, `pet_friendly`, `budget`, `live_music` and
    six others have no rows at all. Publishing the number lets the menu show what
    is actually reachable instead of sending a reader to an empty result and
    letting them infer the feature is broken.

    Counts are city-wide and unfiltered by design. Recomputing them per active
    filter would make the number under a reader's finger change as they narrow,
    which is harder to read than a stable figure, and costs a scan per render.
    """

    rows = db.execute(select(*_TAG_COLUMNS)).all()
    type_values = [item.value for item in models.RestaurantType]
    return {
        "cuisine": list(classifier.CANONICAL_CUISINES),
        "type_tag": type_values,
        "dietary": list(schemas.DIETARY_FLAGS),
        "good_for": list(schemas.GOOD_FOR_TAGS),
        "accessibility": list(schemas.ACCESSIBILITY_FLAGS),
        "counts": {
            "cuisine": _count_column(rows, 0, list(classifier.CANONICAL_CUISINES)),
            "type_tag": _count_enum(rows, type_values),
            "dietary": _count_column(rows, 2, list(schemas.DIETARY_FLAGS)),
            "good_for": _count_column(rows, 3, list(schemas.GOOD_FOR_TAGS)),
            "accessibility": _count_column(rows, 4, list(schemas.ACCESSIBILITY_FLAGS)),
        },
        "total_places": db.query(func.count(models.Restaurant.id)).scalar() or 0,
    }


@app.get("/stats")
def stats(db: DbSession) -> dict[str, int]:
    """Real counts for the headline figures in the UI.

    The hero advertises how much of the city is loaded, so the number has to come
    from the data rather than being a claim in a template. Cuisines are counted
    per tag, because a place can carry several and the field is comma-joined.
    """

    places = db.query(func.count(models.Restaurant.id)).scalar() or 0

    cuisine_counts: dict[str, int] = {}
    for (tags,) in db.query(models.Restaurant.cuisine_tags):
        for tag in (tags or "").split(","):
            name = tag.strip()
            if name:
                cuisine_counts[name] = cuisine_counts.get(name, 0) + 1

    cuisine_total = sum(cuisine_counts.values())
    reviews = db.query(func.count(models.Review.id)).scalar() or 0
    return {
        "places": places,
        # A place with three tags counts once, so report the distinct cuisines
        # actually present rather than the inflated tag sum.
        "cuisines": len(cuisine_counts),
        "cuisine_tags": cuisine_total,
        "reviews": reviews,
    }


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_008.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def _bounding_box(lat: float, lon: float, radius_m: float):
    """Cheap pre-filter box around a point, so a radius query stays index-friendly."""

    lat_delta = radius_m / 111_320.0
    cos_lat = max(0.01, math.cos(math.radians(lat)))
    lon_delta = radius_m / (111_320.0 * cos_lat)
    return lat - lat_delta, lon - lon_delta, lat + lat_delta, lon + lon_delta


def _apply_restaurant_filters(
    query,
    *,
    cuisine: str | None,
    type_tag: models.RestaurantType | None,
    dietary: str | None,
    good_for: str | None,
    accessibility: str | None,
    search: str | None,
):
    if cuisine:
        query = query.filter(_tag_membership(models.Restaurant.cuisine_tags, cuisine))
    if type_tag:
        query = query.filter(models.Restaurant.type_tag == type_tag)
    if dietary:
        query = query.filter(_tag_membership(models.Restaurant.dietary_flags, dietary))
    if good_for:
        query = query.filter(_tag_membership(models.Restaurant.good_for, good_for))
    if accessibility:
        query = query.filter(
            _tag_membership(models.Restaurant.accessibility_flags, accessibility)
        )
    if search:
        pattern = f"%{_escape_like(search)}%"
        query = query.filter(
            or_(
                models.Restaurant.name.ilike(pattern, escape="\\"),
                models.Restaurant.address.ilike(pattern, escape="\\"),
            )
        )
    return query


# SQLite caps the number of bound parameters in one statement, and the default
# has historically been as low as 999. Chunking keeps the page re-read safe
# whatever the result size.
_FETCH_CHUNK = 900


class _Ranked(NamedTuple):
    """A candidate, ranked by distance, carrying only what ranking and the map need.

    The map endpoint returns six of these fields for every place in the city, and
    the card endpoint needs a full record for at most 100 of them. Neither needs
    a full ORM object for every candidate, which is what made these endpoints
    slow: materialising 7,728 complete records to return 48 cost 88 ms against
    8.5 ms for this projection.
    """

    id: int
    name: str
    latitude: float
    longitude: float
    cuisine_tags: str | None
    type_tag: models.RestaurantType
    distance_m: float


def _rank_by_proximity(
    query,
    *,
    origin: tuple[float, float],
    radius_m: int | None,
    sort: str,
    limit: int,
    offset: int,
) -> tuple[list[_Ranked], int]:
    """Order and page by real distance, computed in Python.

    SQLite is not guaranteed to ship the trig functions a SQL-side haversine
    needs, so distance is calculated here. A bounding box narrows the candidate
    set first, which keeps the Python work proportional to the radius rather
    than to the whole city.

    Returns lightweight rows plus the total match count; the caller decides
    whether it needs full records for the page it is about to return.
    """

    if radius_m is not None:
        south, west, north, east = _bounding_box(origin[0], origin[1], radius_m)
        query = query.filter(
            models.Restaurant.latitude.between(south, north),
            models.Restaurant.longitude.between(west, east),
        )

    rows = query.with_entities(
        models.Restaurant.id,
        models.Restaurant.name,
        models.Restaurant.latitude,
        models.Restaurant.longitude,
        models.Restaurant.cuisine_tags,
        models.Restaurant.type_tag,
    ).all()

    origin_lat, origin_lon = origin
    scored = [
        _Ranked(
            row_id,
            name,
            latitude,
            longitude,
            cuisine_tags,
            type_tag,
            round(_haversine_m(origin_lat, origin_lon, latitude, longitude), 1),
        )
        for row_id, name, latitude, longitude, cuisine_tags, type_tag in rows
    ]

    if radius_m is not None:
        scored = [row for row in scored if row.distance_m <= radius_m]
    if sort == "distance":
        scored.sort(key=lambda row: (row.distance_m, row.name, row.id))
    else:
        scored.sort(key=lambda row: (row.name, row.id))

    return scored[offset : offset + limit], len(scored)


def _load_page(db: DbSession, page: list[_Ranked]) -> list[models.Restaurant]:
    """Re-read just the ranked page as full records, in the ranked order.

    The card endpoint returns every column, so those rows have to be loaded —
    but only the ones it actually returns, not every candidate that was ranked.
    The bulk fetch comes back in whatever order the database chose, so the page
    order is reapplied from the ranking.
    """

    if not page:
        return []

    distances = {row.id: row.distance_m for row in page}
    records: list[models.Restaurant] = []
    ids = list(distances)
    for start in range(0, len(ids), _FETCH_CHUNK):
        records.extend(
            db.query(models.Restaurant)
            .filter(models.Restaurant.id.in_(ids[start : start + _FETCH_CHUNK]))
            .all()
        )

    by_id = {record.id: record for record in records}
    ordered: list[models.Restaurant] = []
    for row in page:
        record = by_id.get(row.id)
        if record is not None:
            record.distance_m = distances[row.id]
            ordered.append(record)
    return ordered


@app.get("/restaurants", response_model=list[schemas.RestaurantOut])
def list_restaurants(
    db: DbSession,
    response: Response,
    cuisine: str | None = Query(default=None, max_length=100),
    type_tag: models.RestaurantType | None = None,
    dietary: str | None = Query(default=None, max_length=100),
    good_for: str | None = Query(default=None, max_length=100),
    accessibility: str | None = Query(default=None, max_length=100),
    search: str | None = Query(default=None, max_length=200),
    origin_lat: float | None = Query(default=None, ge=-90, le=90),
    origin_lon: float | None = Query(default=None, ge=-180, le=180),
    radius_m: int | None = Query(default=None, ge=1, le=50_000),
    sort: str = Query(default="name", pattern="^(name|distance)$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[models.Restaurant]:
    if (origin_lat is None) != (origin_lon is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="origin_lat and origin_lon must be supplied together",
        )
    if sort == "distance" and origin_lat is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="sort=distance requires origin_lat and origin_lon",
        )
    if radius_m is not None and origin_lat is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="radius_m requires origin_lat and origin_lon",
        )

    query = _apply_restaurant_filters(
        db.query(models.Restaurant),
        cuisine=cuisine,
        type_tag=type_tag,
        dietary=dietary,
        good_for=good_for,
        accessibility=accessibility,
        search=search,
    )

    if origin_lat is not None:
        rows, total = _rank_by_proximity(
            query,
            origin=(origin_lat, origin_lon),
            radius_m=radius_m,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        # Non-breaking: lets the client show "showing 48 of 312" without changing
        # the response shape from a plain list.
        response.headers["X-Total-Count"] = str(total)
        return _load_page(db, rows)

    return (
        query.order_by(models.Restaurant.name, models.Restaurant.id)
        .offset(offset)
        .limit(limit)
        .all()
    )


# Declared before /restaurants/{restaurant_id} so "points" is not parsed as an id.
@app.get("/restaurants/points", response_model=list[schemas.RestaurantPointOut])
def list_restaurant_points(
    db: DbSession,
    cuisine: str | None = Query(default=None, max_length=100),
    type_tag: models.RestaurantType | None = None,
    dietary: str | None = Query(default=None, max_length=100),
    good_for: str | None = Query(default=None, max_length=100),
    accessibility: str | None = Query(default=None, max_length=100),
    search: str | None = Query(default=None, max_length=200),
    south: float | None = Query(default=None, ge=-90, le=90),
    west: float | None = Query(default=None, ge=-180, le=180),
    north: float | None = Query(default=None, ge=-90, le=90),
    east: float | None = Query(default=None, ge=-180, le=180),
    origin_lat: float | None = Query(default=None, ge=-90, le=90),
    origin_lon: float | None = Query(default=None, ge=-180, le=180),
    radius_m: int | None = Query(default=None, ge=1, le=50_000),
    sort: str = Query(default="name", pattern="^(name|distance)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20000, ge=1, le=40000),
) -> list[schemas.RestaurantPointOut]:
    """Lightweight positions for drawing the whole city on the map.

    Accepts the same filters as /restaurants so map and cards can never disagree
    about what a filter means, plus an optional bounding box so a zoomed-in view
    only pays for the places it can actually show.
    """

    if (origin_lat is None) != (origin_lon is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="origin_lat and origin_lon must be supplied together",
        )
    if (sort == "distance" or radius_m is not None) and origin_lat is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="sort=distance and radius_m require origin_lat and origin_lon",
        )

    query = _apply_restaurant_filters(
        db.query(models.Restaurant),
        cuisine=cuisine,
        type_tag=type_tag,
        dietary=dietary,
        good_for=good_for,
        accessibility=accessibility,
        search=search,
    )

    supplied = (south, west, north, east)
    if all(value is not None for value in supplied):
        query = query.filter(
            models.Restaurant.latitude >= south,
            models.Restaurant.latitude <= north,
            models.Restaurant.longitude >= west,
            models.Restaurant.longitude <= east,
        )
    elif any(value is not None for value in supplied):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="south, west, north and east must all be supplied together",
        )

    has_bounds = all(value is not None for value in supplied)

    if has_bounds:
        # Served from the in-memory projection. The map asks for the same filters
        # inside a moving bounding box constantly, and doing that over a database
        # round trip each time was the single largest CPU cost in the API. The
        # result is identical to the SQL path, which `tests/test_place_index.py`
        # asserts directly.
        entries = place_index.select_rows(
            place_index.all_rows(db),
            cuisine=cuisine,
            type_tag=type_tag,
            dietary=dietary,
            good_for=good_for,
            accessibility=accessibility,
            search=search,
        )
        entries = place_index.within_bounds(entries, south, west, north, east)

        ranked = _rank_entries(
            entries,
            origin=(origin_lat, origin_lon) if origin_lat is not None else None,
            radius_m=radius_m,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        return [
            schemas.RestaurantPointOut(
                id=entry.row.id,
                name=entry.row.name,
                latitude=entry.row.latitude,
                longitude=entry.row.longitude,
                cuisine_tags=entry.row.cuisine_tags,
                type_tag=entry.row.type_tag,
                distance_m=distance,
            )
            for entry, distance in ranked
        ]

    if origin_lat is not None:
        # A radius is the tighter constraint and the one tied to where the user
        # actually is, so it wins over a caller-supplied box.
        rows, _ = _rank_by_proximity(
            query,
            origin=(origin_lat, origin_lon),
            radius_m=radius_m,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        # The map needs six fields per place, so the ranked projection is already
        # the whole response. Loading full records here would rebuild 7,728 ORM
        # objects only to discard every column but these.
        return [
            schemas.RestaurantPointOut(
                id=row.id,
                name=row.name,
                latitude=row.latitude,
                longitude=row.longitude,
                cuisine_tags=row.cuisine_tags,
                type_tag=row.type_tag,
                distance_m=row.distance_m,
            )
            for row in rows
        ]

    return query.order_by(models.Restaurant.id).limit(limit).all()


def _rank_entries(
    entries: list[place_index.IndexedRow],
    *,
    origin: tuple[float, float] | None,
    radius_m: int | None,
    sort: str,
    limit: int,
    offset: int,
) -> list[tuple[place_index.IndexedRow, float | None]]:
    """Order and page index rows, applying the same rules as the SQL path.

    Kept deliberately parallel to `_rank_by_proximity` so the two cannot drift:
    both use haversine, both apply the radius after scoring rather than before,
    and both break ties on name then id.
    """

    scored: list[tuple[place_index.IndexedRow, float | None]] = []
    for entry in entries:
        distance: float | None = None
        if origin is not None:
            distance = round(
                _haversine_m(
                    origin[0], origin[1], entry.row.latitude, entry.row.longitude
                ),
                1,
            )
        scored.append((entry, distance))

    if radius_m is not None:
        scored = [
            pair for pair in scored if pair[1] is not None and pair[1] <= radius_m
        ]
    if origin is not None and sort == "distance":
        scored.sort(key=lambda pair: (pair[1], pair[0].row.name, pair[0].row.id))
    else:
        scored.sort(key=lambda pair: (pair[0].row.name, pair[0].row.id))

    return scored[offset : offset + limit]


@app.get("/restaurants/{restaurant_id}", response_model=schemas.RestaurantOut)
def get_restaurant(restaurant_id: int, db: DbSession) -> models.Restaurant:
    return _restaurant_or_404(db, restaurant_id)


@app.get("/restaurants/{restaurant_id}/theme")
def get_restaurant_theme(restaurant_id: int, db: DbSession) -> dict[str, object]:
    restaurant = _restaurant_or_404(db, restaurant_id)
    theme_id = restaurant.theme_id or "multi_cuisine_default"
    return {
        "theme_id": theme_id,
        "tokens": THEME_TOKENS.get(theme_id, THEME_TOKENS["multi_cuisine_default"]),
    }


@app.patch(
    "/restaurants/{restaurant_id}/confirm-menu", response_model=schemas.RestaurantOut
)
def confirm_menu(
    restaurant_id: int,
    db: DbSession,
    _current_user: CurrentUser,
) -> models.Restaurant:
    restaurant = _restaurant_or_404(db, restaurant_id)
    restaurant.menu_last_confirmed = utc_now()
    db.commit()
    db.refresh(restaurant)
    return restaurant


@app.get("/restaurants/{restaurant_id}/dishes", response_model=list[schemas.DishOut])
def list_dishes(restaurant_id: int, db: DbSession) -> list[schemas.DishOut]:
    """A place's menu, with each dish's contributor attached."""

    _restaurant_or_404(db, restaurant_id)
    rows = (
        db.query(models.Dish)
        .filter_by(restaurant_id=restaurant_id)
        .order_by(models.Dish.name, models.Dish.id)
        .all()
    )
    return [_serialize_dish(dish) for dish in rows]


def _merge_tags(current: str | None, incoming: list[str] | None) -> str | None:
    """Union two comma-separated tag strings, preserving order and dropping dupes."""

    if not incoming:
        return current
    existing = [part.strip() for part in (current or "").split(",") if part.strip()]
    merged = list(dict.fromkeys([*existing, *incoming]))
    return ", ".join(merged) or None


UPLOAD_RATE_LIMIT = int(os.getenv("TABIKO_UPLOAD_RATE_LIMIT", "30"))
UPLOAD_RATE_WINDOW_SECONDS = 3600


def _limit_upload(user_id: int, request: Request) -> None:
    """Cap uploads per reader per hour.

    Keyed on the account rather than the address, because uploads cost disk
    rather than CPU and one reader behind one address is the thing worth
    stopping. The limiter's own window is a minute, which is the wrong shape for
    this, so the hourly count is kept separately and the same shared table backs
    it.
    """

    from sqlalchemy import text

    from .database import engine as app_engine

    window = int(time.time() // UPLOAD_RATE_WINDOW_SECONDS) * UPLOAD_RATE_WINDOW_SECONDS
    with app_engine.begin() as connection:
        count = connection.execute(
            text(
                """
                INSERT INTO rate_limits (scope, client_key, window_start, count)
                VALUES ('upload', :key, :window, 1)
                ON CONFLICT (scope, client_key, window_start)
                DO UPDATE SET count = rate_limits.count + 1
                RETURNING rate_limits.count
                """
            ),
            {"key": f"user:{user_id}", "window": window},
        ).scalar_one()
    if count > UPLOAD_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="That is a lot of photos for one hour. Try again shortly.",
            headers={"Retry-After": str(UPLOAD_RATE_WINDOW_SECONDS)},
        )


def _validated_image_url(value: str | None) -> str | None:
    """Accept only a path this service actually issued.

    The client can send any string here, so a URL is checked against what the
    upload route produces rather than trusted. Anything else -- an absolute URL
    to another host, a `data:` URI, a path to something else on this origin --
    is refused. A dish photo pointing at somebody else's server is a tracking
    pixel that every reader of the menu loads without meaning to.
    """

    if value is None or not value.strip():
        return None
    candidate = value.strip()
    if not candidate.startswith("/uploads/"):
        raise HTTPException(
            status_code=422,
            detail="image_url must be a path returned by the upload endpoint.",
        )
    if uploads.load(candidate.removeprefix("/uploads/")) is None:
        raise HTTPException(
            status_code=422, detail="That image was not found. Upload it first."
        )
    return candidate


# ---------- Photo uploads ----------


@app.post("/uploads", response_model=schemas.UploadOut, status_code=201)
async def upload_image(
    request: Request,
    current_user: CurrentUser,
) -> schemas.UploadOut:
    """Accept one image and return the path it is served from.

    Separate from dish and review submission on purpose: the client uploads once,
    gets a path, and sends that path with the dish or the review. That means a
    photo can be attached to either without a second upload, and a rejected
    image fails before the reader has written anything.
    """

    # Rate limited per reader, not per address: uploads are the one endpoint
    # where a signed-in account is a better key than an IP, and the cost is
    # disk.
    _limit_upload(current_user.id, request)

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > uploads.MAX_UPLOAD_BYTES:
            # Stop reading rather than buffering the rest: the cap is there to
            # bound memory, and a request that ignores it would defeat that by
            # arriving whole.
            raise HTTPException(
                status_code=413,
                detail=f"That image is over {uploads.MAX_UPLOAD_BYTES // 1024} KB.",
            )

    try:
        stored = uploads.store(bytes(body))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return schemas.UploadOut(
        url=stored.url, content_type=stored.content_type, size=stored.size
    )


@app.get("/uploads/{name}")
def serve_image(name: str) -> FileResponse:
    """Serve a stored upload.

    Public, because a dish photograph is public information on a public menu.
    The `nosniff` header matters more than usual here: it is what stops a
    browser treating a file whose bytes are not actually the declared type as
    something executable.
    """

    stored = uploads.load(name)
    if stored is None:
        raise HTTPException(status_code=404, detail="No such image")
    return FileResponse(
        stored.path,
        media_type=stored.content_type,
        headers={
            # Content-addressed names never change meaning, so this is safe to
            # cache hard. The `immutable` here is unlike the SPA bundle in one
            # respect: these files are written once and never rewritten.
            "Cache-Control": "public, max-age=604800",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _apply_reader_tags(
    restaurant: models.Restaurant,
    good_for: list[str] | None,
    dietary: list[str] | None,
) -> None:
    """Let a review fill in the occasion and diet tags OSM does not carry.

    `good_for` sits at 3.7% of places and dietary flags at 8.7%, and re-ingesting
    cannot move either, because nobody tags a restaurant as good for a date in
    OpenStreetMap. The people who know are the ones who just ate there, and they
    are already submitting a review.

    Merged, never replaced. A reader confirming "this is fine for families" must
    not erase an `outdoor_seating=yes` the importer recorded, and two readers
    disagreeing should accumulate rather than have the last write win. That also
    means a wrong tag cannot be removed from here, only by someone who notices it
    and edits the place.
    """

    if good_for:
        restaurant.good_for = _merge_tags(restaurant.good_for, good_for)
    if dietary:
        restaurant.dietary_flags = _merge_tags(restaurant.dietary_flags, dietary)


def _serialize_dish(dish: models.Dish) -> schemas.DishOut:
    """Shape a dish, crediting whoever added it.

    The contributor is included by name because the point of recording them is
    that a reader can see a menu was filled in by a person rather than appearing
    from nowhere. A dish with no contributor is reported as such rather than
    being attributed to nobody in particular.
    """

    contributor = dish.added_by
    return schemas.DishOut(
        id=dish.id,
        restaurant_id=dish.restaurant_id,
        name=dish.name,
        tags=dish.tags,
        avg_rating=dish.avg_rating,
        review_count=dish.review_count,
        image_url=dish.image_url,
        added_by=schemas.DishContributor(
            id=contributor.id,
            name=contributor.name,
            is_critic_verified=contributor.is_critic_verified,
        )
        if contributor
        else None,
    )


@app.post(
    "/restaurants/{restaurant_id}/dishes",
    response_model=schemas.DishOut,
    status_code=status.HTTP_201_CREATED,
)
def create_dish(
    restaurant_id: int,
    dish_in: schemas.DishCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> schemas.DishOut:
    _restaurant_or_404(db, restaurant_id)
    if (
        db.query(models.Dish)
        .filter_by(restaurant_id=restaurant_id, name=dish_in.name)
        .first()
        is not None
    ):
        raise HTTPException(status_code=409, detail="That dish is already on the menu")

    dish = models.Dish(
        restaurant_id=restaurant_id,
        added_by_user_id=current_user.id,
        image_url=_validated_image_url(dish_in.image_url),
        # `image_url` is handled above because it has to be validated against a
        # real file first, so it must not also arrive through the dump.
        **dish_in.model_dump(exclude={"image_url"}),
    )
    db.add(dish)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="That dish is already on the menu"
        ) from exc
    db.refresh(dish)
    return _serialize_dish(dish)


def _parse_dish_lines(text: str) -> list[tuple[str, str | None]]:
    """Read a pasted menu.

    One dish per line. The first comma-separated field is the name, and the rest
    are tags, which is how a menu is read off a board: "Masala Dosa, veg, breakfast".
    A line with no comma is a name and nothing else.

    Blank lines are dropped rather than rejected, because a pasted list almost
    always has trailing newlines and rejecting the whole batch for one of those
    would be maddening.
    """

    parsed: list[tuple[str, str | None]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        name = parts[0].strip()
        if not name:
            continue
        tags = ", ".join(part for part in parts[1:] if part) or None
        parsed.append((name, tags))
    return parsed


@app.post(
    "/restaurants/{restaurant_id}/dishes/bulk",
    response_model=schemas.DishBulkResult,
    status_code=status.HTTP_201_CREATED,
)
def create_dishes_bulk(
    restaurant_id: int,
    payload: schemas.DishBulkCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
) -> schemas.DishBulkResult:
    """Add a whole pasted menu in one request.

    This exists because filling in a menu one dish per form submission is the
    reason nobody does it. A real menu is twenty or thirty lines, and twenty or
    thirty round trips is not a thing anyone will sit through.

    Duplicates are reported rather than rejected: a pasted list that overlaps what
    is already there is the normal case, not an error, and refusing the whole
    batch would throw away the new lines along with the old ones.
    """

    ratelimit.enforce(
        request,
        limit=DISH_BULK_RATE_LIMIT,
        bucket=ratelimit.client_key(request),
        scope="dish-bulk",
    )
    _restaurant_or_404(db, restaurant_id)

    candidates = _parse_dish_lines(payload.text)
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No dishes found in that text. One per line, tags after a comma.",
        )
    if len(candidates) > MAX_DISHES_PER_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"That is {len(candidates)} dishes; the limit is "
            f"{MAX_DISHES_PER_REQUEST}. Add the rest in another go.",
        )

    existing = {
        name.casefold()
        for (name,) in db.query(models.Dish.name).filter_by(restaurant_id=restaurant_id)
    }
    already = [name for name, _ in candidates if name.casefold() in existing]

    added: list[models.Dish] = []
    skipped = list(already)
    seen: set[str] = set()
    for name, tags in candidates:
        key = name.casefold()
        # Also catches the same name pasted twice in one go, which the database
        # constraint would otherwise reject and roll the whole batch back.
        if key in existing or key in seen:
            if key in seen and name not in skipped:
                skipped.append(name)
            continue
        seen.add(key)
        dish = models.Dish(
            restaurant_id=restaurant_id,
            name=name,
            tags=tags,
            added_by_user_id=current_user.id,
        )
        db.add(dish)
        added.append(dish)

    if not added:
        db.rollback()
        return schemas.DishBulkResult(added=[], skipped=skipped)

    # A menu just changed, so any freshness claim about it is stale.
    _restaurant_or_404(db, restaurant_id).menu_last_confirmed = None
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One of those dishes was added a moment ago. Refresh and try again.",
        ) from exc

    for dish in added:
        db.refresh(dish)
    return schemas.DishBulkResult(
        added=[_serialize_dish(dish) for dish in added], skipped=skipped
    )


@app.post(
    "/reviews",
    response_model=schemas.ReviewOut,
    status_code=status.HTTP_201_CREATED,
)
def create_review(
    review_in: schemas.ReviewCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> schemas.ReviewOut:
    restaurant = _restaurant_or_404(db, review_in.restaurant_id)
    request_id = (
        str(review_in.client_request_id)
        if review_in.client_request_id is not None
        else None
    )
    if request_id is not None:
        duplicate = (
            db.query(models.Review)
            .filter_by(user_id=current_user.id, client_request_id=request_id)
            .first()
        )
        if duplicate is not None:
            raise HTTPException(
                status_code=409, detail="That review is already on the table"
            )

    dish = None
    if review_in.dish_id is not None:
        dish = (
            db.query(models.Dish)
            .filter_by(id=review_in.dish_id)
            .with_for_update()
            .first()
        )
        if dish is None:
            raise HTTPException(status_code=404, detail="That dish is not on the radar")
        if dish.restaurant_id != restaurant.id:
            raise HTTPException(
                status_code=400,
                detail="Dish does not belong to the selected restaurant",
            )

    verification_tier = trust.resolve_verification_tier(
        restaurant,
        review_in.claimed_verification_tier,
        review_in.user_lat,
        review_in.user_lon,
    )
    review = models.Review(
        user_id=current_user.id,
        restaurant_id=restaurant.id,
        dish_id=review_in.dish_id,
        rating=review_in.rating,
        text=review_in.text,
        client_request_id=request_id,
        verification_tier=verification_tier,
        image_url=_validated_image_url(review_in.image_url),
    )
    db.add(review)
    try:
        db.flush()
        trust.score_review(db, review)
        db.flush()
        trust.update_hygiene_score(db, restaurant)

        if dish is not None and not review.fraud_flag:
            average, review_count = (
                db.query(
                    func.avg(models.Review.rating),
                    func.count(models.Review.id),
                )
                .filter(
                    models.Review.dish_id == dish.id,
                    models.Review.fraud_flag.is_(False),
                )
                .one()
            )
            dish.avg_rating = float(average or 0.0)
            dish.review_count = review_count

        _apply_reader_tags(restaurant, review_in.good_for, review_in.dietary)

        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if request_id is not None:
            duplicate = (
                db.query(models.Review)
                .filter_by(user_id=current_user.id, client_request_id=request_id)
                .first()
            )
            if duplicate is not None:
                raise HTTPException(
                    status_code=409, detail="That review is already on the table"
                ) from exc
        raise HTTPException(
            status_code=400, detail="That review plate did not line up"
        ) from exc
    except OperationalError as exc:
        db.rollback()
        message = str(exc.orig).lower()
        if "locked" in message or "busy" in message:
            raise HTTPException(
                status_code=503,
                detail="Database is busy; retry the request",
                headers={"Retry-After": "1"},
            ) from exc
        raise

    db.refresh(review)
    return _serialize_review(db, review)


@app.patch("/reviews/{review_id}/moderation", response_model=schemas.ReviewOut)
def moderate_review(
    review_id: int,
    moderation_in: schemas.ReviewModerationUpdate,
    db: DbSession,
    _current_user: AdminUser,
    _access: WriteAccess,
) -> schemas.ReviewOut:
    review = db.query(models.Review).filter_by(id=review_id).with_for_update().first()
    if review is None:
        raise HTTPException(status_code=404, detail="That review left the table")

    review.fraud_flag = moderation_in.fraud_flag
    review.fraud_reason = (
        moderation_in.fraud_reason if moderation_in.fraud_flag else None
    )
    db.flush()
    restaurant = _restaurant_or_404(db, review.restaurant_id)
    trust.update_hygiene_score(db, restaurant)
    if review.dish_id is not None:
        dish = (
            db.query(models.Dish).filter_by(id=review.dish_id).with_for_update().first()
        )
        if dish is not None:
            average, review_count = (
                db.query(
                    func.avg(models.Review.rating),
                    func.count(models.Review.id),
                )
                .filter(
                    models.Review.dish_id == review.dish_id,
                    models.Review.fraud_flag.is_(False),
                )
                .one()
            )
            dish.avg_rating = float(average or 0.0)
            dish.review_count = review_count

    db.commit()
    db.refresh(review)
    # Flagging changes which review text is searchable without changing any row
    # count, so the cached craving index cannot notice on its own.
    craving_search.invalidate_index()
    return _serialize_review(db, review)


@app.get("/reviews/restaurant/{restaurant_id}", response_model=list[schemas.ReviewOut])
def list_reviews_for_restaurant(
    restaurant_id: int,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    following_only: bool = Query(default=False),
    current_user: Annotated[
        models.User | None, Depends(auth.get_current_user_optional)
    ] = None,
) -> list[schemas.ReviewOut]:
    """Every review of a place, or only those from people the reader follows.

    `following_only` is a filter on an otherwise public list, not a private one.
    When it is off or absent the endpoint behaves exactly as it did before this
    parameter existed, which is what keeps a signed-out reader working and keeps
    this from turning the public reviews list into something auth-gated.

    When it is on and nobody is signed in, it is a 401 rather than an empty
    list. "You are following nobody" and "you are not logged in" are different
    answers, and returning an empty list for both would leave a reader staring
    at a blank panel with no explanation and no way to tell what went wrong.
    """

    _restaurant_or_404(db, restaurant_id)

    query = db.query(models.Review).filter_by(
        restaurant_id=restaurant_id, fraud_flag=False
    )
    if following_only:
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sign in to see reviews from people you follow.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        followed = _followed_ids(db, current_user.id)
        if not followed:
            return []
        query = query.filter(models.Review.user_id.in_(followed))

    reviews = (
        query.order_by(models.Review.created_at.desc(), models.Review.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_serialize_review(db, review) for review in reviews]


@app.get("/reviews/flagged", response_model=list[schemas.ReviewOut])
def list_flagged_reviews(
    db: DbSession,
    _current_user: AdminUser,
    _access: WriteAccess,
) -> list[schemas.ReviewOut]:
    reviews = (
        db.query(models.Review)
        .filter_by(fraud_flag=True)
        .order_by(models.Review.created_at.desc())
        .all()
    )
    return [_serialize_review(db, review) for review in reviews]


@app.get(
    "/restaurants/{restaurant_id}/stats", response_model=schemas.RestaurantStatsOut
)
def get_restaurant_stats(
    restaurant_id: int, db: DbSession
) -> schemas.RestaurantStatsOut:
    _restaurant_or_404(db, restaurant_id)
    row = (
        db.query(
            func.avg(
                case((models.Review.fraud_flag.is_(False), models.Review.rating))
            ).label("average"),
            func.count(models.Review.id).label("submitted_count"),
            func.coalesce(
                func.sum(case((models.Review.fraud_flag.is_(False), 1), else_=0)),
                0,
            ).label("visible_count"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                models.Review.fraud_flag.is_(False),
                                models.Review.verification_tier
                                != models.VerificationTier.unverified,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("trusted_count"),
            func.coalesce(
                func.sum(case((models.Review.fraud_flag.is_(True), 1), else_=0)),
                0,
            ).label("flagged_count"),
        )
        .filter(models.Review.restaurant_id == restaurant_id)
        .one()
    )
    average = None if row.average is None else round(float(row.average), 2)
    return schemas.RestaurantStatsOut(
        average_rating=average,
        review_count=int(row.visible_count),
        submitted_review_count=int(row.submitted_count),
        trusted_review_count=int(row.trusted_count),
        flagged_review_count=int(row.flagged_count),
    )


@app.get("/search/craving", response_model=list[schemas.CravingSearchResult])
def search_craving(
    q: Annotated[str, Query(min_length=2, max_length=100)],
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=50),
) -> list[schemas.CravingSearchResult]:
    """Rank venues against the text that actually exists.

    Each result reports any query terms the corpus has no text for, so the UI can
    say "nothing here mentions that" instead of presenting a confident ranking
    of places that merely share a common word.
    """

    results = craving_search.search_by_craving(db, q, limit=limit)
    return [
        schemas.CravingSearchResult(
            restaurant=restaurant,
            relevance=score,
            unmatched_terms=unmatched,
        )
        for restaurant, score, unmatched in results
    ]


# --------------------------------------------------------------------------
# Static frontend, registered last on purpose.
# --------------------------------------------------------------------------
#
# In production the built app is served from this same process, so the frontend
# and the API share an origin: no CORS preflight on the hot path, and one thing to
# deploy. Unset in development, where Vite serves the app on its own port.
#
# The order matters more than it looks. FastAPI matches routes in registration
# order, so a catch-all declared near the top of this file would swallow every
# GET endpoint below it and hand the SPA shell to a client asking for JSON. These
# are last, and `tests/test_static_serving.py` asserts an API route still wins.
STATIC_DIR = os.getenv("TABIKO_STATIC_DIR")

if STATIC_DIR and Path(STATIC_DIR).is_dir():
    from fastapi.staticfiles import StaticFiles

    class _ImmutableAssets(StaticFiles):
        """Serve the hashed bundle with a long cache lifetime.

        The filenames contain a content hash, so a cached copy can never be
        stale: a changed file has a changed name. The service worker and the
        manifest are deliberately not mounted here and are never immutable, or a
        deploy would leave readers on the previous bundle.
        """

        def file_response(self, *args, **kwargs):  # type: ignore[override]
            response = super().file_response(*args, **kwargs)
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response

    app.mount(
        "/assets",
        _ImmutableAssets(directory=Path(STATIC_DIR) / "assets"),
        name="assets",
    )

    @app.middleware("http")
    async def strip_api_prefix(request: Request, call_next):
        """Serve the API under `/api` so it matches the built frontend.

        The client hard-codes `/api` as its base URL, which in development is the
        Vite dev proxy. Without this the production build asked for
        `/api/restaurants`, found only the SPA catch-all, and rendered the error
        state on a page that otherwise worked. One prefix in both environments
        means the proxy and the deployed server cannot disagree.
        """

        if request.url.path.startswith("/api/"):
            request.scope["path"] = request.scope["path"][len("/api") :]
        return await call_next(request)

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str) -> FileResponse:
        """Serve a built file if it exists, otherwise the SPA shell.

        The client owns its own routing, including the `#restaurant-123` deep
        links, so any unknown path has to return index.html rather than a 404.
        """

        candidate = (Path(STATIC_DIR) / full_path).resolve()
        static_root = Path(STATIC_DIR).resolve()
        # Refuse to serve anything outside the build directory, even if a path
        # like `../backend/.env` reaches here.
        if full_path and candidate.is_file() and static_root in candidate.parents:
            return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
        return FileResponse(
            static_root / "index.html",
            headers={"Cache-Control": "no-cache"},
        )
