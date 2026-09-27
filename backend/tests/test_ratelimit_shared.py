"""The rate limiter, and specifically that its limit is not multiplied by workers.

The bug this file exists for: counters lived in each worker process's memory, so
`--workers 4` meant a caller could make four times the configured number of
attempts against `/auth/login` and `/auth/register` -- the two endpoints that
exist because they are expensive to serve, bcrypt being the reason.

Two things about how this is set up are worth stating, because both are traps:

**These tests need a file-backed database.** The rest of the suite runs on an
in-memory SQLite database behind a dependency override, which a second
interpreter cannot open at all. Pointing the parent at its `:memory:` engine
would also mean the counters went to the real `tabiko.db`, so every test run
quietly wrote rate-limit rows into the development database.

**The second process is a real subprocess, not a thread.** Two threads in one
interpreter share a module, so they would never have caught a per-process bug.
Only a second interpreter has its own copy of anything the old limiter kept in
memory.
"""

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def shared_db(tmp_path, monkeypatch):
    """A file-backed database both this process and a subprocess can open.

    Also redirects `app.database.engine`, because the limiter reads its
    connection from there rather than opening its own. Without this the counters
    would land in the development database.
    """

    path = tmp_path / "ratelimit.db"
    url = f"sqlite:///{path.as_posix()}"
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    from app import database as database_module
    from app.models import Base

    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database_module, "engine", engine)
    yield engine, url
    engine.dispose()


@pytest.fixture(autouse=True)
def clear_limiters(shared_db):
    from app import ratelimit

    ratelimit.reset()
    yield
    ratelimit.reset()


class FakeRequest:
    """Just enough of a Request for `client_key` and `enforce`."""

    def __init__(self, host="203.0.113.9"):
        self.client = type("Client", (), {"host": host})()
        self.headers = {}


def _drive(count, host, limit=5, scope="login"):
    """Make `count` attempts through the real limiter, as one process."""

    from app import ratelimit

    statuses = []
    for _ in range(count):
        try:
            ratelimit.enforce(FakeRequest(host), limit=limit, bucket=host, scope=scope)
            statuses.append(200)
        except HTTPException as exc:
            statuses.append(exc.status_code)
    return statuses


# ---------- single-process behaviour ----------


def test_the_limit_is_enforced(shared_db):
    assert _drive(5, "198.51.100.1").count(200) == 5
    assert _drive(7, "198.51.100.2", limit=5).count(429) == 2


def test_different_clients_have_separate_allowances(shared_db):
    _drive(5, "198.51.100.10")
    assert _drive(3, "198.51.100.11").count(200) == 3


def test_scopes_do_not_share_a_bucket(shared_db):
    """A caller cannot spend the login allowance on registration."""

    from app import ratelimit

    request = FakeRequest("198.51.100.20")
    for _ in range(3):
        ratelimit.enforce(request, limit=3, bucket="k", scope="login")
    for _ in range(3):
        ratelimit.enforce(request, limit=3, bucket="k", scope="register")


def test_a_zero_limit_disables_the_check(shared_db):
    assert _drive(50, "198.51.100.30", limit=0).count(200) == 50


def test_the_window_rolls_over(shared_db):
    """A retry just after a boundary gets a fresh allowance, not a permanent 429."""

    from app import ratelimit

    request = FakeRequest("198.51.100.40")
    for _ in range(2):
        ratelimit.enforce(request, limit=2, bucket="k", scope="login")
    with pytest.raises(HTTPException):
        ratelimit.enforce(request, limit=2, bucket="k", scope="login")

    original = ratelimit._window_start
    try:
        ratelimit._window_start = lambda now: original(now) + 60
        ratelimit.enforce(request, limit=2, bucket="k", scope="login")
    finally:
        ratelimit._window_start = original


# ---------- the actual point: one limit across processes ----------

WORKER_SCRIPT = textwrap.dedent(
    """
    import os, sys
    sys.path.insert(0, {backend!r})
    os.environ["TABIKO_ENV"] = "development"
    os.environ["TABIKO_JWT_SECRET"] = "x" * 48
    os.environ["TABIKO_DATABASE_URL"] = {url!r}
    from app import ratelimit
    from app.models import Base
    from app.database import engine

    # A subprocess does not inherit the parent's schema, so make sure the table
    # is there even if this is the only thing that ever ran.
    Base.metadata.create_all(bind=engine)

    class Request:
        def __init__(self):
            self.client = type("C", (), {{"host": {host!r}}})()
            self.headers = {{}}

    allowed = 0
    for _ in range({attempts}):
        try:
            ratelimit.enforce(Request(), limit={limit}, bucket={host!r}, scope={scope!r})
            allowed += 1
        except Exception:
            pass
    print(allowed)
    """
)


def _run_worker(url, host, attempts, limit, scope):
    """Run one throwaway interpreter pointed at the same database file."""

    script = WORKER_SCRIPT.format(
        backend=str(BACKEND),
        url=url,
        host=host,
        attempts=attempts,
        limit=limit,
        scope=scope,
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env={k: v for k, v in os.environ.items() if k != "TABIKO_DATABASE_URL"},
    )
    if result.returncode != 0:
        raise AssertionError(f"worker failed: {result.stderr[-800:]}")
    return int(result.stdout.strip().splitlines()[-1])


def test_two_processes_share_one_allowance(shared_db):
    """The headline requirement.

    Four requests here and four from a separate interpreter must add up to five
    allowed, not eight. Under the old per-process limiter the second process
    started from zero and let all four through.
    """

    _, url = shared_db
    host, limit = "198.51.100.77", 5

    here = _drive(4, host, limit=limit)
    there = _run_worker(url, host, 4, limit, "login")

    total = here.count(200) + there
    assert total == limit, (
        f"expected {limit} allowed across two processes, got {total} "
        f"(this process {here.count(200)}, other process {there})"
    )


def test_a_second_process_is_blocked_once_the_first_exhausts_the_limit(shared_db):
    """The other direction: the parent fills the window, the child gets nothing."""

    _, url = shared_db
    host, limit = "198.51.100.78", 3

    assert _drive(3, host, limit=limit).count(200) == limit
    assert _run_worker(url, host, 3, limit, "login") == 0, (
        "a fresh process must not get a fresh allowance"
    )


def test_the_counter_lives_in_the_database_not_in_memory(shared_db):
    """A direct check, so a regression cannot hide behind the other tests."""

    engine, _ = shared_db
    _drive(3, "198.51.100.79", limit=5)

    with engine.connect() as connection:
        rows = connection.execute(
            text("select scope, client_key, count from rate_limits")
        ).all()

    matching = [row for row in rows if row[1] == "198.51.100.79"]
    assert matching, "the counter was not written to the table"
    assert matching[0][2] == 3


def test_the_sweep_removes_expired_windows(shared_db):
    """Otherwise the table grows one row per client per minute, forever."""

    from app import ratelimit

    engine, url = shared_db
    host = "198.51.100.80"
    _drive(2, host, limit=5)
    _run_worker(url, host, 1, 5, "login")

    stale = int(time.time()) - 10 * 60
    with engine.begin() as connection:
        connection.execute(
            text("update rate_limits set window_start = :stale"), {"stale": stale}
        )

    ratelimit._last_sweep = 0.0
    ratelimit._sweep(time.time())

    with engine.connect() as connection:
        remaining = connection.execute(
            text("select count(*) from rate_limits where client_key = :host"),
            {"host": host},
        ).scalar_one()
    assert remaining == 0, f"{remaining} expired windows survived the sweep"
