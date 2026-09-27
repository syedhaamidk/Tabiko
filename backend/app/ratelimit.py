"""A rate limiter whose counters survive more than one worker process.

Scope, restated because it is the thing that changes here:

- **The counters are in the database.** Previously they were per-process, so
  `--workers 4` quietly quadrupled every limit. The counter on `/auth/login`
  matters most, because bcrypt makes a login expensive enough to be worth
  attacking, and it was also the easiest one to multiply. The cost is a single
  indexed row write per limited request, which is small next to the bcrypt hash
  it is protecting and invisible in WAL mode.
- **Redis is deliberately not used.** This is a single-box deployment on SQLite
  with one file on a volume. Adding a cache to fix a counter would have been a
  much larger change than the problem, and it would have made the app fail to
  start for anyone who did not run it.
- **The key is the client address.** Behind a proxy that is the proxy's address
  unless `TABIKO_TRUST_PROXY` is set, in which case `X-Forwarded-For` is trusted.
  An attacker who can set that header can rotate identities, so trusting it is
  only correct when something in front of the app is guaranteed to overwrite it.
- **Failures and successes both count.** Only counting failures would let an
  attacker burn one password per window; counting both caps request volume,
  which is the actual goal.
- **Multiple boxes still do not share.** Two containers with two SQLite files
  will each enforce the full limit. That is a documented limit of a single-file
  deployment, not something this table can fix -- sharing across hosts needs a
  store both can reach.
"""

from __future__ import annotations

import os
import threading
import time

from fastapi import HTTPException, Request, status
from sqlalchemy import text

_WINDOW_SECONDS = 60
# Windows older than this are swept. Kept short: the only reason to retain a
# window is so that a retry just after a boundary does not get a fresh
# allowance, and one extra window is plenty for that.
_RETENTION_WINDOWS = 2

# A local mutex around the sweep only. The counter itself is atomic in SQL, so
# this is not what makes the limit correct across processes -- it just stops
# several threads in one process all deciding to sweep at once.
_sweep_lock = threading.Lock()
_last_sweep = 0.0
_SWEEP_INTERVAL_SECONDS = 30.0

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


def _window_start(now: float) -> int:
    return int(now // _WINDOW_SECONDS) * _WINDOW_SECONDS


def _engine():
    """The application engine, resolved at call time so tests can redirect it.

    The limiter deliberately does not use the request's session. The endpoint
    being limited may be inside a transaction that later rolls back, and reading
    the counter through that session would let a caller reset their allowance
    simply by provoking an error.
    """

    from .database import engine

    return engine


def _hit(scope: str, key: str, now: float) -> int:
    """Record one request and return the count in the current window, atomically.

    One statement. A read-then-write pair would let two workers both read 9 and
    both store 10 for what was really the eleventh request, which is the exact
    bug this rewrite exists to remove. `RETURNING` gives back the value the
    statement actually wrote rather than one this process believes it wrote.
    """

    window = _window_start(now)
    # `begin()`, not `connect()`: SQLAlchemy rolls an open transaction back when
    # a bare connection closes, so an uncommitted counter would discard every
    # hit and the limiter would never fire at all. That is not theoretical --
    # it is exactly what the first version of this function did.
    with _engine().begin() as connection:
        count = connection.execute(
            text(
                """
                INSERT INTO rate_limits (scope, client_key, window_start, count)
                VALUES (:scope, :key, :window, 1)
                ON CONFLICT (scope, client_key, window_start)
                DO UPDATE SET count = count + 1
                RETURNING count
                """
            ),
            {"scope": scope, "key": key, "window": window},
        ).scalar_one()
    return int(count)


def _sweep(now: float) -> None:
    """Drop windows old enough that nobody is still counting against them.

    Without this the table grows one row per client per minute forever, which is
    the same unbounded-growth problem the in-memory version solved by evicting
    idle keys.
    """

    global _last_sweep
    with _sweep_lock:
        if now - _last_sweep < _SWEEP_INTERVAL_SECONDS:
            return
        _last_sweep = now
        cutoff = _window_start(now) - _RETENTION_WINDOWS * _WINDOW_SECONDS
        try:
            with _engine().begin() as connection:
                connection.execute(
                    text("DELETE FROM rate_limits WHERE window_start < :cutoff"),
                    {"cutoff": cutoff},
                )
        except Exception:  # noqa: BLE001, S110 - cleanup must never fail a request
            # A failed sweep must never take down the request being limited.
            # The table being slightly too large is survivable; a 500 on login
            # because a cleanup statement raced a migration is not. Swallowed
            # deliberately and logged nowhere: a limiter that logs on every
            # failed cleanup is a limiter that fills a log during an outage.
            pass


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
    now = time.time()
    count = _hit(scope, bucket, now)
    if count > limit:
        _sweep(now)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Give it a minute and try again.",
            headers={"Retry-After": str(_WINDOW_SECONDS)},
        )
    _sweep(now)


def reset() -> None:
    """Clear the counters. Tests use this so runs cannot affect each other."""

    with _engine().begin() as connection:
        connection.execute(text("DELETE FROM rate_limits"))
    global _last_sweep
    with _sweep_lock:
        _last_sweep = 0.0
