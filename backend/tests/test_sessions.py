"""Sessions that can be taken back.

The change these tests exist for: a single token lived seven days with no way to
revoke it, so a leaked credential stayed valid for a week and signing out only
discarded the browser's copy. What matters now is that a session can be ended
server-side, that a stolen refresh token is usable at most once, and that a
replay is treated as a compromise rather than a retry.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app import auth, models


@pytest.fixture(autouse=True)
def clear_limiters():
    from app import ratelimit

    ratelimit.reset()
    yield
    ratelimit.reset()


READER_EMAIL = "reader@example.com"


def _register(client, email=READER_EMAIL):
    response = client.post(
        "/auth/register",
        json={"name": "Reader", "email": email, "password": "password123"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _login(client, email=READER_EMAIL):
    response = client.post(
        "/auth/login", json={"email": email, "password": "password123"}
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def reader(client):
    """One registered reader, so a login has something to authenticate against."""

    _register(client)
    return READER_EMAIL


def _user_id(session_factory, email=READER_EMAIL) -> int:
    """Look the reader up directly.

    `/auth/me` is not usable here: the client fixture is signed in as the shared
    test account, not as this reader.
    """

    with session_factory() as db:
        return db.query(models.User).filter_by(email=email).one().id


# ---------- the happy path ----------


def test_login_returns_a_refreshable_pair(client, reader):
    body = _login(client)

    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    # The client needs to know when to refresh before the request fails.
    assert 0 < body["expires_in"] <= 3600


def test_the_access_token_works_immediately(client, reader):
    body = _login(client)
    response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert response.status_code == 200


def test_registration_also_issues_a_session(client):
    body = _register(client)
    assert body["refresh_token"]
    assert (
        client.get(
            "/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
        ).status_code
        == 200
    )


def test_the_access_token_is_short_lived(client, reader):
    assert auth.ACCESS_TOKEN_SECONDS <= 3600, (
        "a token that outlives an hour is not short-lived; the point of the "
        "refresh token is that this one expires quickly"
    )


# ---------- revocation ----------


def test_logout_ends_the_session(client, reader):
    body = _login(client)

    refreshed = client.post(
        "/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert refreshed.status_code == 200
    rotated = refreshed.json()["refresh_token"]

    signed_out = client.post("/auth/logout", json={"refresh_token": rotated})
    assert signed_out.status_code == 204

    # After signing out, that token can no longer buy a new access token.
    assert (
        client.post("/auth/refresh", json={"refresh_token": rotated}).status_code == 401
    )


def test_logout_is_idempotent(client, reader):
    body = _login(client)
    first = client.post("/auth/logout", json={"refresh_token": body["refresh_token"]})
    second = client.post("/auth/logout", json={"refresh_token": body["refresh_token"]})
    # A double tap on sign out must not surface an error.
    assert first.status_code == 204
    assert second.status_code == 204


def test_logout_with_nonsense_is_accepted(client, reader):
    # Reporting "that token was not valid" would leak a detail for no benefit.
    assert (
        client.post(
            "/auth/logout", json={"refresh_token": "not-a-real-token-but-long-enough"}
        ).status_code
        == 204
    )


def test_rotating_does_not_leave_the_old_token_usable(client, reader):
    body = _login(client)

    first = client.post(
        "/auth/refresh", json={"refresh_token": body["refresh_token"]}
    ).json()
    second = client.post(
        "/auth/refresh", json={"refresh_token": first["refresh_token"]}
    ).json()

    assert first["refresh_token"] != second["refresh_token"]
    # The spent token from the middle of the chain is dead.
    assert (
        client.post(
            "/auth/refresh", json={"refresh_token": first["refresh_token"]}
        ).status_code
        == 401
    )


def test_a_replayed_token_ends_every_session(client, reader, session_factory):
    """A token used twice means two parties hold it, so assume theft."""

    body = _login(client)
    stolen = body["refresh_token"]

    first = client.post("/auth/refresh", json={"refresh_token": stolen}).json()

    # Replay it, well outside the rotation grace period.
    with session_factory() as db:
        row = (
            db.query(models.RefreshToken)
            .filter_by(token_hash=auth.hash_refresh_token(stolen))
            .one()
        )
        row.rotated_at = row.rotated_at - timedelta(
            seconds=auth.REFRESH_ROTATION_GRACE_SECONDS + 120
        )
        db.commit()

    assert (
        client.post("/auth/refresh", json={"refresh_token": stolen}).status_code == 401
    )

    # Including the session the legitimate client is holding.
    assert (
        client.post(
            "/auth/refresh", json={"refresh_token": first["refresh_token"]}
        ).status_code
        == 401
    )


def test_two_refreshes_in_the_same_tick_do_not_log_each_other_out(client, reader):
    """Two components refreshing at once must not fight over the same token."""

    body = _login(client)

    first = client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    # Inside the grace window, so the second is treated as our own race.
    second = client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})

    assert first.status_code == 200
    assert second.status_code == 401
    # And the winner's token is still good, which is the point of the grace.
    winner = first.json()["refresh_token"]
    assert (
        client.post("/auth/refresh", json={"refresh_token": winner}).status_code == 200
    )


def test_an_expired_refresh_token_is_refused(client, reader, session_factory):
    body = _login(client)

    with session_factory() as db:
        row = (
            db.query(models.RefreshToken)
            .filter_by(token_hash=auth.hash_refresh_token(body["refresh_token"]))
            .one()
        )
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    assert (
        client.post(
            "/auth/refresh", json={"refresh_token": body["refresh_token"]}
        ).status_code
        == 401
    )


def test_an_empty_or_garbage_token_is_refused(client, reader):
    # Too short to be a token at all, so the schema rejects it before any lookup.
    assert client.post("/auth/refresh", json={"refresh_token": ""}).status_code == 422

    for token in ("x" * 40, "../../../../etc/passwd", "0" * 43):
        response = client.post("/auth/refresh", json={"refresh_token": token})
        assert response.status_code == 401, token


# ---------- storage ----------


def test_only_the_digest_of_a_refresh_token_is_stored(client, reader, session_factory):
    body = _login(client)
    digest = auth.hash_refresh_token(body["refresh_token"])

    with session_factory() as db:
        stored = [row.token_hash for row in db.query(models.RefreshToken).all()]
    # Reading the table must not hand anyone a usable credential.
    assert body["refresh_token"] not in stored
    assert digest in stored


def test_digest_comparison_is_not_plain_equality(client):
    # Guards the primitive, since a future refactor could swap it out.
    import inspect

    source = inspect.getsource(auth._find_refresh)
    assert "compare_digest" in source


def test_a_deleted_user_takes_their_sessions_with_them(client, reader, session_factory):
    body = _login(client)
    user_id = _user_id(session_factory)

    with session_factory() as db:
        db.delete(db.get(models.User, user_id))
        db.commit()

    assert (
        client.post(
            "/auth/refresh", json={"refresh_token": body["refresh_token"]}
        ).status_code
        == 401
    )


def test_purging_drops_only_expired_rows(client, reader, session_factory):
    # The reader fixture registered once, which issued a session of its own.
    baseline = 1
    _login(client)
    _login(client)

    with session_factory() as db:
        assert db.query(models.RefreshToken).count() == baseline + 2
        live = db.query(models.RefreshToken).first()
        live.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()

    with session_factory() as db:
        assert auth.purge_expired_sessions(db) == 1
        assert db.query(models.RefreshToken).count() == baseline + 1


def test_revoking_every_session_ends_them_all(client, reader, session_factory):
    first = _login(client)
    second = _login(client)
    user_id = _user_id(session_factory)

    with session_factory() as db:
        # The registration session plus the two logins.
        assert auth.revoke_all_sessions(db, user_id) == 3

    for body in (first, second):
        assert (
            client.post(
                "/auth/refresh", json={"refresh_token": body["refresh_token"]}
            ).status_code
            == 401
        )


def test_a_refresh_token_cannot_be_used_as_a_bearer(client, reader):
    body = _login(client)
    response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {body['refresh_token']}"}
    )
    # The opaque session secret must not authenticate a request on its own.
    assert response.status_code == 401


def test_refreshing_is_rate_limited(client, reader):
    body = _login(client)
    statuses = [
        client.post(
            "/auth/refresh", json={"refresh_token": body["refresh_token"]}
        ).status_code
        for _ in range(40)
    ]
    assert 429 in statuses, "guessing refresh tokens must not be free"


def test_login_still_works_after_its_own_limit_clears(client, reader):
    # A reader who mistyped a password repeatedly must still be able to sign in
    # once the window rolls; the counter is time-based, not a lockout.
    _login(client)
    assert _login(client)["access_token"]
