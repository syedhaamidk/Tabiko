import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["TABIKO_AUTO_CREATE_SCHEMA"] = "false"
# The app refuses to start on the published dev signing secret unless it is told
# it is running locally, so the suite has to say so. `tests/test_security.py`
# reloads `app.auth` to exercise the refusal itself.
os.environ["TABIKO_ENV"] = "development"

from app import auth
from app.database import Base, get_db
from app.main import app
from app.models import Dish, Restaurant, RestaurantType, User

TEST_EMAIL = "asha@example.com"
TEST_PASSWORD = "password123"


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)


def _ensure_test_user(session_factory) -> User:
    with session_factory() as db:
        user = db.query(User).filter_by(email=TEST_EMAIL).first()
        if user is None:
            user = User(
                name="Asha",
                email=TEST_EMAIL,
                password_hash=auth.hash_password(TEST_PASSWORD),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        db.expunge(user)
        return user


def _install_db_override(db_engine) -> None:
    def override_get_db():
        session = sessionmaker(
            bind=db_engine, autoflush=False, expire_on_commit=False
        )()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
def client(db_engine, session_factory) -> Generator[TestClient, None, None]:
    user = _ensure_test_user(session_factory)
    token = auth.create_access_token(user.id)
    _install_db_override(db_engine)
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def anon_client(db_engine) -> Generator[TestClient, None, None]:
    _install_db_override(db_engine)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def seeded_data(session_factory) -> dict[str, int]:
    user = _ensure_test_user(session_factory)
    with session_factory() as db:
        restaurant = Restaurant(
            name="Campus Cafe",
            source="manual",
            source_id="test-restaurant-1",
            latitude=13.1682,
            longitude=77.5354,
            address="Test Address",
            cuisine_tags="Cafe/Bakery",
            dietary_flags="veg",
            good_for="date, work",
            type_tag=RestaurantType.cafe,
            theme_id="cafe_bakery",
        )
        other_restaurant = Restaurant(
            name="Other Place",
            source="manual",
            source_id="test-restaurant-2",
            latitude=13.17,
            longitude=77.54,
            dietary_flags="non_veg, vegan",
            type_tag=RestaurantType.unclassified,
        )
        db.add_all([restaurant, other_restaurant])
        db.flush()
        dish = Dish(restaurant_id=restaurant.id, name="Filter Coffee")
        other_dish = Dish(restaurant_id=other_restaurant.id, name="Lunch Plate")
        db.add_all([dish, other_dish])
        db.commit()
        return {
            "user_id": user.id,
            "restaurant_id": restaurant.id,
            "dish_id": dish.id,
            "other_restaurant_id": other_restaurant.id,
            "other_dish_id": other_dish.id,
        }
