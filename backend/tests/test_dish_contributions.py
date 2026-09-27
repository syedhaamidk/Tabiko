"""Contributing a menu.

Filling in a menu one dish per form submission is why nobody fills one in, so
bulk entry is the feature, and the interesting behaviour is all in how it treats a
pasted list that overlaps what is already there: duplicates are reported, not
raised, because refusing the batch would throw away the new dishes too.
"""

import pytest

from app import models


@pytest.fixture(autouse=True)
def clear_limiters():
    from app import ratelimit

    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def place(session_factory):
    with session_factory() as db:
        restaurant = models.Restaurant(
            name="Corner Cafe",
            source="test",
            source_id="menu-1",
            latitude=12.99,
            longitude=77.55,
        )
        db.add(restaurant)
        db.commit()
        db.refresh(restaurant)
        return restaurant.id


def _add_dish(client, restaurant_id, name, tags=None):
    return client.post(
        f"/restaurants/{restaurant_id}/dishes",
        json={"name": name, "tags": tags},
    )


def _bulk(client, restaurant_id, text):
    return client.post(
        f"/restaurants/{restaurant_id}/dishes/bulk",
        json={"text": text},
    )


# ---------- parsing ----------


def test_a_line_becomes_a_name_and_its_tags(client, place):
    response = _bulk(client, place, "Masala Dosa, veg, breakfast")

    assert response.status_code == 201
    added = response.json()["added"]
    assert len(added) == 1
    assert added[0]["name"] == "Masala Dosa"
    assert added[0]["tags"] == "veg, breakfast"


def test_a_line_without_a_comma_is_just_a_name(client, place):
    added = _bulk(client, place, "Filter Coffee").json()["added"]
    assert added[0]["name"] == "Filter Coffee"
    assert added[0]["tags"] is None


def test_blank_lines_and_trailing_newlines_are_ignored(client, place):
    # A pasted list always has them, and rejecting the batch over one would be
    # maddening.
    response = _bulk(client, place, "\nMasala Dosa\n\n\nIdli, veg\n   \n")

    assert [dish["name"] for dish in response.json()["added"]] == [
        "Masala Dosa",
        "Idli",
    ]


def test_a_full_menu_goes_in_at_once(client, place):
    menu = "\n".join(f"Dish {index}, tasty" for index in range(25))

    response = _bulk(client, place, menu)

    assert response.status_code == 201
    assert len(response.json()["added"]) == 25
    assert len(client.get(f"/restaurants/{place}/dishes").json()) == 25


def test_text_with_no_dishes_is_rejected(client, place):
    response = _bulk(client, place, "   \n\n  ")

    assert response.status_code == 422
    assert "one per line" in response.json()["detail"].lower()


def test_a_line_that_is_only_commas_is_skipped(client, place):
    added = _bulk(client, place, ",,,\nMasala Dosa").json()["added"]
    assert [dish["name"] for dish in added] == ["Masala Dosa"]


# ---------- duplicates ----------


def test_duplicates_are_reported_rather_than_raised(client, place):
    _bulk(client, place, "Masala Dosa, veg")

    response = _bulk(client, place, "Masala Dosa, veg\nIdli, veg")

    assert response.status_code == 201
    body = response.json()
    # The new line still lands, and the collision is reported.
    assert [dish["name"] for dish in body["added"]] == ["Idli"]
    assert body["skipped"] == ["Masala Dosa"]


def test_a_duplicated_name_inside_one_paste_is_collapsed(client, place):
    body = _bulk(client, place, "Vada\nVada\nVada, extra tags").json()

    assert len(body["added"]) == 1
    assert body["added"][0]["name"] == "Vada"
    assert "Vada" in body["skipped"]


def test_duplicates_are_matched_case_insensitively(client, place):
    _bulk(client, place, "Masala Dosa")

    body = _bulk(client, place, "masala dosa").json()

    assert body["added"] == []
    assert body["skipped"] == ["masala dosa"]


def test_a_paste_of_only_duplicates_is_not_an_error(client, place):
    _bulk(client, place, "Masala Dosa")

    response = _bulk(client, place, "Masala Dosa")

    assert response.status_code == 201
    assert response.json()["added"] == []


def test_the_same_dish_name_on_two_places_is_fine(client, session_factory):
    with session_factory() as db:
        other = models.Restaurant(
            name="Second Cafe",
            source="test",
            source_id="menu-2",
            latitude=12.98,
            longitude=77.56,
        )
        db.add(other)
        db.commit()
        db.refresh(other)
        other_id = other.id

    # The unique constraint is per place, so a shared dish name is not a clash.
    _bulk(client, place, "Masala Dosa")
    response = _bulk(client, other_id, "Masala Dosa")

    assert response.status_code == 201
    assert len(response.json()["added"]) == 1


# ---------- limits and permissions ----------


def test_an_absurdly_long_paste_is_refused(client, place):
    response = _bulk(client, place, "\n".join(f"Dish {i}" for i in range(500)))

    assert response.status_code == 422
    assert "limit" in response.json()["detail"].lower()


def test_bulk_entry_needs_a_signed_in_reader(anon_client, place):
    assert _bulk(anon_client, place, "Masala Dosa").status_code == 401


def test_bulk_entry_is_rate_limited(client, place):
    statuses = [
        _bulk(client, place, f"Dish {index}").status_code for index in range(30)
    ]
    assert 429 in statuses, "bulk entry must not be a free write amplifier"


def test_bulk_entry_needs_a_real_place(client):
    assert _bulk(client, 999999, "Masala Dosa").status_code == 404


# ---------- contributor credit ----------


def test_a_dish_records_who_added_it(client, place, session_factory):
    body = _bulk(client, place, "Masala Dosa").json()
    dish_id = body["added"][0]["id"]

    with session_factory() as db:
        row = db.get(models.Dish, dish_id)
        assert row.added_by_user_id is not None
        assert row.added_by.email == "asha@example.com"


def test_the_contributor_is_reported_on_read(client, place):
    _bulk(client, place, "Masala Dosa")

    dish = client.get(f"/restaurants/{place}/dishes").json()[0]

    assert dish["added_by"]["name"] == "Asha"
    assert dish["added_by"]["is_critic_verified"] is False


def test_a_single_dish_add_credits_the_contributor_too(client, place):
    dish = _add_dish(client, place, "Idli").json()

    assert dish["added_by"]["name"] == "Asha"


def test_a_dish_survives_the_contributor_leaving(client, place, session_factory):
    """Deleting an account must not delete a menu other readers now rely on."""

    dish_id = _bulk(client, place, "Masala Dosa").json()["added"][0]["id"]
    user_id = client.get("/auth/me").json()["id"]

    with session_factory() as db:
        db.delete(db.get(models.User, user_id))
        db.commit()

    dishes = client.get(f"/restaurants/{place}/dishes").json()
    assert [dish["id"] for dish in dishes] == [dish_id]
    # Unattributed rather than attributed to nobody in particular.
    assert dishes[0]["added_by"] is None


def test_adding_a_menu_makes_the_freshness_claim_stale(client, place, session_factory):
    _bulk(client, place, "Masala Dosa")
    client.post(
        f"/restaurants/{place}/confirm-menu",
        headers={
            "Authorization": f"Bearer {client.get('/auth/me').json().get('x', '') or ''}"
        },
    )

    _bulk(client, place, "Idli, veg")

    with session_factory() as db:
        restaurant = db.get(models.Restaurant, place)
        # A menu that just changed is not "freshly confirmed".
        assert restaurant.menu_last_confirmed is None


def test_bulk_entry_credits_a_verified_critic(client, place, session_factory):
    from conftest import TEST_EMAIL

    with session_factory() as db:
        db.query(models.User).filter_by(
            email=TEST_EMAIL
        ).one().is_critic_verified = True
        db.commit()

    dish = _bulk(client, place, "Masala Dosa").json()["added"][0]
    assert dish["added_by"]["is_critic_verified"] is True
