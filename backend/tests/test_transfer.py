"""Seeding PostgreSQL: migration, transfer, and the boot-time check.

`build_city` replays the snapshot into a SQLite file and refuses anything
else, so a hosted Postgres database is seeded by `transfer_city` instead:
migrate the target, copy every row, verify the counts. This file proves that
path rather than describing it.

Most tests here need a live server. They look for one at `TABIKO_TEST_PG_URL`
and skip without it, so a developer without Postgres still gets a green suite
and CI — which provisions one — exercises the real thing. The refusal paths
need no server and always run.
"""

import os

import pytest
from sqlalchemy import create_engine, text

from scripts import transfer_city
from scripts.build_city import _if_empty_remote


def _reachable(url: str) -> bool:
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 3}, future=True)
        with engine.connect() as connection:
            connection.execute(text("select 1"))
        engine.dispose()
        return True
    except Exception:  # noqa: BLE001 - any failure means "no server", which is the skip path
        return False


@pytest.fixture
def pg_url():
    """A live PostgreSQL, or a skip.

    Defaults to the conventional local test location, which will not exist by
    accident: connecting to a database that was never created fails fast and
    skips, rather than touching anything real.
    """

    url = os.getenv(
        "TABIKO_TEST_PG_URL",
        "postgresql+psycopg://tabiko:tabiko-test-2026@127.0.0.1:5432/tabiko_test",
    )
    if not _reachable(url):
        pytest.skip("no PostgreSQL reachable; set TABIKO_TEST_PG_URL to run this")
    return url


@pytest.fixture
def migrated_pg(pg_url):
    """A freshly migrated, empty Postgres database.

    Dropped first so tests never inherit each other's rows, migrated through
    the real `alembic upgrade head` rather than `create_all` — the point is to
    prove the migrations themselves work on PostgreSQL, which is exactly what
    failed the first time this ran (native enum types and batch recreates are
    SQLite-shaped assumptions).
    """

    engine = create_engine(pg_url, future=True)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()

    from scripts.build_city import migrate

    migrate(pg_url)
    return pg_url


@pytest.fixture
def tiny_city(tmp_path):
    """A few rows of every kind, in a SQLite file.

    Small on purpose: this is about crossing the dialect boundary (enums,
    datetimes, foreign keys), not about volume. The full 7,683-place transfer
    was verified by hand against a scratch server, not in the suite.
    """

    from datetime import datetime, timezone

    from app.models import (
        Base,
        Dish,
        Favorite,
        Follow,
        RefreshToken,
        Restaurant,
        RestaurantType,
        Review,
        User,
    )

    path = tmp_path / "tiny.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}", future=True)
    Base.metadata.create_all(bind=engine)

    from sqlalchemy.orm import sessionmaker

    session = sessionmaker(bind=engine, future=True)()
    try:
        places = [
            Restaurant(
                name="Campus Cafe",
                source="manual",
                source_id="tiny-1",
                latitude=13.0,
                longitude=77.5,
                type_tag=RestaurantType.cafe,
            ),
            Restaurant(
                name="Night Mess",
                source="manual",
                source_id="tiny-2",
                latitude=13.1,
                longitude=77.6,
                type_tag=RestaurantType.family_restaurant,
                good_for="late_night",
                dietary_flags="veg",
            ),
            Restaurant(
                name="Quiet Corner",
                source="manual",
                source_id="tiny-3",
                latitude=13.2,
                longitude=77.7,
                type_tag=RestaurantType.unclassified,
            ),
        ]
        asha = User(name="Asha", email="asha@example.com", password_hash="x")
        bala = User(
            name="Bala",
            email="bala@example.com",
            password_hash="x",
            reviewer_type="food_critic",
            is_critic_verified=True,
        )
        session.add_all([*places, asha, bala])
        session.flush()

        dosa = Dish(
            restaurant_id=places[0].id, name="Ghee Roast", added_by_user_id=asha.id
        )
        coffee = Dish(restaurant_id=places[0].id, name="Filter Coffee")
        session.add_all([dosa, coffee])
        session.flush()

        session.add(
            Review(
                user_id=asha.id,
                restaurant_id=places[0].id,
                dish_id=dosa.id,
                rating=5,
                text="Worth the walk.",
                verification_tier="unverified",
                fraud_flag=False,
                created_at=datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc),
            )
        )
        session.add(Favorite(user_id=asha.id, restaurant_id=places[1].id))
        session.add(Follow(follower_id=asha.id, followed_id=bala.id))
        session.add(
            RefreshToken(
                user_id=asha.id,
                token_hash="digest-for-test",
                expires_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()
    finally:
        session.close()
        engine.dispose()
    return path


def _row(engine, table: str) -> list:
    from sqlalchemy import MetaData, Table

    reflected = Table(table, MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        return connection.execute(reflected.select()).all()


# ---------- refusal paths: no server needed ----------


def test_bare_postgres_scheme_names_the_project_driver():
    """Dashboards hand out `postgresql://` with no driver, which SQLAlchemy
    reads as psycopg2 — a driver this project does not install. Accept the
    dashboard's form rather than failing on ModuleNotFoundError."""

    from app.database import normalize_url

    assert (
        normalize_url("postgresql://u:p@host:5432/db")
        == "postgresql+psycopg://u:p@host:5432/db"
    )


def test_an_explicit_driver_is_never_overridden():
    from app.database import normalize_url

    url = "postgresql+psycopg://u:p@host:5432/db"
    assert normalize_url(url) == url
    assert normalize_url("sqlite:///tabiko.db") == "sqlite:///tabiko.db"


def test_refuses_a_non_postgres_target(tmp_path):
    assert (
        transfer_city.main(
            ["--source", str(tmp_path / "tiny.db"), "--target", "sqlite:///whatever"]
        )
        == 2
    )


def test_refuses_a_missing_source(tmp_path):
    assert (
        transfer_city.main(
            [
                "--source",
                str(tmp_path / "never-built.db"),
                "--target",
                "postgresql+psycopg://u:p@host:5432/db",
            ]
        )
        == 2
    )


def test_if_empty_refuses_an_unreachable_database():
    assert _if_empty_remote("postgresql+psycopg://u:p@127.0.0.1:59999/gone") == 1


# ---------- live paths ----------


def test_transfers_a_tiny_city_end_to_end(migrated_pg, tiny_city):
    source = f"sqlite:///{tiny_city.as_posix()}"

    assert (
        transfer_city.main(["--source", str(tiny_city), "--target", migrated_pg]) == 0
    )

    target = create_engine(migrated_pg, future=True)
    try:
        assert transfer_city.row_count(target, "restaurants") == 3
        assert transfer_city.row_count(target, "users") == 2
        assert transfer_city.row_count(target, "dishes") == 2
        assert transfer_city.row_count(target, "reviews") == 1
        assert transfer_city.row_count(target, "favorites") == 1
        assert transfer_city.row_count(target, "follows") == 1
        assert transfer_city.row_count(target, "refresh_tokens") == 1

        # Enums crossed as values, not as opaque strings: the critic is still
        # a critic and the cafe is still a cafe.
        users = {row.email: row for row in _row(target, "users")}
        assert users["bala@example.com"].reviewer_type == "food_critic"
        assert users["bala@example.com"].is_critic_verified is True
        places = {row.source_id: row for row in _row(target, "restaurants")}
        assert places["tiny-1"].type_tag == "cafe"
        assert places["tiny-2"].good_for == "late_night"

        # The contributor link survived the crossing.
        dishes = {row.name: row for row in _row(target, "dishes")}
        assert dishes["Ghee Roast"].added_by_user_id == users["asha@example.com"].id

        # The source file is untouched: this is a copy, not a move.
        source_engine = create_engine(source, future=True)
        try:
            assert transfer_city.row_count(source_engine, "restaurants") == 3
        finally:
            source_engine.dispose()
    finally:
        target.dispose()


def test_refuses_a_populated_target(migrated_pg, tiny_city):
    first = transfer_city.main(["--source", str(tiny_city), "--target", migrated_pg])
    assert first == 0

    # Copying again would double every place, so the second run must refuse
    # rather than oblige.
    assert (
        transfer_city.main(["--source", str(tiny_city), "--target", migrated_pg]) == 3
    )

    target = create_engine(migrated_pg, future=True)
    try:
        assert transfer_city.row_count(target, "restaurants") == 3
    finally:
        target.dispose()


def test_if_empty_leaves_a_seeded_database_alone(migrated_pg, tiny_city):
    assert (
        transfer_city.main(["--source", str(tiny_city), "--target", migrated_pg]) == 0
    )
    assert _if_empty_remote(migrated_pg) == 0


def test_if_empty_refuses_an_empty_database(migrated_pg):
    assert _if_empty_remote(migrated_pg) == 1
