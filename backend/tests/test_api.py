from uuid import uuid4

import pytest

from app.models import Dish, Restaurant, Review, User


def test_health_checks_database_and_schema(client):
    liveness = client.get("/health/live")
    readiness = client.get("/health")

    assert liveness.status_code == 200
    assert liveness.json() == {"status": "ok"}
    assert readiness.status_code == 200
    assert readiness.json() == {"status": "ok", "database": "ok"}


def test_health_fails_when_expected_schema_is_missing(client, db_engine):
    Restaurant.__table__.drop(bind=db_engine)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_health_fails_for_read_only_database(client, db_engine):
    with db_engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA query_only=ON")
        connection.commit()
    try:
        response = client.get("/health")
    finally:
        with db_engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA query_only=OFF")
            connection.commit()

    assert response.status_code == 503


def test_register_login_profile_and_me(client):
    credentials = {
        "name": "Ravi Kumar",
        "email": "RAVI@Example.com",
        "password": "password123",
    }
    registered = client.post("/auth/register", json=credentials)
    token = registered.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    me = client.get("/auth/me", headers=auth_headers)
    updated = client.patch(
        "/auth/me",
        headers=auth_headers,
        json={
            "reviewer_type": "cuisine_specialist",
            "cuisine_specialty": "South Indian",
        },
    )
    duplicate = client.post("/auth/register", json=credentials)
    logged_in = client.post(
        "/auth/login",
        json={"email": "ravi@example.com", "password": "password123"},
    )
    bad_login = client.post(
        "/auth/login",
        json={"email": "ravi@example.com", "password": "wrongpassword"},
    )

    assert registered.status_code == 201
    assert me.status_code == 200
    assert me.json()["email"] == "ravi@example.com"
    assert updated.json()["reviewer_type"] == "cuisine_specialist"
    assert updated.json()["cuisine_specialty"] == "South Indian"
    assert duplicate.status_code == 409
    assert logged_in.status_code == 200
    assert bad_login.status_code == 401


def test_authentication_is_required_for_user_writes(anon_client, seeded_data):
    review = anon_client.post(
        "/reviews",
        json={"restaurant_id": seeded_data["restaurant_id"], "rating": 4},
    )
    dish = anon_client.post(
        f"/restaurants/{seeded_data['restaurant_id']}/dishes",
        json={"name": "Anonymous Dish"},
    )

    assert review.status_code == 401
    assert dish.status_code == 401


def test_dish_creation_duplicate_and_missing_parent(client, seeded_data):
    restaurant_id = seeded_data["restaurant_id"]
    payload = {"name": "Masala Dosa", "tags": "veg,bestseller"}

    created = client.post(f"/restaurants/{restaurant_id}/dishes", json=payload)
    duplicate = client.post(f"/restaurants/{restaurant_id}/dishes", json=payload)
    missing_parent = client.post("/restaurants/999999/dishes", json=payload)

    assert created.status_code == 201
    assert created.json()["name"] == "Masala Dosa"
    assert duplicate.status_code == 409
    assert missing_parent.status_code == 404


def test_restaurant_search_theme_filters_and_nested_404s(client, seeded_data):
    restaurant_id = seeded_data["restaurant_id"]

    restaurants = client.get("/restaurants", params={"search": "campus"})
    work = client.get("/restaurants", params={"good_for": "work"})
    date = client.get("/restaurants", params={"good_for": "date"})
    wrong = client.get("/restaurants", params={"good_for": "group"})
    theme = client.get(f"/restaurants/{restaurant_id}/theme")

    assert [item["id"] for item in restaurants.json()] == [restaurant_id]
    assert [item["id"] for item in work.json()] == [restaurant_id]
    assert [item["id"] for item in date.json()] == [restaurant_id]
    assert wrong.json() == []
    assert theme.status_code == 200
    assert theme.json()["theme_id"] == "cafe_bakery"
    assert client.get("/restaurants/999999/dishes").status_code == 404
    assert client.get("/reviews/restaurant/999999").status_code == 404


def test_cuisine_and_dietary_filters_match_complete_tags(client, seeded_data):
    veg = client.get("/restaurants", params={"dietary": "veg"})
    non_veg = client.get("/restaurants", params={"dietary": "non_veg"})
    vegan = client.get("/restaurants", params={"dietary": "vegan"})
    cuisine = client.get("/restaurants", params={"cuisine": "Cafe/Bakery"})
    broad_cuisine = client.get("/restaurants", params={"cuisine": "Indian"})
    wildcard = client.get("/restaurants", params={"dietary": "%"})

    assert [item["id"] for item in veg.json()] == [seeded_data["restaurant_id"]]
    assert [item["id"] for item in non_veg.json()] == [
        seeded_data["other_restaurant_id"]
    ]
    assert [item["id"] for item in vegan.json()] == [seeded_data["other_restaurant_id"]]
    assert [item["id"] for item in cuisine.json()] == [seeded_data["restaurant_id"]]
    assert broad_cuisine.json() == []
    assert wildcard.json() == []


@pytest.mark.parametrize("rating", [0, 5.1, -1])
def test_review_rating_must_be_between_one_and_five(client, seeded_data, rating):
    response = client.post(
        "/reviews",
        json={"restaurant_id": seeded_data["restaurant_id"], "rating": rating},
    )

    assert response.status_code == 422


def test_review_creation_updates_dish_rating(client, session_factory, seeded_data):
    payload = {
        "restaurant_id": seeded_data["restaurant_id"],
        "dish_id": seeded_data["dish_id"],
        "rating": 4.5,
        "text": "Fresh coffee and friendly service.",
    }

    first = client.post("/reviews", json=payload)
    payload["rating"] = 3.5
    second = client.post("/reviews", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["reviewer"]["id"] == seeded_data["user_id"]
    with session_factory() as db:
        dish = db.get(Dish, seeded_data["dish_id"])
        assert dish.review_count == 2
        assert dish.avg_rating == 4.0


def test_duplicate_client_request_id_is_rejected(client, session_factory, seeded_data):
    payload = {
        "restaurant_id": seeded_data["restaurant_id"],
        "dish_id": seeded_data["dish_id"],
        "rating": 4,
        "text": "A sufficiently detailed idempotency review.",
        "client_request_id": str(uuid4()),
    }

    first = client.post("/reviews", json=payload)
    duplicate = client.post("/reviews", json=payload)

    assert first.status_code == 201
    assert first.json()["client_request_id"] == payload["client_request_id"]
    assert duplicate.status_code == 409
    with session_factory() as db:
        assert db.query(Review).count() == 1
        dish = db.get(Dish, seeded_data["dish_id"])
        assert dish.review_count == 1


def test_review_rejects_missing_and_cross_restaurant_dishes(
    client, session_factory, seeded_data
):
    base_payload = {
        "restaurant_id": seeded_data["restaurant_id"],
        "rating": 4,
        "text": "A detailed and useful review.",
    }

    missing_dish = client.post("/reviews", json={**base_payload, "dish_id": 999999})
    cross_restaurant_dish = client.post(
        "/reviews", json={**base_payload, "dish_id": seeded_data["other_dish_id"]}
    )

    assert missing_dish.status_code == 404
    assert cross_restaurant_dish.status_code == 400
    with session_factory() as db:
        assert db.query(Review).count() == 0


def test_checkin_and_claimed_tier_are_server_resolved(client, seeded_data):
    checked_in = client.post(
        "/reviews",
        json={
            "restaurant_id": seeded_data["restaurant_id"],
            "rating": 4,
            "text": "A detailed review posted while physically nearby.",
            "user_lat": 13.1682,
            "user_lon": 77.5354,
        },
    )
    claimed_order = client.post(
        "/reviews",
        json={
            "restaurant_id": seeded_data["restaurant_id"],
            "rating": 4,
            "text": "A detailed review with an unsupported order claim.",
            "claimed_verification_tier": "order_confirmed",
        },
    )

    assert checked_in.status_code == 201
    assert checked_in.json()["verification_tier"] == "checked_in"
    assert claimed_order.status_code == 201
    assert claimed_order.json()["verification_tier"] == "unverified"


def test_hygiene_score_is_derived_from_visible_review_text(client, seeded_data):
    response = client.post(
        "/reviews",
        json={
            "restaurant_id": seeded_data["restaurant_id"],
            "rating": 4,
            "text": "The place was spotless, clean, and the food was fresh.",
        },
    )
    restaurant = client.get(f"/restaurants/{seeded_data['restaurant_id']}")

    assert response.status_code == 201
    assert restaurant.json()["hygiene_score"] == 5.0


def test_short_extreme_review_is_not_auto_flagged(client, seeded_data):
    created = client.post(
        "/reviews",
        json={
            "restaurant_id": seeded_data["restaurant_id"],
            "rating": 5,
            "text": "Great",
        },
    )
    stats = client.get(f"/restaurants/{seeded_data['restaurant_id']}/stats")

    assert created.status_code == 201
    assert created.json()["fraud_flag"] is False
    assert stats.json()["review_count"] == 1
    assert stats.json()["flagged_review_count"] == 0


def test_reviewer_burst_flag_and_stats_contract(client, session_factory, seeded_data):
    payload = {
        "restaurant_id": seeded_data["restaurant_id"],
        "dish_id": seeded_data["dish_id"],
        "rating": 4,
        "text": "A normal detailed review with specific observations.",
    }

    responses = [client.post("/reviews", json=payload) for _ in range(3)]
    visible = client.get(f"/reviews/restaurant/{seeded_data['restaurant_id']}")
    stats = client.get(f"/restaurants/{seeded_data['restaurant_id']}/stats")

    assert [response.json()["fraud_flag"] for response in responses] == [
        False,
        False,
        True,
    ]
    assert len(visible.json()) == 2
    assert stats.json() == {
        "average_rating": 4.0,
        "review_count": 2,
        "submitted_review_count": 3,
        "trusted_review_count": 0,
        "flagged_review_count": 1,
    }
    with session_factory() as db:
        dish = db.get(Dish, seeded_data["dish_id"])
        assert dish.review_count == 2


def test_moderation_requires_admin_and_can_restore_review(
    client, session_factory, seeded_data
):
    payload = {
        "restaurant_id": seeded_data["restaurant_id"],
        "dish_id": seeded_data["dish_id"],
        "rating": 4,
        "text": "A normal detailed review with specific observations.",
    }
    responses = [client.post("/reviews", json=payload) for _ in range(3)]
    flagged_id = responses[-1].json()["id"]
    forbidden = client.patch(
        f"/reviews/{flagged_id}/moderation", json={"fraud_flag": False}
    )

    with session_factory() as db:
        account = db.query(User).filter_by(id=seeded_data["user_id"]).one()
        account.is_admin = True
        db.commit()

    restored = client.patch(
        f"/reviews/{flagged_id}/moderation", json={"fraud_flag": False}
    )
    visible = client.get(f"/reviews/restaurant/{seeded_data['restaurant_id']}")

    assert forbidden.status_code == 403
    assert restored.status_code == 200
    assert restored.json()["fraud_flag"] is False
    assert len(visible.json()) == 3


def test_flagged_queue_is_admin_only(client, session_factory, seeded_data):
    payload = {
        "restaurant_id": seeded_data["restaurant_id"],
        "rating": 4,
        "text": "A normal detailed review with specific observations.",
    }
    for _ in range(3):
        client.post("/reviews", json=payload)

    forbidden = client.get("/reviews/flagged")
    with session_factory() as db:
        account = db.query(User).filter_by(id=seeded_data["user_id"]).one()
        account.is_admin = True
        db.commit()
    allowed = client.get("/reviews/flagged")

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert len(allowed.json()) == 1


def test_craving_search_ranks_matching_restaurants(client, seeded_data):
    client.post(
        f"/restaurants/{seeded_data['restaurant_id']}/dishes",
        json={"name": "Spicy Biryani", "tags": "spicy,comfort"},
    )

    results = client.get("/search/craving", params={"q": "spicy comfort"})
    missing = client.get("/search/craving", params={"q": "sushi ramen"})

    assert results.status_code == 200
    assert results.json()[0]["restaurant"]["id"] == seeded_data["restaurant_id"]
    assert results.json()[0]["relevance"] > 0
    assert missing.json() == []


def test_deleting_dish_preserves_review(session_factory, seeded_data):
    with session_factory() as db:
        review = Review(
            user_id=seeded_data["user_id"],
            restaurant_id=seeded_data["restaurant_id"],
            dish_id=seeded_data["dish_id"],
            rating=4,
            text="A review that should survive menu cleanup.",
        )
        db.add(review)
        db.commit()
        review_id = review.id

        dish = db.get(Dish, seeded_data["dish_id"])
        db.delete(dish)
        db.commit()
        db.expire_all()

        assert db.get(Review, review_id).dish_id is None
