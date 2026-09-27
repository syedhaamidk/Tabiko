from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.database import Base


def test_initial_migration_round_trip(tmp_path, monkeypatch):
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("TABIKO_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    # Compare against the real head so adding a migration does not need a test edit.
    head = ScriptDirectory.from_config(config).get_current_head()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        inspector = inspect(connection)
        # Derived from the models rather than written out, so a new table is a
        # real assertion here and never a test edit that quietly widens the check.
        assert set(inspector.get_table_names()) == {
            *Base.metadata.tables,
            "alembic_version",
        }
        assert "client_request_id" in {
            column["name"] for column in inspector.get_columns("reviews")
        }
        assert "password_hash" in {
            column["name"] for column in inspector.get_columns("users")
        }
        assert "good_for" in {
            column["name"] for column in inspector.get_columns("restaurants")
        }
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            == head
        )
    engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        assert "restaurants" not in inspect(connection).get_table_names()
    engine.dispose()
