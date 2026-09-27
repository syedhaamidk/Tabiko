"""A small fixed-window rate limiter for the unauthenticated endpoints.

`/auth/login` and `/auth/register` are the only routes an anonymous caller can
hammer, and both are deliberately expensive: `bcrypt` costs around a tenth of a
second per verification, so an unthrottled endpoint is a free denial-of-service
against the worker pool as well as an open door to password guessing.

Scope, stated plainly because it matters for how this is used:

- **The counters live in this process's memory.** With `--workers 4` there are
  four independent sets of counters, so the effective limit is roughly four times
  what is configured. That is acceptable for one box and wrong for a fleet, which
  needs a shared store such as Redis. Setting the limit to a quarter of the
  intended per-client budget is the mitigation.
- **The key is the client address.** Behind a proxy that is the proxy's address
  unless `TABIKO_TRUST_PROXY` is set, in which case `X-Forwarded-For` is trusted.
  An attacker who can set that header can rotate identities, so trusting it is
  only correct when something in front of the app is guaranteed to overwrite it.
- **Failures and successes both count.** Only counting failures would let an
  attacker burn one password per window; counting both caps request volume, which
  is the actual goal.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

# How many windows of history to keep per key before forgetting the oldest.
_MAX_WINDOWS = 8
_WINDOW_SECONDS = 60.0

# A key that has not been seen for this long is dropped entirely, so an address
# sweep cannot grow the table without bound.
_KEY_TTL_SECONDS = _WINDOW_SECONDS * _MAX_WINDOWS

# Ceiling on distinct tracked keys before the idle sweep runs.
_MAX_KEYS = 10_000

_counters: dict[str, list[float]] = defaultdict(list)
_lock = threading.Lock()

TRUST_PROXY = os.getenv("TABIKO_TRUST_PROXY", "").strip().lower() in {
    "1",
    "true",
    "yes",
}


def client_key(request: Request) -> str:
    if TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            # The left-most entry is the original client.
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _hit(key: str, limit: int, now: float) -> int:
    """Record a request and return the count within the current window.

    Memory is bounded by the age cutoff alone. An earlier version also capped the
    list length, which was a bug: with a cap below the limit the count could never
    exceed the cap, so the limiter never fired at all.
    """

    with _lock:
        window = _counters[key]
        cutoff = now - _WINDOW_SECONDS
        window[:] = [stamp for stamp in window if stamp > cutoff]
        window.append(now)
        count = sum(1 for stamp in window if stamp > cutoff)
        # An idle key holds one timestamp forever otherwise, so evict anything
        # untouched for a few windows.
        if len(_counters) > _MAX_KEYS:
            for stale in [
                name
                for name, stamps in _counters.items()
                if name != key and stamps and stamps[-1] < now - _KEY_TTL_SECONDS
            ]:
                del _counters[stale]
        return count


def enforce(
    request: Request,
    *,
    limit: int,
    bucket: str,
    scope: str,
) -> None:
    """Raise 429 when the caller is over `limit` requests per window.

    `scope` separates the buckets so that, for example, a caller cannot spend the
    login allowance on registration.
    """

    if limit <= 0:
        return
    count = _hit(f"{scope}:{bucket}", limit, time.monotonic())
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Give it a minute and try again.",
            headers={"Retry-After": str(int(_WINDOW_SECONDS))},
        )


def reset() -> None:
    """Clear the counters. Tests use this so runs cannot affect each other."""

    with _lock:
        _counters.clear()
