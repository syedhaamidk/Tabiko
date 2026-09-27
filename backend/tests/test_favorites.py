"""Saved places.

A shortlist is the one piece of state a reader builds up over time, so the
behaviour worth pinning down is idempotency: saving and unsaving are things a
button gets tapped twice, and neither may produce a duplicate row or an error.
"""

import pytest

from app.models import Restaurant


@pytest.fixture
def two_places(session_factory):
    with session_factory() as db:
        places = [
            Restaurant(
                name="Save Target One",
                source="test",
                source_id="fav-1",
                latitude=12.99,
                longitude=77.55,
            ),
            Restaurant(
                name="Save Target Two",
                source="test",
                source_id="fav-2",
                latitude=12.991,
                longitude=77.551,
            ),
        ]
        db.add_all(places)
        db.commit()
        return [place.id for place in places]


def _fav_ids(client) -> list[int]:
    return [row["restaurant_id"] for row in client.get("/favorites").json()]


def test_saving_a_place_records_it(client, two_places):
    response = client.put(f"/favorites/{two_places[0]}")

    assert response.status_code == 200
    body = response.json()
    assert body["restaurant_id"] == two_places[0]
    assert _fav_ids(client) == [two_places[0]]


def test_saving_the_same_place_twice_still_yields_one_row(client, two_places):
    first = client.put(f"/favorites/{two_places[0]}")
    second = client.put(f"/favorites/{two_places[0]}")

    assert first.status_code == 200
    assert second.status_code == 200
    # The second call must not mint a second row or a second id.
    assert second.json()["id"] == first.json()["id"]
    assert _fav_ids(client) == [two_places[0]]


def test_saving_a_missing_place_is_a_404(client, two_places):
    assert client.put("/favorites/999999").status_code == 404


def test_unsaving_removes_it(client, two_places):
    client.put(f"/favorites/{two_places[0]}")
    client.put(f"/favorites/{two_places[1]}")

    response = client.delete(f"/favorites/{two_places[0]}")

    assert response.status_code == 204
    assert _fav_ids(client) == [two_places[1]]


def test_unsaving_twice_does_not_error(client, two_places):
    client.put(f"/favorites/{two_places[0]}")

    assert client.delete(f"/favorites/{two_places[0]}").status_code == 204
    # A second tap on an already-removed place is a no-op, not a 404.
    assert client.delete(f"/favorites/{two_places[0]}").status_code == 204
    assert _fav_ids(client) == []


def test_favorites_are_listed_newest_first(client, two_places):
    client.put(f"/favorites/{two_places[0]}")
    client.put(f"/favorites/{two_places[1]}")

    assert _fav_ids(client) == [two_places[1], two_places[0]]


def test_favorites_require_a_signed_in_reader(anon_client, two_places):
    assert anon_client.get("/favorites").status_code == 401
    assert anon_client.put(f"/favorites/{two_places[0]}").status_code == 401
    assert anon_client.delete(f"/favorites/{two_places[0]}").status_code == 401


def test_one_reader_never_sees_another_readers_saves(
    client, anon_client, session_factory, two_places
):
    client.put(f"/favorites/{two_places[0]}")

    from app import auth
    from app.models import User

    with session_factory() as db:
        other = User(
            name="Someone Else",
            email="someone@example.com",
            password_hash=auth.hash_password("password123"),
        )
        db.add(other)
        db.commit()
        db.refresh(other)
        other_token = auth.create_access_token(other.id)

    response = anon_client.get(
        "/favorites", headers={"Authorization": f"Bearer {other_token}"}
    )

    assert response.status_code == 200
    assert response.json() == []


def test_saved_places_can_be_listed_as_cards(client, two_places):
    client.put(f"/favorites/{two_places[1]}")
    client.put(f"/favorites/{two_places[0]}")

    response = client.get("/favorites/places")

    assert response.status_code == 200
    body = response.json()
    # Newest save first, and carrying real card fields rather than bare ids.
    assert [row["id"] for row in body] == [two_places[0], two_places[1]]
    assert body[0]["name"] == "Save Target One"
    assert "address" in body[0]


def test_saved_places_skip_places_that_no_longer_exist(
    client, session_factory, two_places
):
    client.put(f"/favorites/{two_places[0]}")
    client.put(f"/favorites/{two_places[1]}")

    with session_factory() as db:
        db.query(Restaurant).filter(Restaurant.id == two_places[0]).delete()
        db.commit()

    response = client.get("/favorites/places")

    assert [row["id"] for row in response.json()] == [two_places[1]]


def test_saved_places_require_a_signed_in_reader(anon_client, two_places):
    assert anon_client.get("/favorites/places").status_code == 401


def test_deleting_a_restaurant_takes_its_saves_with_it(
    client, session_factory, two_places
):
    client.put(f"/favorites/{two_places[0]}")
    client.put(f"/favorites/{two_places[1]}")

    with session_factory() as db:
        db.query(Restaurant).filter(Restaurant.id == two_places[0]).delete()
        db.commit()

    # The shortlist must not keep pointing at a place that no longer exists.
    assert _fav_ids(client) == [two_places[1]]
