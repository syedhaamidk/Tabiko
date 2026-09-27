"""Rebuild the city, reproducibly.

    python -m scripts.build_city                 # replay the committed snapshot
    python -m scripts.build_city --verify        # rebuild and diff against live
    python -m scripts.build_city --refresh       # fetch current OSM, rewrite the pin

The default is a replay, not a fetch. That is the whole point: `replay` is a pure
function of the repository, so a fresh clone can build the same 7,728 places
with no network, no API key, and no Overpass rate limit. The three public
endpoints all returned 504 while this was being written, which is what a build
that depends on them looks like from the inside.

`--verify` is the honest check on all of this. It builds into a scratch database
and reports what differs from the live one -- places added since the snapshot,
places gone, places whose attributes changed. It is how you find out whether the
snapshot still matches reality without destroying the database you are running.

`--refresh` is the only mode that touches the network, and it is the only one
that can fail. When it does, the committed snapshot is untouched and the next
default build still works.

Why a committed payload rather than a pinned Overpass date: the public
instances keep no history. A `[date:"..."]` query a year old returns nothing,
which is indistinguishable from a working query over an empty area, so a date
pin would be an unverifiable claim. See `app.ingestion.snapshot`.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.ingestion import snapshot as snap
from app.ingestion.overpass_ingest import (
    OVERPASS_URL,
    fetch_bbox_tiled,
)

# The bounding box that produced the committed city. Every one of the 7,728 rows
# in the live database falls inside it, and it is the value the importer's own
# --help suggests, so it is the one the data actually came from.
#
# South-west to north-east: 12.75,77.45 -> 13.15,77.80.
CITY_BBOX: tuple[float, float, float, float] = (12.75, 77.45, 13.15, 77.80)

SNAPSHOT_PATH = BACKEND / "data" / "osm_snapshot.json.gz"
PROVENANCE_PATH = BACKEND / "data" / "city_provenance.json"
DEFAULT_DATABASE = BACKEND / "tabiko.db"

# How old the snapshot may get before preflight complains. A year is long
# enough that nobody has to babysit it and short enough that "the data is from
# last year" cannot slip through unnoticed.
STALE_AFTER_DAYS = 365


def log(message: str) -> None:
    print(message, flush=True)


# ---------- provenance ----------


def write_provenance(
    *,
    metadata: dict,
    imported: int,
    database: Path,
    verified_against: Path | None = None,
    diff: dict | None = None,
) -> dict:
    """Record what the city is and where it came from.

    Committed, deliberately. It is a few hundred bytes, it is the only thing
    that answers "how old is this data and what produced it", and it is what
    lets a reviewer check a claim instead of taking it on trust.
    """

    record = {
        "schema": 1,
        "city": "Bengaluru",
        "bbox": list(CITY_BBOX),
        "source": "OpenStreetMap via Overpass API",
        "snapshot_digest": metadata.get("digest"),
        "snapshot_fetched_at": metadata.get("fetched_at"),
        "snapshot_element_count": metadata.get("element_count"),
        "overpass_endpoint": metadata.get("endpoint") or OVERPASS_URL,
        "places_imported": imported,
        "database": database.name,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    if verified_against is not None:
        record["verified_against"] = verified_against.name
    if diff is not None:
        record["verification"] = diff

    PROVENANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROVENANCE_PATH.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return record


def read_provenance() -> dict | None:
    if not PROVENANCE_PATH.is_file():
        return None
    try:
        return json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


# ---------- diffing ----------


def _rows(database: Path) -> dict[str, tuple]:
    """Every place as a comparable tuple, keyed by its OSM id."""

    if not database.is_file():
        return {}
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        cursor = connection.execute(
            "select source_id, name, latitude, longitude, cuisine_tags, type_tag,"
            " dietary_flags, good_for, accessibility_flags, address"
            " from restaurants where source = 'overpass'"
        )
        return {
            row[0]: tuple(
                round(value, 6) if isinstance(value, float) else value
                for value in row[1:]
            )
            for row in cursor
        }
    finally:
        connection.close()


def diff_databases(fresh: Path, live: Path) -> dict:
    """Compare two databases on identity and on attributes.

    Reported separately because they mean different things. A place that is new
    or gone means OSM changed. A place whose cuisine or flags changed means this
    project's derivation logic changed, or the snapshot and the live database
    were built by different versions of it. Conflating the two makes both
    unreadable.
    """

    new_rows = _rows(fresh)
    live_rows = _rows(live)

    new_ids = set(new_rows) - set(live_rows)
    gone_ids = set(live_rows) - set(new_rows)
    shared = set(new_rows) & set(live_rows)
    changed = sorted(
        source_id for source_id in shared if new_rows[source_id] != live_rows[source_id]
    )

    return {
        "rebuilt_places": len(new_rows),
        "live_places": len(live_rows),
        "new_since_snapshot": len(new_ids),
        "gone_since_snapshot": len(gone_ids),
        "attributes_changed": len(changed),
        "identical": len(shared) - len(changed),
        "examples_new": sorted(new_ids)[:5],
        "examples_changed": changed[:5],
    }


# ---------- build ----------


def rebuild(database: Path, elements: list[dict], *, replace: bool) -> int:
    """Import elements into `database` from scratch, returning the row count.

    Builds its own engine and session rather than using `app.database`'s, so the
    target is whatever was asked for. `upsert_restaurant` takes the session as an
    argument and never reaches for a global, so nothing here has to be patched.
    """

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base
    from app.ingestion.overpass_ingest import upsert_restaurant

    if replace:
        for path in (
            database,
            *(database.with_name(database.name + s) for s in ("-wal", "-shm")),
        ):
            path.unlink(missing_ok=True)
        log(f"  removed any existing {database.name}")

    database.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{database.as_posix()}", future=True)
    try:
        Base.metadata.create_all(bind=engine)
        session = sessionmaker(bind=engine, future=True)()
        try:
            count = 0
            for element in elements:
                # upsert_restaurant already rejects anything without a name,
                # coordinates and an OSM id, so it is the only gate needed.
                if upsert_restaurant(session, element):
                    count += 1
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    finally:
        engine.dispose()

    return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch current data from Overpass and rewrite the snapshot. The only mode that uses the network.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Build into a scratch database and report how it differs from the live one, changing nothing.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help="The live database to build into or compare against.",
    )
    parser.add_argument(
        "--tiles",
        type=int,
        default=16,
        help="Grid size for --refresh. 16 means 4x4 small queries, which is far more reliable than one city-wide query.",
    )
    parser.add_argument("--url", help="Use only this Overpass endpoint.")

    args = parser.parse_args()

    if args.tiles < 1:
        parser.error("--tiles must be at least 1")
    side = int(args.tiles**0.5 + 0.5)
    rows = columns = max(1, side)

    log(f"City bbox: {CITY_BBOX}")

    # ---------- verify: never touches the live database ----------
    if args.verify:
        if not SNAPSHOT_PATH.is_file():
            log(f"No snapshot at {SNAPSHOT_PATH}. Run with --refresh first.")
            return 1
        log(f"Replaying {SNAPSHOT_PATH.name}...")
        elements, metadata = snap.read_snapshot(SNAPSHOT_PATH)
        log(f"  {len(elements)} elements, digest {metadata.get('digest')}")

        scratch = BACKEND / "data" / "verify_scratch.db"
        log(f"Building into {scratch.name}...")
        imported = rebuild(scratch, elements, replace=True)
        log(f"  imported {imported} places")

        log(f"Comparing against {args.database.name}...")
        report = diff_databases(scratch, args.database)

        log("")
        log("Verification")
        log("------------")
        log(f"  places in the rebuild : {report['rebuilt_places']}")
        log(f"  places live           : {report['live_places']}")
        log(f"  identical             : {report['identical']}")
        log(f"  new since snapshot    : {report['new_since_snapshot']}")
        log(f"  gone since snapshot   : {report['gone_since_snapshot']}")
        log(f"  attributes changed    : {report['attributes_changed']}")
        if report["examples_new"]:
            log(f"  e.g. new: {', '.join(report['examples_new'])}")
        if report["examples_changed"]:
            log(f"  e.g. changed: {', '.join(report['examples_changed'])}")

        write_provenance(
            metadata=metadata,
            imported=imported,
            database=args.database,
            verified_against=args.database,
            diff=report,
        )
        log(f"\nWrote {PROVENANCE_PATH.relative_to(BACKEND)}")

        scratch.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            scratch.with_name(scratch.name + suffix).unlink(missing_ok=True)
        return 0

    # ---------- refresh: the only mode that uses the network ----------
    if args.refresh:
        side_label = f"{rows}x{columns}"
        log(f"Fetching {side_label} tiles from Overpass. This can take a while.")
        log("If this fails, the committed snapshot is untouched and still usable.")

        def progress(index: int, total: int, count: int) -> None:
            log(f"  tile {index}/{total}, {count} places so far")

        try:
            elements = fetch_bbox_tiled(
                CITY_BBOX,
                rows=rows,
                columns=columns,
                urls=[args.url] if args.url else None,
                on_tile=progress,
            )
        except Exception as exc:  # noqa: BLE001 - top-level CLI guard
            # Deliberately broad. A refresh is the one mode that touches the
            # network, and the point of catching everything here is that no
            # failure mode may leave the command looking like it saved a
            # snapshot. The committed payload is only rewritten on the line
            # below, so a failure at any point leaves it exactly as it was.
            log(f"Fetch failed: {type(exc).__name__}: {exc}")
            log("The committed snapshot has not been touched.")
            return 1

        envelope = snap.build_envelope(
            elements,
            bbox=CITY_BBOX,
            endpoint=args.url or OVERPASS_URL,
            note=f"{side_label} tiles over the Bengaluru bbox",
        )
        snap.write_snapshot(SNAPSHOT_PATH, envelope)
        log(
            f"Wrote {SNAPSHOT_PATH.relative_to(BACKEND)}: "
            f"{len(elements)} elements, {envelope['digest']}"
        )
        log("Now run without --refresh to build from it.")

    # ---------- default: replay ----------
    if not SNAPSHOT_PATH.is_file():
        log(f"No snapshot at {SNAPSHOT_PATH}.")
        log("Run `python -m scripts.build_city --refresh` once to create one.")
        return 1

    log(f"Replaying {SNAPSHOT_PATH.name}...")
    elements, metadata = snap.read_snapshot(SNAPSHOT_PATH)
    age = snap.snapshot_age_days(metadata)
    log(f"  {len(elements)} elements")
    log(f"  digest  {metadata.get('digest')}")
    log(
        f"  fetched {metadata.get('fetched_at')}"
        + (f" ({age:.0f} days ago)" if age is not None else "")
    )
    if age is not None and age > STALE_AFTER_DAYS:
        log(
            f"  WARNING: older than {STALE_AFTER_DAYS} days. Run --refresh when convenient."
        )

    log(f"Building into {args.database.name}...")
    imported = rebuild(args.database, elements, replace=True)
    log(f"  imported {imported} places")

    write_provenance(metadata=metadata, imported=imported, database=args.database)
    log(f"Wrote {PROVENANCE_PATH.relative_to(BACKEND)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
