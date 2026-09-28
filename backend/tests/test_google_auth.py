"""Google sign-in: a new front door, not a new auth system.

The endpoint verifies a Google ID token and mints a normal Tabiko session, so
everything interesting is at the boundary: what Google claims, what the server
accepts, and which account the reader ends up in. The session machinery itself
(rotation, revocation, rate limits) is covered elsewhere and is only asserted
here once, to prove a Google login really produces one.

Google is never contacted. `verify_google_token` is stubbed per test, which is
also what keeps the suite offline-deterministic — the alternative is a test
that phones Mountain View.
"""

import pytest

from app import auth

SUB = "google-sub-111"
EMAIL = "meera@example.com"
CLIENT_ID = "test-client-id.apps.googleusercontent.com"


@pytest.fixture(autouse=True)
def clear_limiters():
    from app import ratelimit

    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def google(monkeypatch):
    """A configured Google project with a stubbed verifier.

    Returns `present(**overrides)`, which sets the claims the next sign-in
    will present. Anything but `"good-token"` is refused, the way a forged or
    expired token would be.
    """

    monkeypatch.setattr(auth, "GOOGLE_CLIENT_ID", CLIENT_ID)
    state = {"claims": None}

    def present(**overrides):
        base = {
            "sub": SUB,
            "email": EMAIL,
            "email_verified": True,
            "name": "Meera",
            "iss": "https://accounts.google.com",
            "aud": CLIENT_ID,
        }
        base.update(overrides)
        state["claims"] = base
        return base

    def verify(token):
        if token != "good-token":
            raise ValueError("bad token")
        return dict(state["claims"])

    present()
    monkeypatch.setattr(auth, "verify_google_token", verify)
    return present


def sign_in(anon_client, token="good-token"):
    return anon_client.post("/auth/google", json={"id_token": token})


# ---------- the providers endpoint ----------


def test_providers_reports_disabled_without_a_client_id(anon_client, monkeypatch):
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_ID", "")

    body = anon_client.get("/auth/providers").json()

    assert body == {"google_enabled": False, "google_client_id": None}


def test_providers_reports_enabled_with_the_client_id(anon_client, google):
    body = anon_client.get("/auth/providers").json()

    assert body == {"google_enabled": True, "google_client_id": CLIENT_ID}


def test_providers_needs_no_account(anon_client):
    assert anon_client.get("/auth/providers").status_code == 200


# ---------- first sign-in creates ----------


def test_first_sign_in_creates_a_passwordless_account(
    anon_client, session_factory, google
):
    from app.models import User

    response = sign_in(anon_client)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]

    with session_factory() as db:
        user = db.query(User).filter_by(email=EMAIL).one()
        assert user.google_sub == SUB
        assert user.name == "Meera"
        assert user.password_hash is None, (
            "a Google-created account must have no password to guess"
        )


def test_the_session_is_a_real_tabiko_session(anon_client, google):
    """Rotation, refresh and /auth/me all work — nothing downstream knows."""

    tokens = sign_in(anon_client).json()

    me = anon_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == EMAIL

    refreshed = anon_client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != tokens["access_token"]


def test_a_name_is_derived_when_google_sends_none(anon_client, session_factory, google):
    from app.models import User

    google(name=None)

    assert sign_in(anon_client).status_code == 200
    with session_factory() as db:
        assert db.query(User).filter_by(email=EMAIL).one().name == "meera"


# ---------- a known email links, keeping everything ----------


def test_sign_in_links_a_matching_password_account(
    anon_client, session_factory, seeded_data, google
):
    """The reader keeps their reviews, saves and follows — the sub attaches."""

    from app.models import Review, User

    with session_factory() as db:
        me = db.query(User).filter_by(email="asha@example.com").one()
        me_id = me.id
        db.add(
            Review(
                user_id=me_id,
                restaurant_id=seeded_data["restaurant_id"],
                rating=5,
                text="Mine before Google.",
                verification_tier="unverified",
            )
        )
        db.commit()

    # Google reports the same address the password account uses.
    google(email="asha@example.com", name="Asha")

    assert sign_in(anon_client).status_code == 200
    with session_factory() as db:
        linked = db.query(User).filter_by(email="asha@example.com").one()
        assert linked.id == me_id, "linking must not create a second account"
        assert linked.google_sub == SUB
        assert linked.password_hash is not None, (
            "linking adds a credential, it must not remove one"
        )
        assert (
            db.query(Review).filter_by(user_id=me_id).one().text
            == "Mine before Google."
        )


def test_a_second_sign_in_returns_to_the_same_account(
    anon_client, session_factory, google
):
    from app.models import User

    first = sign_in(anon_client).json()
    second = sign_in(anon_client).json()

    assert second["access_token"] != first["access_token"]
    with session_factory() as db:
        assert db.query(User).filter_by(email=EMAIL).count() == 1


def test_two_google_accounts_do_not_collide(anon_client, session_factory, google):
    from app.models import User

    assert sign_in(anon_client).status_code == 200

    google(sub="google-sub-222", email="farhan@example.com", name="Farhan")
    assert sign_in(anon_client).status_code == 200

    with session_factory() as db:
        assert db.query(User).count() == 2


def test_an_admin_email_is_still_promoted(
    anon_client, session_factory, google, monkeypatch
):
    from app.models import User

    monkeypatch.setattr(auth, "ADMIN_EMAILS", {"boss@example.com"})
    google(email="boss@example.com", name="Boss")

    assert sign_in(anon_client).status_code == 200
    with session_factory() as db:
        assert db.query(User).filter_by(email="boss@example.com").one().is_admin is True


# ---------- refusals ----------


def test_an_unverified_email_proves_nothing(anon_client, session_factory, google):
    """Accepting it would let anyone claim anyone else's account by typing
    their address into a Google signup form."""

    from app.models import User

    google(email_verified=False)

    response = sign_in(anon_client)

    assert response.status_code == 401
    assert "verified" in response.json()["detail"]
    with session_factory() as db:
        assert db.query(User).filter_by(email=EMAIL).count() == 0


def test_a_forged_or_expired_token_is_one_undistinguished_401(
    anon_client, session_factory, google
):
    from app.models import User

    response = sign_in(anon_client, token="forged-token")

    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers
    with session_factory() as db:
        assert db.query(User).filter_by(email=EMAIL).count() == 0


def test_a_token_without_identity_is_refused(anon_client, google):
    google(sub=None, email=None)

    assert sign_in(anon_client).status_code == 401


def test_an_unconfigured_server_refuses_rather_than_verifying_against_nothing(
    anon_client, monkeypatch
):
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_ID", "")

    response = sign_in(anon_client)

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]
