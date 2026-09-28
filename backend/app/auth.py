"""Password authentication, and revocable tokens for the API.

Two token types, because one long-lived token cannot be taken back:

- An **access token** is a short-lived JWT (30 minutes by default). It is
  stateless, so verifying a request costs no database round trip, and it is
  accepted in a `Bearer` header.
- A **refresh token** is a long-lived opaque secret (30 days) whose SHA-256 is
  stored, never the token itself. It is the only thing that can mint a new access
  token, and revoking it ends the session immediately.

Before this, one token lived for seven days with no way to revoke it: a leaked
token stayed valid until it expired, and signing out only threw away the copy the
browser held. Anyone holding the token kept working. Rotation makes that
recoverable — each refresh issues a new token and burns the old one, so a stolen
refresh token works at most once before the legitimate client's next refresh
invalidates it.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import models
from .database import get_db

ALGORITHM = "HS256"

# Kept only so local development works with no setup. It is a public constant:
# anyone holding this value can sign a token for any user id, including an admin.
# It must never be reachable in a deployment.
INSECURE_DEV_SECRET = "dev-only-secret-change-me-before-production-0000000000000000"

# Set TABIKO_ENV=development to opt into the fallback above. Anything else, and
# anything unset, requires a real secret — a silent fallback is how a staging
# deploy ends up signing production tokens with a value from a public repository.
ENVIRONMENT = os.getenv("TABIKO_ENV", "production").strip().lower()
ALLOW_INSECURE_DEV_SECRET = ENVIRONMENT in {"development", "dev", "test", "local"}


def _load_secret() -> str:
    secret = os.getenv("TABIKO_JWT_SECRET") or os.getenv("JWT_SECRET_KEY") or ""
    secret = secret.strip()

    if secret and secret != INSECURE_DEV_SECRET:
        if len(secret) < 32:
            raise RuntimeError(
                "TABIKO_JWT_SECRET must be at least 32 characters. "
                f"Got {len(secret)}. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return secret

    if not secret:
        secret = INSECURE_DEV_SECRET

    if ALLOW_INSECURE_DEV_SECRET:
        return secret

    raise RuntimeError(
        "TABIKO_JWT_SECRET is not set, so every token would be signed with a "
        "constant that is published in this repository. Anyone could then mint a "
        "token for any user, including an admin. Set a real secret, or set "
        "TABIKO_ENV=development to run locally with the known-dev value."
    )


SECRET_KEY = _load_secret()
USING_DEV_SECRET = SECRET_KEY == INSECURE_DEV_SECRET


def _positive_int(name: str, default: str) -> int:
    raw = os.getenv(name, default).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"{name} must be a whole number of seconds or minutes"
        ) from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


# An access token is deliberately short-lived. The client refreshes transparently,
# so the only cost is one extra request per half hour, and a captured token stops
# working almost immediately.
ACCESS_TOKEN_SECONDS = _positive_int("TABIKO_ACCESS_TOKEN_SECONDS", "1800")
REFRESH_TOKEN_DAYS = _positive_int("TABIKO_REFRESH_TOKEN_DAYS", "30")
# Grace period for a refresh token rotated a moment ago, so two concurrent
# requests cannot invalidate each other.
REFRESH_ROTATION_GRACE_SECONDS = _positive_int("TABIKO_REFRESH_GRACE_SECONDS", "30")

ADMIN_EMAILS = {
    email.strip().lower()
    for email in os.getenv("TABIKO_ADMIN_EMAILS", "").split(",")
    if email.strip()
}

bearer_scheme = HTTPBearer(auto_error=False)

# The OAuth client ID Google issued for this deployment's web application.
# Empty means Google sign-in is not configured, and the endpoint refuses
# rather than verifying against nothing. A client ID is public by design —
# it ships in the frontend bundle — so this is configuration, not a secret.
GOOGLE_CLIENT_ID = os.getenv("TABIKO_GOOGLE_CLIENT_ID", "").strip()


def verify_google_token(id_token: str) -> dict:
    """Verify a Google ID token and return its claims.

    Signature, audience, issuer and expiry are all checked by Google's own
    verifier against Google's current certificates — reimplementing any of
    that here would be a way to get it subtly wrong. The certificates are
    fetched over HTTPS on each call rather than cached: logins are capped at
    a handful per minute per client, so one extra request is invisible, and a
    cache is a place for a rotated-out key to linger.

    Raises ValueError for anything that is not a valid token for this project,
    which the endpoint reports as a 401 without distinguishing why. Saying
    *which* check failed would teach an attacker which forgeries get how far.
    """

    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    if not GOOGLE_CLIENT_ID:
        raise ValueError("Google sign-in is not configured")
    return google_id_token.verify_oauth2_token(
        id_token, google_requests.Request(), GOOGLE_CLIENT_ID
    )


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, seconds: int | None = None) -> str:
    """A short-lived bearer token. Stateless, so it cannot be revoked.

    That is the trade: cheap to verify, and bounded by its own short life. Anything
    that must be revocable is a session, held by a refresh token.
    """

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(seconds=seconds or ACCESS_TOKEN_SECONDS),
        "type": "access",
        "jti": secrets.token_urlsafe(8),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ---------- refresh tokens ----------


def hash_refresh_token(token: str) -> str:
    """SHA-256 of the token, which is safe to store.

    The token is 32 bytes of `secrets.token_urlsafe`, so there is nothing to brute
    force: an attacker who reads the database still cannot recover it, and a
    digest is constant-time comparable. `hmac.compare_digest` is used wherever a
    stored hash is checked.
    """

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_refresh_token(raw)


def issue_session(db: Session, user: models.User) -> tuple[str, str]:
    """Mint an access token and a fresh refresh token, storing only its digest."""

    raw_refresh, digest = _new_refresh_token()
    db.add(
        models.RefreshToken(
            user_id=user.id,
            token_hash=digest,
            expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS),
        )
    )
    return create_access_token(user.id), raw_refresh


def _find_refresh(db: Session, digest: str) -> models.RefreshToken | None:
    """Look a refresh token up without leaking its existence through timing.

    `hmac.compare_digest` is not what makes the lookup constant-time — SQL is —
    but it is the right primitive at the boundary and costs nothing.
    """

    for row in db.query(models.RefreshToken).filter_by(token_hash=digest).all():
        if hmac.compare_digest(row.token_hash, digest):
            return row
    return None


def rotate_session(
    db: Session, raw_refresh: str
) -> tuple[models.User, str, str] | None:
    """Exchange a refresh token for a new pair, invalidating the old one.

    Returns None when the token is unknown, already used, revoked or expired. The
    short grace period after rotation means a client that fires two refreshes at
    once is not logged out by its own race.
    """

    if not raw_refresh:
        return None
    row = _find_refresh(db, hash_refresh_token(raw_refresh))
    if row is None:
        return None

    now = datetime.now(timezone.utc)
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        # SQLite hands back naive datetimes even though they were written as UTC.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now or row.revoked_at is not None:
        return None

    if row.rotated_at is not None:
        rotated_at = row.rotated_at
        if rotated_at.tzinfo is None:
            rotated_at = rotated_at.replace(tzinfo=timezone.utc)
        if (now - rotated_at).total_seconds() > REFRESH_ROTATION_GRACE_SECONDS:
            # Already exchanged, and outside the grace period. A replay of a
            # stolen token is treated as a compromise and ends every session.
            revoke_all_sessions(db, row.user_id)
            return None
        # Inside the grace period this is the client's own race: the request that
        # won has already issued the next pair, so this one simply declines and
        # the client retries with the token it is about to receive.
        return None

    raw_next, digest_next = _new_refresh_token()
    # Only `rotated_at`. Marking it revoked as well would make a later replay look
    # like an ordinary revoked token, so the theft signal would never be seen.
    row.rotated_at = now
    row.replaced_by_token_hash = digest_next
    db.add(
        models.RefreshToken(
            user_id=row.user_id,
            token_hash=digest_next,
            expires_at=now + timedelta(days=REFRESH_TOKEN_DAYS),
        )
    )
    db.commit()
    user = db.get(models.User, row.user_id)
    if user is None:
        return None
    return user, create_access_token(user.id), raw_next


def revoke_session(db: Session, raw_refresh: str) -> bool:
    """Sign one device out."""

    if not raw_refresh:
        return False
    row = _find_refresh(db, hash_refresh_token(raw_refresh))
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return True


def revoke_all_sessions(db: Session, user_id: int) -> int:
    """Sign every device out. Used on password change and on a replayed token."""

    now = datetime.now(timezone.utc)
    count = (
        db.query(models.RefreshToken)
        .filter(
            models.RefreshToken.user_id == user_id,
            models.RefreshToken.revoked_at.is_(None),
        )
        .update({models.RefreshToken.revoked_at: now}, synchronize_session=False)
    )
    db.commit()
    return count


def purge_expired_sessions(db: Session) -> int:
    """Drop rows that can no longer be used.

    Expiry is checked on every use anyway, so this only keeps the table small.
    A scheduled call is enough; there is no background worker in this service.
    """

    now = datetime.now(timezone.utc)
    expired = (
        db.query(models.RefreshToken.id)
        .filter(models.RefreshToken.expires_at < now)
        .all()
    )
    if not expired:
        return 0
    db.query(models.RefreshToken).filter(
        models.RefreshToken.id.in_([row[0] for row in expired])
    ).delete(synchronize_session=False)
    db.commit()
    return len(expired)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> models.User:
    if credentials is None:
        raise _unauthorized()
    try:
        payload = jwt.decode(
            credentials.credentials,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
        if payload.get("type") != "access":
            raise _unauthorized()
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise _unauthorized() from exc

    user = db.get(models.User, user_id)
    if user is None:
        raise _unauthorized()
    return user


def get_current_user_optional(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> models.User | None:
    """The same as `get_current_user`, except anonymous is allowed.

    For endpoints that are public but gain something when signed in, where
    requiring a token would break the page for readers who are only browsing.

    A token that is *present but bad* is still a 401 rather than a silent
    downgrade to anonymous. A client sending a token has said it believes it is
    signed in, and quietly treating that as "logged out" turns an expired
    session into a page that looks signed out instead of an error the client can
    act on by refreshing. The frontend relies on that distinction to know when to
    refresh a token.
    """

    if credentials is None:
        return None
    return get_current_user(credentials, db)


def require_admin(
    current_user: Annotated[models.User, Depends(get_current_user)],
) -> models.User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return current_user
