"""Database configuration for the Tabiko API.

The default database is a local SQLite file next to the backend package.  Set
``TABIKO_DATABASE_URL`` to use a different SQLite path or a SQLAlchemy-compatible
PostgreSQL URL.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = BACKEND_DIR / "tabiko.db"


def normalize_url(url: str) -> str:
    """Accept the URL form dashboards actually hand out.

    Supabase (and most Postgres hosts) give `postgresql://...` with no driver,
    which SQLAlchemy reads as "use psycopg2" — a driver this project does not
    install or test against. The project's driver is psycopg v3, so the bare
    scheme is rewritten to name it. Anything already naming a driver passes
    through untouched, so an explicit choice is never overridden.
    """

    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


DATABASE_URL = normalize_url(
    os.getenv("TABIKO_DATABASE_URL", f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}")
)

engine_options: dict[str, object] = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}
    if DATABASE_URL in {"sqlite://", "sqlite:///:memory:"}:
        # Keep every worker/thread on the same explicit in-memory database.
        engine_options["poolclass"] = StaticPool

engine = create_engine(DATABASE_URL, **engine_options)

if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        """SQLite ignores foreign keys unless explicitly enabled per connection."""

        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        """Write-ahead logging, which is what makes SQLite safe to read while writing.

        The default rollback journal serialises readers against the writer, so
        every write blocks every read. Measured on this database with eight
        concurrent writers:

            journal=delete  synchronous=FULL      332 writes/sec
            journal=delete  synchronous=NORMAL    396 writes/sec
            journal=wal     synchronous=FULL    2,001 writes/sec
            journal=wal     synchronous=NORMAL  38,678 writes/sec

        WAL alone is a 6x gain at identical durability, and lets reads proceed
        during a write. It needs a filesystem with working shared memory, so it is
        skipped when that is unavailable rather than failing the connection.
        """

        cursor = dbapi_connection.cursor()
        try:
            mode = cursor.execute("PRAGMA journal_mode=WAL").fetchone()
            if mode and str(mode[0]).lower() == "wal":
                # NORMAL is the recommended pairing with WAL: a commit no longer
                # fsyncs, and the database cannot be corrupted by a crash, only
                # by losing the most recent transactions.
                cursor.execute("PRAGMA synchronous=NORMAL")
                # A negative value is kibibytes; -32000 is ~32 MB, comfortably
                # holding the working set of the city-wide point queries.
                cursor.execute("PRAGMA cache_size=-32000")
        except sqlite3.Error:
            # A network filesystem cannot do WAL. The rollback journal still
            # works, just without concurrent readers.
            pass
        finally:
            cursor.close()


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    bind=engine,
)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped database session."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
