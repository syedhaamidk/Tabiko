"""The headline numbers in the UI.

The hero states how much of the city is loaded. If that number came from a
template it would drift every time data was re-ingested, so it is measured here
instead and asserted against the rows a test actually seeded.
"""

from app.models import Restaurant, Review


def _seed(session_factory):
    with session_factory() as db:
        db.add_all(
            [
                Restaurant(
                    name="Count Cafe",
                    source="test",
                    source_id="stats-1",
                    latitude=12.99,
                    longitude=77.55,
                    cuisine_tags="Cafe/Bakery",
                ),
                Restaurant(
                    name="Count Biryani",
                    source="test",
                    source_id="stats-2",
                    latitude=12.991,
                    longitude=77.551,
                    cuisine_tags="Biryani, Multi-cuisine",
                ),
            ]
        )
        db.commit()


def test_stats_report_what_is_actually_stored(client, session_factory):
    _seed(session_factory)

    response = client.get("/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["places"] == 2
    # Three distinct tags across two places: the second carries two.
    assert body["cuisines"] == 3
    assert body["cuisine_tags"] == 3
    assert body["reviews"] == 0


def test_stats_count_reviews(client, session_factory):
    _seed(session_factory)
    with session_factory() as db:
        user_id = _make_user(db)
        place = db.query(Restaurant).first()
        db.add(
            Review(
                user_id=user_id,
                restaurant_id=place.id,
                rating=4,
                text="Solid filter coffee.",
            )
        )
        db.commit()

    assert client.get("/stats").json()["reviews"] == 1


def _make_user(db):
    from app.models import User

    user = User(name="Stats Tester", email="stats@test.local", password_hash="x")
    db.add(user)
    db.flush()
    return user.id
