"""Following people: the endpoints, and the properties the brief asked for.

The feature is deliberately small -- a follows table, immediate, no requests and
no notifications -- so the interesting behaviour is all in the edges: doing it
twice, doing it to yourself, doing it while logged out, and the counts staying
true afterwards. Those are what is tested here.

One thing is deliberately *not* fixed: the follow-status lookup is one request
per reviewer. That is written up at the bottom of this file, as the brief asked.
"""

import contextlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import auth
from app.database import get_db
from app.main import app
from app.models import Restaurant, Review, User, utc_now

# ---------- fixtures ----------


@pytest.fixture
def people(session_factory, seeded_data):
    """Three other readers, so following, the counts and the feed have something to say.

    `seeded_data` is what creates the place; without it there is nothing to
    review and the feed tests would pass for the wrong reason.
    """

    with session_factory() as db:
        made = []
        for name in ("Bala", "Chetan", "Divya"):
            user = User(
                name=name,
                email=f"{name.lower()}@example.com",
                password_hash=auth.hash_password("their-password-2026"),
            )
            db.add(user)
            made.append(user)
        db.commit()
        for user in made:
            db.refresh(user)
        return {user.name: user.id for user in made}


@pytest.fixture
def viewer_id(session_factory, seeded_data):
    """The signed-in reader the `client` fixture authenticates as."""
    with session_factory() as db:
        return db.query(User).filter_by(email="asha@example.com").one().id


@pytest.fixture
def as_user(db_engine):
    """Make an authenticated client for any user, without fighting fixture order.

    Several tests need to be *two* readers at once -- one following, one being
    followed -- and the shared `client` fixture is hard-wired to one of them.
    This is that, generalised.
    """

    def override_get_db():
        session = sessionmaker(
            bind=db_engine, autoflush=False, expire_on_commit=False
        )()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with contextlib.ExitStack() as stack:

            def make(user_id: int) -> TestClient:
                token = auth.create_access_token(user_id)
                return stack.enter_context(
                    TestClient(app, headers={"Authorization": f"Bearer {token}"})
                )

            yield make
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def place(session_factory, seeded_data):
    """The place the reviews are about.

    Depends on `seeded_data` explicitly rather than relying on another fixture
    pulling it in: a test that only asks for `place` would otherwise get a
    NoResultFound, which reads like a broken endpoint rather than a missing
    fixture dependency.
    """

    with session_factory() as db:
        return db.query(Restaurant).filter_by(source_id="test-restaurant-1").one().id


def add_review(session_factory, user_id: int, restaurant_id: int, text: str, **extra):
    """Write a review row directly.

    Not through `POST /reviews`, because that path rate-limits, runs the fraud
    scorer and applies a verification tier, none of which is what these tests are
    about. Writing the row keeps them about the follow behaviour and nothing else.
    """

    with session_factory() as db:
        review = Review(
            user_id=user_id,
            restaurant_id=restaurant_id,
            rating=extra.get("rating", 5),
            text=text,
            verification_tier=extra.get("verification_tier", "unverified"),
            fraud_flag=extra.get("fraud_flag", False),
            fraud_reason=extra.get("fraud_reason"),
            created_at=extra.get("created_at", utc_now()),
        )
        db.add(review)
        db.commit()
        db.refresh(review)
        return review.id


# ---------- following is idempotent ----------


def test_following_then_unfollowing_round_trips(client, people):
    other = people["Bala"]

    followed = client.post(f"/users/{other}/follow")
    assert followed.status_code == 200
    assert followed.json()["is_following"] is True
    assert followed.json()["follower_count"] == 1

    unfollowed = client.delete(f"/users/{other}/follow")
    assert unfollowed.status_code == 200
    assert unfollowed.json()["is_following"] is False
    assert unfollowed.json()["follower_count"] == 0


def test_following_twice_does_not_double_up(client, people, session_factory):
    """A double tap on a flaky connection is the normal case, not an edge case.

    The unique pair on the table is what makes this hold. Without it the counts
    would drift upward every time a request was retried, and because the counts
    are what the button label is built from, the label would lie.
    """

    other = people["Bala"]

    for _ in range(4):
        assert client.post(f"/users/{other}/follow").json()["follower_count"] == 1

    with session_factory() as db:
        from app.models import Follow

        rows = db.query(Follow).filter_by(followed_id=other).count()
    assert rows == 1, f"four taps created {rows} rows"


def test_unfollowing_twice_is_fine_and_unfollowing_a_stranger_is_fine(client, people):
    """Both directions have to tolerate the button being pressed twice."""
    bala, chetan = people["Bala"], people["Chetan"]

    client.post(f"/users/{bala}/follow")
    first = client.delete(f"/users/{bala}/follow")
    second = client.delete(f"/users/{bala}/follow")

    assert first.status_code == second.status_code == 200
    assert first.json()["follower_count"] == second.json()["follower_count"] == 0

    # Never followed in the first place.
    assert client.delete(f"/users/{chetan}/follow").status_code == 200


def test_following_restores_after_unfollowing(client, people):
    """A reader who unfollows and changes their mind must not hit a conflict."""
    other = people["Bala"]

    client.post(f"/users/{other}/follow")
    client.delete(f"/users/{other}/follow")
    again = client.post(f"/users/{other}/follow")

    assert again.status_code == 200
    assert again.json()["is_following"] is True
    assert again.json()["follower_count"] == 1


# ---------- not yourself ----------


def test_you_cannot_follow_yourself(client, viewer_id):
    response = client.post(f"/users/{viewer_id}/follow")

    assert response.status_code == 422
    assert "yourself" in response.json()["detail"]


def test_you_cannot_unfollow_yourself_either(client, viewer_id):
    assert client.delete(f"/users/{viewer_id}/follow").status_code == 422


def test_a_self_follow_row_cannot_be_written_at_all(session_factory, viewer_id):
    """The CHECK constraint, not the endpoint.

    An endpoint guard is a convention. A constraint is the only thing that still
    holds when the row is written by a script, a migration or a future admin
    tool -- which is exactly the case where nobody is thinking about it.
    """

    from app.models import Follow

    with session_factory() as db:
        db.add(Follow(follower_id=viewer_id, followed_id=viewer_id))
        with pytest.raises(Exception, match="follow"):
            db.commit()
        db.rollback()

    with session_factory() as db:
        assert db.query(Follow).count() == 0


def test_following_someone_who_does_not_exist_is_404(client):
    assert client.post("/users/99999/follow").status_code == 404
    assert client.get("/users/99999/follow-status").status_code == 404


def test_every_follow_endpoint_needs_an_account(anon_client, people):
    other = people["Bala"]
    assert anon_client.post(f"/users/{other}/follow").status_code == 401
    assert anon_client.delete(f"/users/{other}/follow").status_code == 401
    assert anon_client.get(f"/users/{other}/follow-status").status_code == 401
    assert anon_client.get("/users/me/following").status_code == 401
    assert anon_client.get("/feed/following").status_code == 401
    assert anon_client.get("/users/search?q=Ba").status_code == 401


# ---------- counts stay accurate ----------


def test_counts_stay_right_when_several_people_follow_one_reader(
    as_user, people, viewer_id
):
    """The count is a query, not a stored number, so it cannot drift.

    The tempting implementation keeps an integer on the user row and increments
    it. That is a second source of truth, and it disagrees with the table the
    first time a request is retried or two of them race.
    """

    bala, chetan, divya = people["Bala"], people["Chetan"], people["Divya"]

    # Three distinct readers follow Bala. Bala is deliberately not one of them,
    # because following yourself is refused -- including her would have made the
    # count quietly one short rather than failing loudly.
    for follower in (viewer_id, chetan, divya):
        assert as_user(follower).post(f"/users/{bala}/follow").status_code == 200

    status = as_user(bala).get(f"/users/{bala}/follow-status").json()
    assert status["follower_count"] == 3
    assert status["following_count"] == 0, "nobody here follows Bala back"

    # And one unfollow moves it by exactly one.
    as_user(divya).delete(f"/users/{bala}/follow")
    assert (
        as_user(bala).get(f"/users/{bala}/follow-status").json()["follower_count"] == 2
    )


def test_follow_status_describes_the_subject_not_the_viewer(client, people):
    """`follower_count` and `following_count` are both about the person asked about.

    Worth pinning down because the same two numbers are used in two directions,
    and mixing them up produces a button that says the wrong thing.
    """

    after_follow = client.post(f"/users/{people['Bala']}/follow").json()
    assert after_follow["follower_count"] == 1, "Bala gained a follower"
    assert after_follow["following_count"] == 1, "Asha follows one person"

    status = client.get(f"/users/{people['Bala']}/follow-status").json()
    assert status["is_following"] is True
    assert status["follower_count"] == 1
    assert status["following_count"] == 0, "Bala follows nobody"


def test_follow_status_for_someone_you_do_not_follow_is_false(client, people):
    status = client.get(f"/users/{people['Bala']}/follow-status").json()
    assert status["is_following"] is False
    assert status["follower_count"] == 0


# ---------- searching for people ----------


def test_search_finds_a_reader_by_name(client, people):
    results = client.get("/users/search?q=Bal").json()

    assert [user["name"] for user in results] == ["Bala"]
    assert results[0]["is_following"] is False
    assert results[0]["follower_count"] == 0


@pytest.mark.parametrize("term", ["BALA", "bala", "Ba", "ba"])
def test_search_is_case_insensitive_and_partial(client, people, term):
    assert [user["name"] for user in client.get(f"/users/search?q={term}").json()] == [
        "Bala"
    ]


def test_search_excludes_you(client, viewer_id):
    """You should not appear in your own people search, even under your own name."""
    assert client.get("/users/search?q=Asha").json() == []


def test_search_excludes_you_on_a_partial_match(client, viewer_id):
    """A prefix that only matches you must not surface you either."""
    assert client.get("/users/search?q=sh").json() == []


def test_search_is_capped(as_user, session_factory, viewer_id):
    """Otherwise it is a paginated dump of the users table."""

    from app import main

    with session_factory() as db:
        for index in range(60):
            db.add(
                User(
                    name=f"Reader {index:02d}",
                    email=f"r{index:02d}@example.com",
                    password_hash=auth.hash_password("p"),
                )
            )
        db.commit()

    results = as_user(viewer_id).get("/users/search?q=Reader").json()

    assert len(results) == main.USER_SEARCH_LIMIT
    assert main.USER_SEARCH_LIMIT == 25


def test_search_excludes_self_from_the_cap(as_user, session_factory, viewer_id):
    """The cap must not be spent on you.

    Named to sort first, so a self-match at the top of an alphabetical list
    would take one of the 25 slots a reader could have been looking for -- and
    the result would look correct because it is simply shorter.
    """

    from app import main

    with session_factory() as db:
        db.query(User).filter_by(email="asha@example.com").one().name = "Aaa Reader"
        for index in range(main.USER_SEARCH_LIMIT + 5):
            db.add(
                User(
                    name=f"Reader {index:02d}",
                    email=f"r{index:02d}@example.com",
                    password_hash=auth.hash_password("p"),
                )
            )
        db.commit()

    results = as_user(viewer_id).get("/users/search?q=Reader").json()

    assert len(results) == main.USER_SEARCH_LIMIT
    assert "Aaa Reader" not in [user["name"] for user in results]


def test_search_with_nothing_matching_is_empty(client):
    assert client.get("/users/search?q=zzzznobody").json() == []


def test_search_rejects_an_empty_query(client):
    assert client.get("/users/search?q=").status_code == 422


def test_search_rejects_an_absurdly_long_query(client):
    assert client.get(f"/users/search?q={'a' * 100}").status_code == 422


# ---------- the following list ----------


def test_my_following_lists_only_people_i_follow(as_user, people):
    chetan = as_user(people["Chetan"])
    chetan.post(f"/users/{people['Bala']}/follow")
    chetan.post(f"/users/{people['Divya']}/follow")

    listing = chetan.get("/users/me/following").json()

    assert listing["count"] == 2
    assert {user["name"] for user in listing["users"]} == {"Bala", "Divya"}
    assert all(user["is_following"] for user in listing["users"])


def test_my_following_does_not_list_the_other_direction(as_user, people):
    """Following is not mutual, and the list must not pretend it is."""
    bala = as_user(people["Bala"])
    bala.post(f"/users/{people['Chetan']}/follow")

    assert as_user(people["Chetan"]).get("/users/me/following").json()["count"] == 0
    assert as_user(people["Bala"]).get("/users/me/following").json()["count"] == 1


def test_my_following_is_empty_for_someone_who_follows_nobody(client):
    assert client.get("/users/me/following").json() == {"users": [], "count": 0}


def test_my_following_shrinks_on_unfollow(as_user, people):
    chetan = as_user(people["Chetan"])
    chetan.post(f"/users/{people['Bala']}/follow")
    chetan.delete(f"/users/{people['Bala']}/follow")

    assert chetan.get("/users/me/following").json() == {"users": [], "count": 0}


# ---------- the feed ----------


def test_the_feed_carries_reviews_from_people_i_follow(
    as_user, session_factory, people, place
):
    add_review(session_factory, people["Bala"], place, "The dosa here is exceptional.")
    add_review(session_factory, people["Divya"], place, "Coffee was cold.")

    chetan = as_user(people["Chetan"])
    chetan.post(f"/users/{people['Bala']}/follow")
    feed = chetan.get("/feed/following").json()

    # Divya was not followed, so her review is absent.
    assert feed["count"] == 1
    entry = feed["entries"][0]
    assert entry["review"]["text"] == "The dosa here is exceptional."
    assert entry["restaurant_name"] == "Campus Cafe"
    assert entry["review"]["reviewer"]["name"] == "Bala"


def test_the_feed_empties_correctly_after_unfollow(
    as_user, session_factory, people, place
):
    """The property the brief named specifically, and the one most likely to break.

    A feed that keeps showing someone you unfollowed is worse than one that is
    slow to update: it means the filter is cached rather than applied.
    """

    add_review(session_factory, people["Bala"], place, "Worth the queue.")

    chetan = as_user(people["Chetan"])
    chetan.post(f"/users/{people['Bala']}/follow")
    assert chetan.get("/feed/following").json()["count"] == 1

    chetan.delete(f"/users/{people['Bala']}/follow")
    after = chetan.get("/feed/following").json()

    assert after == {"entries": [], "count": 0}, (
        "an unfollowed person's review was still in the feed"
    )


def test_the_feed_empties_when_the_person_unfollows_you(
    as_user, session_factory, people, place
):
    """The other direction: the follow is what puts a review in a feed, not
    who wrote it. If Divya stops following Bala, Divya loses the review."""

    add_review(session_factory, people["Bala"], place, "From Bala.")

    divya = as_user(people["Divya"])
    divya.post(f"/users/{people['Bala']}/follow")
    assert divya.get("/feed/following").json()["count"] == 1

    divya.delete(f"/users/{people['Bala']}/follow")
    assert divya.get("/feed/following").json() == {"entries": [], "count": 0}


def test_the_feed_is_empty_for_someone_who_follows_nobody(client):
    assert client.get("/feed/following").json() == {"entries": [], "count": 0}


def test_the_feed_does_not_show_your_own_reviews_even_though_you_are_followed(
    as_user, session_factory, people, place
):
    """Your own review is already on the page you wrote it from.

    Including it would make every reader's feed open with themselves, which is
    not a feed of other people's opinions.
    """

    bala, chetan = people["Bala"], people["Chetan"]
    add_review(session_factory, bala, place, "Bala on the place.")
    add_review(session_factory, chetan, place, "Chetan on the place.")

    # Bala follows Chetan. Chetan follows nobody.
    as_user(bala).post(f"/users/{chetan}/follow")
    feed = as_user(bala).get("/feed/following").json()

    assert [entry["review"]["text"] for entry in feed["entries"]] == [
        "Chetan on the place."
    ]


def test_the_feed_is_chronological_most_recent_first(
    as_user, session_factory, people, place
):
    """No ranking, no weighting. A feed you cannot explain is one you cannot trust."""

    import datetime

    base = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    for offset, (name, text) in enumerate(
        (
            ("Bala", "First, the oldest."),
            ("Divya", "Second."),
            ("Chetan", "Third, the newest."),
        )
    ):
        add_review(
            session_factory,
            people[name],
            place,
            text,
            created_at=base + datetime.timedelta(hours=offset),
        )

    viewer = as_user(people["Bala"])
    for name in ("Chetan", "Divya"):
        viewer.post(f"/users/{people[name]}/follow")
    entries = viewer.get("/feed/following").json()["entries"]

    # Bala's own review is not in her feed, so the two followed readers' are --
    # newest first. Her own exclusion is asserted separately; including her here
    # would have made this a test of two things at once.
    assert [entry["review"]["text"] for entry in entries] == [
        "Third, the newest.",
        "Second.",
    ]


def test_the_feed_omits_flagged_reviews(as_user, session_factory, people, place):
    """A flagged review must not surface as a trusted reader's opinion just
    because you follow them. Following is not a free pass."""

    kept = add_review(session_factory, people["Bala"], place, "Legitimate.")
    add_review(
        session_factory,
        people["Divya"],
        place,
        "Should not appear.",
        fraud_flag=True,
        fraud_reason="test",
    )

    viewer = as_user(people["Chetan"])
    viewer.post(f"/users/{people['Bala']}/follow")
    viewer.post(f"/users/{people['Divya']}/follow")
    feed = viewer.get("/feed/following").json()

    assert [entry["review"]["id"] for entry in feed["entries"]] == [kept]


def test_the_feed_is_capped(as_user, session_factory, people, place):
    """~50 entries, as specified."""

    from app import main

    for index in range(main.FEED_LIMIT + 5):
        add_review(session_factory, people["Bala"], place, f"Review number {index}.")

    viewer = as_user(people["Chetan"])
    viewer.post(f"/users/{people['Bala']}/follow")
    feed = viewer.get("/feed/following").json()

    assert main.FEED_LIMIT == 50
    assert feed["count"] == main.FEED_LIMIT
    assert len(feed["entries"]) == main.FEED_LIMIT


def test_a_removed_place_does_not_break_the_feed(
    as_user, session_factory, people, seeded_data
):
    """A review outliving its restaurant has to render, not raise.

    Reachable in practice because `PRAGMA foreign_keys` is **off** by default in
    raw `sqlite3` -- the application's own session turns it on, but a script, a
    restore or an ad-hoc query does not. `Review.restaurant_id` is
    `ondelete="CASCADE"`, so a real deletion takes the review with it; the
    dangling case comes from a row written without enforcement, which is exactly
    when it is least expected.
    """

    from sqlalchemy import text

    place_id = seeded_data["restaurant_id"]

    # Through the engine's own connection, and with foreign keys switched off for
    # it, because the application's session would refuse to create the very row
    # this test is about. `StaticPool` means this is the same connection the
    # rest of the test sees, so the row is really there afterwards.
    with session_factory.kw["bind"].begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        connection.execute(
            text(
                """
                insert into reviews
                    (user_id, restaurant_id, rating, text, verification_tier,
                     fraud_flag, created_at)
                values (:user, :place, 5, 'About a place that is gone.',
                        'unverified', 0, '2026-01-01 12:00:00')
                """
            ),
            {"user": people["Bala"], "place": place_id},
        )
        review_id = connection.execute(text("select last_insert_rowid()")).scalar_one()
        connection.execute(
            text("delete from restaurants where id = :place"), {"place": place_id}
        )

    with session_factory() as db:
        assert db.query(Review).filter_by(id=review_id).count() == 1, (
            "the dangling review did not survive, so the test proved nothing"
        )
        assert db.query(Restaurant).filter_by(id=place_id).count() == 0

    viewer = as_user(people["Chetan"])
    viewer.post(f"/users/{people['Bala']}/follow")
    feed = viewer.get("/feed/following").json()

    assert [entry["review"]["id"] for entry in feed["entries"]] == [review_id]
    assert "removed" in feed["entries"][0]["restaurant_name"]
    assert feed["entries"][0]["restaurant_latitude"] is None


# ---------- following_only on the restaurant page ----------


def test_following_only_is_ignored_when_the_parameter_is_absent(
    client, session_factory, people, place
):
    """The default has to be the behaviour that existed before the parameter.

    Anything else and adding a feature silently changed the public reviews list
    that every reader, signed in or not, already relied on.
    """

    add_review(session_factory, people["Bala"], place, "From Bala.")
    add_review(session_factory, people["Divya"], place, "From Divya.")

    everyone = client.get(f"/reviews/restaurant/{place}").json()

    assert len(everyone) == 2, "the default must not filter"
    assert {review["text"] for review in everyone} == {"From Bala.", "From Divya."}


def test_following_only_false_is_public_again(anon_client, seeded_data):
    place = seeded_data["restaurant_id"]
    response = anon_client.get(f"/reviews/restaurant/{place}?following_only=false")
    assert response.status_code == 200


def test_following_only_returns_401_when_signed_out(anon_client, seeded_data):
    """A 401, not an empty list.

    "You follow nobody" and "you are not signed in" are different answers, and
    returning an empty list for both leaves a reader staring at a blank panel
    with no way to tell what went wrong or what to do about it.
    """

    place = seeded_data["restaurant_id"]

    # Sanity: the same request without the filter is public.
    assert anon_client.get(f"/reviews/restaurant/{place}").status_code == 200

    filtered = anon_client.get(f"/reviews/restaurant/{place}?following_only=true")
    assert filtered.status_code == 401
    assert "sign in" in filtered.json()["detail"].lower()


@pytest.mark.parametrize(
    "query", ["following_only=true", "following_only=1", "following_only=True"]
)
def test_the_truthy_spellings_all_count(anon_client, seeded_data, query):
    place = seeded_data["restaurant_id"]
    assert anon_client.get(f"/reviews/restaurant/{place}?{query}").status_code == 401


@pytest.mark.parametrize(
    "query", ["following_only=false", "following_only=0", "following_only=no"]
)
def test_the_falsey_spellings_all_stay_public(anon_client, seeded_data, query):
    place = seeded_data["restaurant_id"]
    assert anon_client.get(f"/reviews/restaurant/{place}?{query}").status_code == 200


def test_a_bad_token_is_a_401_not_a_silent_downgrade(anon_client, seeded_data):
    """The client relies on this distinction to know a refresh is worth trying.

    If a present-but-expired token quietly became "logged out", the frontend
    could never tell "needs refresh" from "signed out", and would show a
    signed-out page to someone who is merely signed-in-expired.
    """

    place = seeded_data["restaurant_id"]
    response = anon_client.get(
        f"/reviews/restaurant/{place}?following_only=true",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert response.status_code == 401


def test_following_only_narrows_the_list(as_user, session_factory, people, place):
    bala_review = add_review(session_factory, people["Bala"], place, "From Bala.")
    add_review(session_factory, people["Divya"], place, "From Divya.")

    chetan = as_user(people["Chetan"])
    assert len(chetan.get(f"/reviews/restaurant/{place}").json()) == 2

    chetan.post(f"/users/{people['Bala']}/follow")
    just_bala = chetan.get(f"/reviews/restaurant/{place}?following_only=true").json()

    assert [review["id"] for review in just_bala] == [bala_review]
    assert just_bala[0]["text"] == "From Bala."


def test_following_only_is_empty_when_i_follow_nobody(
    as_user, session_factory, people, place
):
    add_review(session_factory, people["Bala"], place, "From Bala.")

    chetan = as_user(people["Chetan"])
    response = chetan.get(f"/reviews/restaurant/{place}?following_only=true")

    # Signed in, following nobody: 200 and empty, which is a different answer
    # from the 401 for signed out. The UI shows "follow some people" here.
    assert response.status_code == 200
    assert response.json() == []


def test_following_only_empties_after_unfollow(as_user, session_factory, people, place):
    add_review(session_factory, people["Bala"], place, "From Bala.")

    chetan = as_user(people["Chetan"])
    chetan.post(f"/users/{people['Bala']}/follow")
    assert (
        len(chetan.get(f"/reviews/restaurant/{place}?following_only=true").json()) == 1
    )

    chetan.delete(f"/users/{people['Bala']}/follow")
    assert chetan.get(f"/reviews/restaurant/{place}?following_only=true").json() == []


# ---------- the N+1 the brief asked to have documented ----------


def test_the_shape_that_causes_the_n_plus_one(client, session_factory, people, place):
    """Follow status costs one request per reviewer, and that is intentional here.

    Pinned as a test so the note below cannot quietly go stale: if this ever
    fails, the shape has changed and the write-up should change with it.
    """

    first = add_review(session_factory, people["Bala"], place, "From Bala.")
    second = add_review(session_factory, people["Divya"], place, "From Divya.")
    third = add_review(session_factory, people["Bala"], place, "Also from Bala.")

    reviews = client.get(f"/reviews/restaurant/{place}").json()
    assert {review["id"] for review in reviews} == {first, second, third}

    # The list gives reviewer ids but no follow state. That is the whole of the
    # problem: the client has to ask, once per distinct author.
    assert all("is_following" not in review["reviewer"] for review in reviews)

    # Three reviews, two authors -- so the cost is per-author and not per-review,
    # which is already a reason to dedupe client-side regardless.
    assert len({review["reviewer"]["id"] for review in reviews}) == 2


# ---------------------------------------------------------------------------
# Future batching opportunity, deliberately not implemented
# ---------------------------------------------------------------------------
#
# Rendering the follow button on a list of reviews costs one HTTP request per
# distinct reviewer, because the list endpoint returns the reviewer's id but not
# whether the viewer follows them. A restaurant page with six reviews from six
# people is six requests that are each answered in under a millisecond and
# together add a pause you can see.
#
# Three ways to remove it, none taken here because the brief asked for this to be
# documented rather than fixed:
#
#   1. Put `is_following` on `ReviewerInfo`, computed with one extra join of the
#      viewer's follows. Cheapest change, but it makes an anonymous list response
#      vary by viewer, which complicates any caching of that endpoint.
#   2. `GET /users/follow-status?ids=1,2,3` returning a map. One extra request
#      per page rather than per reviewer; the client still has to key the result.
#   3. Include follow state only when the viewer is signed in, and have the
#      frontend render a plain "Follow" button until the batch arrives. Avoids
#      the caching problem in (1), at the cost of a visible state change.
#
# The reason it has not been done is that it is currently a latency nicety on a
# page with few reviews, and none of the three fixes is free. Whoever picks it up
# should decide which trade-off is acceptable rather than reaching for the first
# one that compiles.
