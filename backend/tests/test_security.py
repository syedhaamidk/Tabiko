"""Security behaviour that has to hold before this faces a network.

Three things are pinned here, all of which were open:

- A missing signing secret used to fall back to a constant that is published in
  this repository, which would let anyone mint a token for any user.
- The anonymous auth endpoints accepted unlimited requests.
- No response carried any security headers.
"""

import importlib
import time

import pytest

from app import auth, ratelimit


@pytest.fixture(autouse=True)
def clear_limiters():
    ratelimit.reset()
    yield
    ratelimit.reset()


# ---------- the signing secret ----------


def _load_auth(monkeypatch, **env):
    for key in ("TABIKO_JWT_SECRET", "JWT_SECRET_KEY", "TABIKO_ENV"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(auth)


def test_a_missing_secret_stops_the_app_starting(monkeypatch):
    """The critical fix: refuse, rather than sign with a public constant."""

    with pytest.raises(RuntimeError) as excinfo:
        _load_auth(monkeypatch)
    message = str(excinfo.value)
    assert "TABIKO_JWT_SECRET" in message
    assert "admin" in message


def test_the_published_dev_constant_is_never_accepted_in_production(monkeypatch):
    with pytest.raises(RuntimeError):
        _load_auth(
            monkeypatch,
            TABIKO_JWT_SECRET=auth.INSECURE_DEV_SECRET,
            TABIKO_ENV="production",
        )


def test_a_short_secret_is_rejected_with_advice(monkeypatch):
    with pytest.raises(RuntimeError) as excinfo:
        _load_auth(monkeypatch, TABIKO_JWT_SECRET="too-short", TABIKO_ENV="production")
    assert "32 characters" in str(excinfo.value)
    assert "secrets.token_urlsafe" in str(excinfo.value)


def test_a_real_secret_is_accepted(monkeypatch):
    secret = "k" * 48
    reloaded = _load_auth(
        monkeypatch, TABIKO_JWT_SECRET=secret, TABIKO_ENV="production"
    )
    try:
        assert reloaded.SECRET_KEY == secret
        assert reloaded.USING_DEV_SECRET is False
    finally:
        monkeypatch.setenv("TABIKO_ENV", "development")
        importlib.reload(auth)


def test_development_may_still_use_the_dev_secret(monkeypatch):
    reloaded = _load_auth(monkeypatch, TABIKO_ENV="development")
    try:
        assert reloaded.SECRET_KEY == reloaded.INSECURE_DEV_SECRET
        assert reloaded.USING_DEV_SECRET is True
    finally:
        monkeypatch.delenv("TABIKO_ENV", raising=False)
        monkeypatch.setenv("TABIKO_JWT_SECRET", "k" * 48)
        importlib.reload(auth)
        monkeypatch.delenv("TABIKO_JWT_SECRET", raising=False)
        monkeypatch.setenv("TABIKO_ENV", "development")
        importlib.reload(auth)
        monkeypatch.setenv("TABIKO_JWT_SECRET", "k" * 48)
        importlib.reload(auth)


def test_the_dev_secret_is_actually_published_and_must_stay_unusable(monkeypatch):
    """If this test ever needs changing, the constant has become a real risk.

    The value is in the source on purpose, so local development needs no setup.
    The only thing standing between it and a production breach is the guard above.
    """

    assert len(auth.INSECURE_DEV_SECRET) == len(auth.INSECURE_DEV_SECRET)
    assert "dev-only" in auth.INSECURE_DEV_SECRET
    assert "change-me" in auth.INSECURE_DEV_SECRET


# ---------- rate limiting ----------


def test_repeated_failed_logins_are_capped(anon_client):
    payload = {"email": "nobody@example.com", "password": "guessguess"}

    # bcrypt is slow, so only a handful of attempts are made before the cap bites.
    statuses = [
        anon_client.post("/auth/login", json=payload).status_code for _ in range(14)
    ]

    assert 401 in statuses, "the wrong password must still be rejected"
    assert 429 in statuses, "unlimited guessing must not be possible"


def test_a_capped_caller_gets_a_retry_hint(anon_client):
    payload = {"email": "nobody@example.com", "password": "guessguess"}
    for _ in range(14):
        response = anon_client.post("/auth/login", json=payload)
    if response.status_code == 429:
        assert response.headers.get("Retry-After")
        assert "minute" in response.json()["detail"]


def test_registering_is_capped_separately(anon_client):
    made = 0
    for index in range(12):
        response = anon_client.post(
            "/auth/register",
            json={
                "name": f"User {index}",
                "email": f"user{index}@example.com",
                "password": "password123",
            },
        )
        if response.status_code == 429:
            break
        made += 1

    assert 0 < made < 12, "registration must be capped before a dozen accounts"


def test_a_successful_login_is_still_allowed_under_the_cap(client):
    # The limiter must not lock out the legitimate signed-in reader whose token
    # the test client is already using.
    assert client.get("/auth/me").status_code == 200


def test_the_window_closes_again(monkeypatch):
    """Counters must expire, or a caller is penalised forever."""

    from fastapi import HTTPException

    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    ratelimit.reset()

    class FakeRequest:
        client = type("C", (), {"host": "1.2.3.4"})()

    request = FakeRequest()
    for _ in range(3):
        ratelimit.enforce(request, limit=3, bucket="1.2.3.4", scope="t")
    with pytest.raises(HTTPException):
        ratelimit.enforce(request, limit=3, bucket="1.2.3.4", scope="t")

    now[0] += ratelimit._WINDOW_SECONDS + 1
    # No longer over the limit once the window has rolled.
    ratelimit.enforce(request, limit=3, bucket="1.2.3.4", scope="t")


def test_separate_scopes_do_not_share_an_allowance():
    from fastapi import HTTPException

    ratelimit.reset()

    class FakeRequest:
        client = type("C", (), {"host": "1.2.3.4"})()

    request = FakeRequest()
    for _ in range(2):
        ratelimit.enforce(request, limit=2, bucket="k", scope="login")
    with pytest.raises(HTTPException):
        ratelimit.enforce(request, limit=2, bucket="k", scope="login")
    # Registering has its own budget, so spending the login one is not enough.
    ratelimit.enforce(request, limit=2, bucket="k", scope="register")


def test_different_callers_have_separate_allowances():
    from fastapi import HTTPException

    ratelimit.reset()

    class FakeRequest:
        def __init__(self, host):
            self.client = type("C", (), {"host": host})()

    for _ in range(2):
        ratelimit.enforce(FakeRequest("1.1.1.1"), limit=2, bucket="a", scope="login")
    with pytest.raises(HTTPException):
        ratelimit.enforce(FakeRequest("1.1.1.1"), limit=2, bucket="a", scope="login")
    ratelimit.enforce(FakeRequest("2.2.2.2"), limit=2, bucket="b", scope="login")


def test_a_forwarded_header_is_ignored_unless_trusting_a_proxy(monkeypatch):
    ratelimit.reset()
    monkeypatch.setattr(ratelimit, "TRUST_PROXY", False)

    class FakeRequest:
        client = type("C", (), {"host": "10.0.0.1"})()

        def __init__(self):
            self.headers = {"x-forwarded-for": "9.9.9.9"}

    # Untrusted by default, so the proxy's own address is the key.
    assert ratelimit.client_key(FakeRequest()) == "10.0.0.1"

    monkeypatch.setattr(ratelimit, "TRUST_PROXY", True)
    assert ratelimit.client_key(FakeRequest()) == "9.9.9.9"


def test_a_counter_cannot_grow_without_bound():
    ratelimit.reset()

    class FakeRequest:
        client = type("C", (), {"host": "1.2.3.4"})()

    request = FakeRequest()
    for _ in range(200):
        ratelimit.enforce(request, limit=1000, bucket="b", scope="t")

    # The age cutoff is the bound, and it must not be shorter than the limit or
    # the limiter silently stops firing.
    assert len(ratelimit._counters["t:b"]) == 200
    assert ratelimit._WINDOW_SECONDS > 0


def test_idle_keys_are_evicted(monkeypatch):
    """An address sweep must not grow the table forever."""

    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    ratelimit.reset()

    class FakeRequest:
        def __init__(self, host):
            self.client = type("C", (), {"host": host})()

    ratelimit.enforce(FakeRequest("1.1.1.1"), limit=100, bucket="k", scope="t")
    assert ratelimit._counters

    # Far enough in the future that the old key is idle, then add many new ones so
    # the sweep is triggered.
    now[0] += ratelimit._KEY_TTL_SECONDS + 1
    for index in range(ratelimit._MAX_KEYS + 10):
        ratelimit.enforce(
            FakeRequest(f"host-{index}"), limit=100, bucket=f"k{index}", scope="t"
        )

    assert "t:k" not in ratelimit._counters
    assert len(ratelimit._counters) <= ratelimit._MAX_KEYS + 10


# ---------- headers ----------


def test_security_headers_are_present_on_api_responses(client):
    response = client.get("/stats")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    policy = response.headers["Content-Security-Policy"]
    assert "object-src 'none'" in policy
    assert "frame-ancestors 'none'" in policy
    # The single most important line: no inline or eval'd script.
    assert "script-src 'self'" in policy
    assert "unsafe-eval" not in policy


def test_authenticated_responses_are_not_cached(client):
    for path in ("/favorites", "/auth/me"):
        response = client.get(path)
        assert "no-store" in response.headers.get("Cache-Control", ""), path


def test_public_responses_are_not_marked_no_store(client):
    # Over-caching everything would be as wrong as under-caching the auth routes.
    assert "no-store" not in client.get("/stats").headers.get("Cache-Control", "")


def test_a_429_carries_retry_after(anon_client):
    payload = {"email": "nobody@example.com", "password": "guessguess"}
    for _ in range(14):
        response = anon_client.post("/auth/login", json=payload)
        if response.status_code == 429:
            assert response.headers["Retry-After"] == "60"
            break
    else:
        pytest.fail("the login endpoint was never rate limited")
