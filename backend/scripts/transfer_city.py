"""Copy the city from a SQLite file into PostgreSQL.

    python -m scripts.transfer_city --target postgresql+psycopg://user:pw@host:5432/db
    python -m scripts.transfer_city --source /path/to/tabiko.db --target ...

Why this exists
--------------
`build_city` replays the OSM snapshot into a SQLite *file* and refuses anything
else. That is correct for local development and the container, and it is also
why a hosted deployment with a real Postgres database cannot be seeded by it.
Rather than teaching the importer about a second database, this copies rows
from a database the importer already built into one Postgres already migrated.

The shape of the operation, in order:

1.  Refuse unless the target is PostgreSQL. Copying SQLite to SQLite is
    `cp`, not a script.
2.  Refuse unless the target's `restaurants` table is empty. Copying into a
    database that already has a city would double every place. There is no
    `--force`: wiping a database is a decision, not a flag.
3.  Run `alembic upgrade head` against the target first, so the schema is the
    migrations' business and never this script's. (This is the same helper
    `build_city` uses, for the same reason.)
4.  Copy table by table in foreign-key order, skipping `alembic_version` (the
    migration record belongs to the target, not the source) and `rate_limits`
    (ephemeral per-minute counters; yesterday's windows are garbage, not data).
5.  Count every table on both sides and fail loudly on any mismatch.

Types cross the boundary without conversion code because both sides go through
SQLAlchemy: SQLite hands back `datetime` objects and enum members, and the
Postgres dialect serialises them. `str`-valued enums land in native Postgres
enum types, which is what migrations 0002/0003 create there.

One known asymmetry, stated rather than hidden: `alembic check` reports a
single benign diff on PostgreSQL (a unique *index* on `users.email` versus a
unique *constraint*). Both enforce the same thing; the check runs against
SQLite in CI, where the two render identically.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = BACKEND / "tabiko.db"

# Foreign-key order. `rate_limits` is deliberately absent (see module docstring),
# and so is `alembic_version`, which belongs to the target.
TABLE_ORDER = (
    "restaurants",
    "users",
    "dishes",
    "reviews",
    "favorites",
    "refresh_tokens",
    "follows",
)

CHUNK_SIZE = 500


def log(message: str) -> None:
    print(message, flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    import os

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="SQLite file holding the built city (default: backend/tabiko.db)",
    )
    parser.add_argument(
        "--target",
        default=os.getenv("TABIKO_DATABASE_URL", ""),
        help="PostgreSQL URL (or set TABIKO_DATABASE_URL)",
    )
    return parser.parse_args(argv)


def table_names(engine) -> set[str]:
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            query = "select tablename from pg_tables where schemaname = 'public'"
        else:
            query = "select name from sqlite_master where type = 'table'"
        return {row[0] for row in connection.execute(text(query))}


def row_count(engine, table: str) -> int:
    with engine.connect() as connection:
        return connection.execute(text(f"select count(*) from {table}")).scalar_one()


def copy_table(source_engine, target_engine, table: str) -> int:
    """Copy every row of one table, in chunks, returning the row count."""

    from sqlalchemy import MetaData, Table

    source_table = Table(table, MetaData(), autoload_with=source_engine)
    target_table = Table(table, MetaData(), autoload_with=target_engine)
    columns = [column.name for column in source_table.columns]

    total = 0
    with source_engine.connect() as reader:
        result = reader.execute(
            source_table.select().order_by(*source_table.primary_key.columns.values())
        )
        while True:
            batch = result.fetchmany(CHUNK_SIZE)
            if not batch:
                break
            rows = [dict(zip(columns, row, strict=True)) for row in batch]
            with target_engine.begin() as writer:
                writer.execute(target_table.insert(), rows)
            total += len(rows)
    return total


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.target.startswith("postgresql"):
        log("error: --target must be a PostgreSQL URL.")
        log("Copying SQLite to SQLite is `cp`, not a script.")
        return 2
    if not args.source.is_file():
        log(f"error: no SQLite file at {args.source}.")
        log("Build one first: python -m scripts.build_city")
        return 2

    source_url = f"sqlite:///{args.source.as_posix()}"
    source_engine = create_engine(source_url, future=True)
    target_engine = create_engine(args.target, future=True)

    try:
        from scripts.build_city import migrate as migrate_target

        log("migrating the target to head...")
        migrate_target(args.target)

        present = table_names(target_engine)
        missing = [table for table in TABLE_ORDER if table not in present]
        if missing:
            log(f"error: target is missing tables after migration: {missing}")
            return 1

        existing = row_count(target_engine, "restaurants")
        if existing:
            log(
                f"error: target already holds {existing} restaurants. "
                "Copying into it would double every place. Empty the "
                "database first if that is really what you want."
            )
            return 3

        # The source of truth for what should arrive: skip tables that do not
        # exist there rather than failing, so a database from an older revision
        # still transfers what it has.
        source_tables = table_names(source_engine)
        counts: dict[str, int] = {}
        for table in TABLE_ORDER:
            if table not in source_tables:
                log(f"  {table}: absent in source, skipped")
                continue
            moved = copy_table(source_engine, target_engine, table)
            counts[table] = moved
            log(f"  {table}: {moved} rows")

        log("verifying...")
        problems: list[str] = []
        for table, moved in counts.items():
            actual = row_count(target_engine, table)
            if actual != moved:
                problems.append(f"{table}: copied {moved} but target holds {actual}")
        if problems:
            log("MISMATCH — the transfer did not land cleanly:")
            for problem in problems:
                log(f"  - {problem}")
            return 1

        total = sum(counts.values())
        log(f"done: {total} rows across {len(counts)} tables, all verified.")
        return 0
    finally:
        source_engine.dispose()
        target_engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
