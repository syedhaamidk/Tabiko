"""Building the city, and proving the build is reproducible.

The point of the snapshot is that `python -m scripts.build_city` is a pure
function of the repository. These tests exist because that claim is worthless if
it is only ever asserted: a snapshot that cannot be re-read, a digest that
ignores its own contents, and a diff that conflates "OSM changed" with "this
project's derivation changed" would all pass a casual test while quietly
destroying the one property the whole design exists to provide.
"""

import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.ingestion import snapshot as snap
from app.ingestion.overpass_ingest import build_bbox_query, tile_bbox
from scripts import build_city


def element(element_id, name="Corner Cafe", lat=12.99, lon=77.55, **tags):
    payload = {"amenity": "restaurant"}
    if name:
        payload["name"] = name
    payload.update(tags)
    return {
        "type": "node",
        "id": element_id,
        "lat": lat,
        "lon": lon,
        "tags": payload,
    }


# ---------- the digest ----------


def test_the_digest_identifies_the_set_of_places():
    a = [element(1), element(2)]
    b = [element(2), element(1)]

    # Order is an artefact of the query, not of the data.
    assert snap.digest_elements(a) == snap.digest_elements(b)


def test_the_digest_ignores_how_a_place_is_described():
    """Tags and coordinates get edited; that is not a different snapshot.

    If the digest covered everything, every OSM correction would look like a
    different city and `--verify` could never tell drift from noise.
    """

    before = [element(1, name="Corner Cafe", cuisine="chinese")]
    after = [element(1, name="Corner Cafe Renamed", cuisine="indian")]

    assert snap.digest_elements(before) == snap.digest_elements(after)


def test_a_different_place_set_is_a_different_digest():
    assert snap.digest_elements([element(1)]) != snap.digest_elements(
        [element(1), element(2)]
    )


def test_the_digest_separates_types_with_the_same_id():
    """OSM node 1 and way 1 are different objects, not the same one."""

    nodes = [{"type": "node", "id": 1, "tags": {}}]
    ways = [{"type": "way", "id": 1, "tags": {}}]

    assert snap.digest_elements(nodes) != snap.digest_elements(ways)


# ---------- round trip ----------


def test_a_snapshot_survives_a_round_trip(tmp_path):
    elements = [element(1), element(2, name="Filter Coffee", lat=12.98, lon=77.56)]
    path = tmp_path / "snap.json.gz"

    snap.write_snapshot(
        path, snap.build_envelope(elements, bbox=(12.75, 77.45, 13.15, 77.8))
    )
    loaded, metadata = snap.read_snapshot(path)

    assert loaded == elements
    assert metadata["element_count"] == 2
    assert metadata["bbox"] == [12.75, 77.45, 13.15, 77.8]
    assert metadata["digest"] == snap.digest_elements(elements)


def test_elements_are_not_in_the_returned_metadata(tmp_path):
    """Otherwise a caller logging the metadata dumps the whole payload."""

    path = tmp_path / "snap.json.gz"
    snap.write_snapshot(path, snap.build_envelope([element(1)]))

    _, metadata = snap.read_snapshot(path)

    assert "elements" not in metadata


def test_rewriting_an_unchanged_snapshot_produces_identical_bytes(tmp_path):
    """Otherwise every build churns the repository for no reason."""

    elements = [element(1), element(2)]
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = tmp_path / "a.json.gz"
    second = tmp_path / "b.json.gz"

    snap.write_snapshot(
        first, snap.build_envelope(elements, fetched_at=when, bbox=(1.0, 2.0, 3.0, 4.0))
    )
    snap.write_snapshot(
        second,
        snap.build_envelope(elements, fetched_at=when, bbox=(1.0, 2.0, 3.0, 4.0)),
    )

    assert first.read_bytes() == second.read_bytes()


def test_a_corrupt_snapshot_is_refused(tmp_path):
    """Importing it would build a city that disagrees with its own record."""

    path = tmp_path / "snap.json.gz"
    envelope = snap.build_envelope([element(1), element(2)])
    envelope["digest"] = "sha256:" + "0" * 64
    with gzip.open(path, "wb") as gz:
        gz.write(json.dumps(envelope).encode())

    with pytest.raises(ValueError, match="corrupt"):
        snap.read_snapshot(path)


def test_a_truncated_snapshot_is_refused(tmp_path):
    path = tmp_path / "snap.json.gz"
    with gzip.open(path, "wb") as gz:
        gz.write(
            json.dumps({"schema": snap.SNAPSHOT_SCHEMA, "elements": []}).encode()[:20]
        )

    # A truncated gzip fails in the gzip layer rather than the envelope checks,
    # so which error surfaces depends on where the cut lands.
    with pytest.raises((OSError, ValueError, EOFError)):
        snap.read_snapshot(path)


def test_an_unknown_schema_is_refused_rather_than_misread(tmp_path):
    path = tmp_path / "snap.json.gz"
    envelope = snap.build_envelope([element(1)])
    envelope["schema"] = 99
    with gzip.open(path, "wb") as gz:
        gz.write(json.dumps(envelope).encode())

    with pytest.raises(ValueError, match="schema"):
        snap.read_snapshot(path)


def test_a_snapshot_with_no_elements_list_is_refused(tmp_path):
    path = tmp_path / "snap.json.gz"
    with gzip.open(path, "wb") as gz:
        gz.write(
            json.dumps({"schema": snap.SNAPSHOT_SCHEMA, "elements": "nope"}).encode()
        )

    with pytest.raises(ValueError, match="elements"):
        snap.read_snapshot(path)


# ---------- age ----------


def test_age_is_measured_in_days():
    when = datetime.now(timezone.utc) - timedelta(days=10)

    metadata = {"fetched_at": when.isoformat()}

    assert 9.9 < snap.snapshot_age_days(metadata) < 10.1


def test_an_unparseable_timestamp_yields_no_age():
    """A wrong answer here would be worse than admitting ignorance."""

    assert snap.snapshot_age_days({"fetched_at": "not a date"}) is None
    assert snap.snapshot_age_days({}) is None


def test_a_naive_timestamp_is_read_as_utc():
    when = datetime.now(timezone.utc) - timedelta(days=3)

    metadata = {"fetched_at": when.replace(tzinfo=None).isoformat()}

    assert 2.9 < snap.snapshot_age_days(metadata) < 3.1


# ---------- tiling ----------


def test_tiles_cover_the_whole_bbox_with_no_gaps():
    """A missing strip is an invisible hole in the city."""

    bbox = (12.75, 77.45, 13.15, 77.80)
    tiles = tile_bbox(bbox, 4, 4)

    assert tiles[0][:2] == pytest.approx(bbox[:2])
    assert tiles[-1][2:] == pytest.approx(bbox[2:])

    # Every tile's north edge meets the next row's south edge, and likewise
    # across columns, so the grid tiles the rectangle exactly. Four rows give
    # four south edges plus the bbox's own north edge: five boundaries.
    boundaries_lat = sorted({round(t[0], 9) for t in tiles} | {round(bbox[2], 9)})
    boundaries_lon = sorted({round(t[1], 9) for t in tiles} | {round(bbox[3], 9)})
    assert len(boundaries_lat) == 5
    assert len(boundaries_lon) == 5

    # And no tile is degenerate, which is what a division error would produce.
    for tile in tiles:
        assert tile[2] > tile[0]
        assert tile[3] > tile[1]


def test_a_one_by_one_grid_is_the_bbox_itself():
    assert tile_bbox((12.75, 77.45, 13.15, 77.80), 1, 1) == [
        (12.75, 77.45, 13.15, 77.80)
    ]


def test_a_degenerate_grid_is_rejected():
    with pytest.raises(ValueError):
        tile_bbox((12.75, 77.45, 13.15, 77.80), 0, 4)


def test_tiling_is_only_used_because_one_big_query_times_out():
    """The reason this exists, so nobody simplifies it away.

    A single city-wide Overpass query on a free endpoint is the shape that
    returns 504; all three configured mirrors were observed doing so. Small
    tiles are individually cheap, and one failing tile costs one tile.
    """

    assert len(tile_bbox((12.75, 77.45, 13.15, 77.80), 4, 4)) == 16


def test_the_query_asks_for_nodes_ways_and_relations_with_centres():
    """Ways and relations have no lat/lon of their own, so `out center` is not
    optional: without it every building-mapped venue is silently dropped."""

    query = build_bbox_query(12.75, 77.45, 13.15, 77.80)

    assert "nwr[" in query
    assert "out center;" in query
    assert "amenity=restaurant" in query


# ---------- the diff ----------


def build_database(path: Path, places: list[tuple]) -> Path:
    """A minimal stand-in with the columns the diff reads."""

    import sqlite3

    connection = sqlite3.connect(path)
    connection.execute(
        "create table restaurants (source_id text, source text, name text,"
        " latitude real, longitude real, cuisine_tags text, type_tag text,"
        " dietary_flags text, good_for text, accessibility_flags text, address text)"
    )
    connection.executemany(
        "insert into restaurants values (?, 'overpass', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                f"osm-node-{sid}",
                name,
                lat,
                lon,
                cuisine,
                "cafe",
                None,
                None,
                None,
                None,
            )
            for sid, name, lat, lon, cuisine in places
        ],
    )
    connection.commit()
    connection.close()
    return path


def test_an_identical_database_reports_no_drift(tmp_path):
    places = [(1, "A", 12.99, 77.55, "chinese"), (2, "B", 12.98, 77.56, "indian")]
    fresh = build_database(tmp_path / "fresh.db", places)
    live = build_database(tmp_path / "live.db", places)

    report = build_city.diff_databases(fresh, live)

    assert report["identical"] == 2
    assert report["new_since_snapshot"] == 0
    assert report["gone_since_snapshot"] == 0
    assert report["attributes_changed"] == 0


def test_a_new_place_is_reported_as_new(tmp_path):
    fresh = build_database(tmp_path / "fresh.db", [(1, "A", 12.99, 77.55, "chinese")])
    live = build_database(tmp_path / "live.db", [])

    report = build_city.diff_databases(fresh, live)

    assert report["new_since_snapshot"] == 1
    assert report["examples_new"] == ["osm-node-1"]


def test_a_removed_place_is_reported_as_gone(tmp_path):
    fresh = build_database(tmp_path / "fresh.db", [])
    live = build_database(tmp_path / "live.db", [(1, "A", 12.99, 77.55, "chinese")])

    report = build_city.diff_databases(fresh, live)

    assert report["gone_since_snapshot"] == 1


def test_attribute_drift_is_separated_from_identity_drift(tmp_path):
    """These mean different things and conflating them makes both unreadable.

    A new or gone place means OSM changed. A place whose cuisine or flags
    changed means this project's derivation logic did, or the two databases came
    from different versions of it.
    """

    fresh = build_database(tmp_path / "fresh.db", [(1, "A", 12.99, 77.55, "italian")])
    live = build_database(tmp_path / "live.db", [(1, "A", 12.99, 77.55, "chinese")])

    report = build_city.diff_databases(fresh, live)

    assert report["attributes_changed"] == 1
    assert report["new_since_snapshot"] == 0
    assert report["gone_since_snapshot"] == 0
    assert report["identical"] == 0
    assert report["examples_changed"] == ["osm-node-1"]


def test_a_moved_place_counts_as_changed_not_as_new_and_gone(tmp_path):
    """It is the same place. Reporting it as a delete and an insert would be
    wrong, and would make a coordinate correction look like churn."""

    fresh = build_database(tmp_path / "fresh.db", [(1, "A", 12.991, 77.55, "chinese")])
    live = build_database(tmp_path / "live.db", [(1, "A", 12.990, 77.55, "chinese")])

    report = build_city.diff_databases(fresh, live)

    assert report["new_since_snapshot"] == 0
    assert report["gone_since_snapshot"] == 0
    assert report["attributes_changed"] == 1


def test_a_missing_database_is_an_empty_side_not_a_crash(tmp_path):
    live = build_database(tmp_path / "live.db", [(1, "A", 12.99, 77.55, "chinese")])

    report = build_city.diff_databases(tmp_path / "never-built.db", live)

    assert report["rebuilt_places"] == 0
    assert report["gone_since_snapshot"] == 1


def test_a_renamed_place_counts_as_changed(tmp_path):
    fresh = build_database(
        tmp_path / "fresh.db", [(1, "New Name", 12.99, 77.55, "chinese")]
    )
    live = build_database(
        tmp_path / "live.db", [(1, "Old Name", 12.99, 77.55, "chinese")]
    )

    assert build_city.diff_databases(fresh, live)["attributes_changed"] == 1


# ---------- provenance ----------


def test_provenance_records_where_the_city_came_from(tmp_path, monkeypatch):
    monkeypatch.setattr(
        build_city, "PROVENANCE_PATH", tmp_path / "city_provenance.json"
    )
    metadata = {
        "digest": "sha256:" + "a" * 64,
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "element_count": 100,
    }

    record = build_city.write_provenance(
        metadata=metadata, imported=90, database=tmp_path / "tabiko.db"
    )

    assert record["places_imported"] == 90
    assert record["snapshot_digest"] == metadata["digest"]
    assert record["bbox"] == list(build_city.CITY_BBOX)
    assert "Overpass" in record["source"]


def test_the_pinned_bbox_is_the_one_the_data_came_from():
    """Not a value picked today: the documented bbox, which every existing row
    falls inside. Changing it would silently produce a different city."""

    assert build_city.CITY_BBOX == (12.75, 77.45, 13.15, 77.80)
