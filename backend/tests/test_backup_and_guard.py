"""The destructive-rebuild guard, and a backup/restore that has really been run.

The guard exists because `build_city` deletes the database file, and the whole
purpose of the contribution flow is that dishes, reviews and accounts accumulate
in that file. It is the only command in the repository that can throw away a
reader's work, and until this it would do so on a re-import typed without
thinking.

The restore tests are not mocked. They write a database with rows in it, back it
up, change the live database, and restore over the top, then check the rows came
back. A restore script that has only ever been dry-run is a restore script whose
first real use is also its first test.
"""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import backup as backup_module
from scripts import build_city

BACKEND = Path(__file__).resolve().parents[1]


# ---------- the guard ----------


def make_database(path: Path, *, dishes=0, reviews=0, users=0, favorites=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        create table restaurants (id integer primary key, name text, source text);
        create table dishes (id integer primary key, name text);
        create table reviews (id integer primary key, text text);
        create table users (id integer primary key, name text);
        create table favorites (id integer primary key);
        create table refresh_tokens (id integer primary key);
        """
    )
    for index in range(40):
        connection.execute(
            "insert into restaurants values (?, ?, 'test')", (index, f"Place {index}")
        )
    for index in range(dishes):
        connection.execute("insert into dishes values (?, ?)", (index, f"Dish {index}"))
    for index in range(reviews):
        connection.execute(
            "insert into reviews values (?, ?)", (index, f"Review {index}")
        )
    for index in range(users):
        connection.execute("insert into users values (?, ?)", (index, f"User {index}"))
    for index in range(favorites):
        connection.execute("insert into favorites values (?)", (index,))
    connection.commit()
    connection.close()
    return path


def run_build(database: Path, *args):
    """Run build_city as a real subprocess and return (exit code, output)."""

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.build_city",
            "--database",
            str(database),
            *args,
        ],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


def test_it_refuses_against_a_populated_database(tmp_path):
    database = make_database(
        tmp_path / "tabiko.db", dishes=77, reviews=4, users=2, favorites=3
    )

    code, output = run_build(database)

    assert code == 3, f"expected a refusal, got {code}\n{output}"
    assert "Refusing to rebuild" in output
    # It has to say what is at stake, not just that it declined.
    assert "77" in output and "dishes" in output
    assert "4" in output and "reviews" in output
    assert "2" in output and "users" in output
    assert "scripts.backup" in output
    assert "--force" in output


def test_the_refusal_leaves_the_database_untouched(tmp_path):
    database = make_database(tmp_path / "tabiko.db", dishes=77, reviews=4, users=2)

    run_build(database)

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("select count(*) from dishes").fetchone()[0] == 77
        assert connection.execute("select count(*) from reviews").fetchone()[0] == 4
        assert connection.execute("select count(*) from users").fetchone()[0] == 2
    finally:
        connection.close()


def test_a_city_only_database_is_not_at_risk(tmp_path):
    """Places come from OpenStreetMap and are rebuilt from the snapshot.

    Only reader-created data should block, or the guard would fire on every
    normal rebuild and mean nothing.
    """

    database = make_database(tmp_path / "tabiko.db")

    assert build_city.destructive_targets(database) == {}


def test_the_guard_names_only_the_tables_that_have_rows(tmp_path):
    database = make_database(tmp_path / "tabiko.db", dishes=5, users=1)

    at_risk = build_city.destructive_targets(database)

    assert at_risk == {"dishes": 5, "users": 1}


def test_force_gets_past_the_guard(tmp_path):
    database = make_database(tmp_path / "tabiko.db", dishes=77, reviews=4, users=2)
    before = (
        sqlite3.connect(database).execute("select count(*) from dishes").fetchone()[0]
    )
    assert before == 77

    _code, output = run_build(database, "--force")

    # It must get past the guard and actually rebuild. Whether the snapshot
    # itself is readable is a separate question, so only the guard is asserted.
    assert "Refusing to rebuild" not in output


def test_verify_does_not_need_force(tmp_path):
    """--verify builds into a scratch database and changes nothing, so the guard
    must not stand in its way."""

    database = make_database(tmp_path / "tabiko.db", dishes=77, reviews=4, users=2)

    _code, output = run_build(database, "--verify")

    assert "Refusing to rebuild" not in output


def test_a_missing_database_is_not_at_risk(tmp_path):
    assert build_city.destructive_targets(tmp_path / "never.db") == {}


# ---------- backup and restore, actually run ----------


@pytest.fixture
def live(tmp_path, monkeypatch):
    """A database and an uploads directory wired up as the app would find them."""

    database = tmp_path / "tabiko.db"
    make_database(database, dishes=12, reviews=3, users=2, favorites=1)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "one.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"a" * 200)
    (uploads / "two.jpg").write_bytes(b"\xff\xd8\xff" + b"b" * 300)

    monkeypatch.setenv("TABIKO_DATABASE_URL", f"sqlite:///{database.as_posix()}")
    monkeypatch.setenv("TABIKO_UPLOADS_DIR", str(uploads))
    return database, uploads


def _counts(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {
            table: connection.execute(f"select count(*) from {table}").fetchone()[0]
            for table in ("restaurants", "dishes", "reviews", "users", "favorites")
        }
    finally:
        connection.close()


def test_a_backup_captures_the_database_and_the_uploads(live, tmp_path):
    _database, uploads = live

    target = backup_module.create_backup(tmp_path / "backups")

    assert (target / "database.sqlite3").is_file()
    assert (target / "uploads" / "one.png").read_bytes() == (
        uploads / "one.png"
    ).read_bytes()
    assert (target / "uploads" / "two.jpg").read_bytes() == (
        uploads / "two.jpg"
    ).read_bytes()
    manifest = backup_module.json.loads((target / "manifest.json").read_text())
    assert len(manifest["uploads"]) == 2
    assert manifest["row_counts"]["dishes"] == 12


def test_the_database_backup_is_consistent_not_just_the_file(tmp_path, monkeypatch):
    """A plain file copy in WAL mode can miss writes still in the -wal.

    That produces an archive that opens cleanly and is quietly short of recent
    rows, which is worse than no backup because it looks like one.
    """

    database = tmp_path / "tabiko.db"
    make_database(database, dishes=5)
    # Without this the script resolves the *development* database, and a test
    # that quietly backs up the real one is a test that can destroy it.
    monkeypatch.setenv("TABIKO_DATABASE_URL", f"sqlite:///{database.as_posix()}")
    monkeypatch.setenv("TABIKO_UPLOADS_DIR", str(tmp_path / "uploads"))

    # A connection left open means WAL sidecars are live while we copy.
    writer = sqlite3.connect(database)
    writer.execute("insert into dishes values (99, 'written just now')")
    writer.commit()

    try:
        target = backup_module.create_backup(tmp_path / "backups")
        captured = _counts(target / "database.sqlite3")
    finally:
        writer.close()

    assert captured["dishes"] == 6, "the online backup missed a committed write"


def test_no_test_can_reach_the_development_database(live):
    """A guard against the mistake this file already made once.

    `create_backup` with no configuration falls back to `backend/tabiko.db`. That
    is right for a person and a hazard for a test, so the wiring is asserted
    rather than assumed: the `live` fixture must have redirected it.
    """

    from app import database as database_module

    assert backup_module._database_path() != database_module.DEFAULT_DATABASE_PATH


def test_a_dry_run_verifies_without_writing(live, tmp_path):
    database, _ = live
    original = database.read_bytes()
    target = backup_module.create_backup(tmp_path / "backups")

    assert backup_module.restore(target, dry_run=True) == 0
    assert database.read_bytes() == original, "a dry run modified the database"


def test_a_restore_brings_back_what_was_lost(live, tmp_path):
    """The real thing: back up, destroy the live data, restore, check it came back."""

    database, uploads = live
    before = _counts(database)
    target = backup_module.create_backup(tmp_path / "backups")

    # Lose everything, as an accidental rebuild would.
    connection = sqlite3.connect(database)
    connection.executescript(
        "delete from dishes; delete from reviews; delete from users;"
    )
    connection.commit()
    connection.close()
    (uploads / "one.png").unlink()
    assert _counts(database)["dishes"] == 0

    assert backup_module.restore(target, force=True) == 0

    assert _counts(database) == before
    assert (uploads / "one.png").is_file()
    assert (uploads / "one.png").read_bytes() == (
        target / "uploads" / "one.png"
    ).read_bytes()


def test_a_restore_refuses_a_corrupted_archive(live, tmp_path):
    """Half a restore is worse than none: broken images on real dishes."""

    database, _ = live
    target = backup_module.create_backup(tmp_path / "backups")
    original = database.read_bytes()

    # Corrupt an upload inside the backup.
    (target / "uploads" / "one.png").write_bytes(b"corrupted")

    assert backup_module.restore(target, force=True) == 1
    assert database.read_bytes() == original, "a failed restore still wrote"


def test_a_restore_refuses_when_a_file_is_missing(live, tmp_path):
    database, _ = live
    target = backup_module.create_backup(tmp_path / "backups")
    original = database.read_bytes()

    (target / "uploads" / "two.jpg").unlink()

    assert backup_module.restore(target, force=True) == 1
    assert database.read_bytes() == original


def test_a_restore_will_not_clobber_without_force(live, tmp_path):
    database, _ = live
    target = backup_module.create_backup(tmp_path / "backups")
    original = database.read_bytes()

    assert backup_module.restore(target) == 2
    assert database.read_bytes() == original


@pytest.mark.skipif(
    sys.platform != "win32",
    reason=(
        "Windows refuses to replace a file another process holds open, which "
        "is what this refusal is for. POSIX lets the replace succeed, so the "
        "locked-database path this test exercises cannot trigger there."
    ),
)
def test_a_restore_reports_clearly_when_the_database_is_locked(live, tmp_path):
    """The bug this script's first draft had, found by actually running it.

    A live app holds the database open. The original restore wrote the database
    and then died on the uploads with a bare PermissionError, leaving rows
    pointing at files that were not there -- a half-restore, which is worse than
    no restore.

    The first attempt to prevent this probed for the lock up front. That does not
    work: Python's `open` does not request exclusive access, so the probe
    succeeds on a database a running app is actively using, and the restore
    walked straight into the same failure. So the swap is now atomic and the
    real error is caught instead.
    """

    database, _uploads = live
    target = backup_module.create_backup(tmp_path / "backups")
    before = _counts(database)

    # Hold the database itself, the way a running uvicorn does.
    holder = database.open("ab")
    try:
        with pytest.raises(SystemExit) as caught:
            backup_module.restore(target, force=True)
    finally:
        holder.close()

    message = str(caught.value)
    assert "held open" in message
    assert "Stop the app" in message
    assert "Nothing was lost" in message

    # The database is intact, and no half-written file is left beside it.
    assert _counts(database) == before
    assert not database.with_name(f"{database.name}.restoring").exists()
    assert database.is_file()


def test_uploads_are_restored_before_the_database_is_swapped(live, tmp_path):
    """Order matters: a recoverable failure beats a broken menu.

    A dish row holds a URL. Extra files on disk are harmless; rows pointing at
    files that are not there are not.
    """

    database, uploads = live
    target = backup_module.create_backup(tmp_path / "backups")
    original = database.read_bytes()

    # Fail at the very end, after the uploads have been written.
    real_replace = backup_module.os.replace

    def failing_replace(src, dst):
        raise OSError("simulated failure at the final step")

    backup_module.os.replace = failing_replace
    try:
        with pytest.raises(OSError):
            backup_module.restore(target, force=True)
    finally:
        backup_module.os.replace = real_replace

    # The uploads are back, and the database is untouched: a reader sees the
    # old menu with spare files on disk, not a new menu with no photographs.
    assert (uploads / "one.png").is_file()
    assert (uploads / "one.png").read_bytes() == (
        target / "uploads" / "one.png"
    ).read_bytes()
    assert database.read_bytes() == original
    # No half-written file left behind.
    assert not database.with_name(f"{database.name}.restoring").exists()


def test_a_restore_keeps_the_database_it_replaced(live, tmp_path):
    """A restore of the wrong backup has to be recoverable too."""

    database, _ = live
    target = backup_module.create_backup(tmp_path / "backups")
    before = database.read_bytes()

    backup_module.restore(target, force=True)

    kept = list(database.parent.glob(f"{database.name}.pre-restore-*"))
    assert kept, "the replaced database was not kept"
    assert kept[0].read_bytes() == before


def test_backups_are_listed_newest_first(live, tmp_path):
    root = tmp_path / "backups"
    backup_module.create_backup(root)
    backup_module.create_backup(root)

    found = backup_module.list_backups(root)
    assert len(found) == 2
    assert found == sorted(found, reverse=True)


def test_restore_rejects_a_directory_that_is_not_a_backup(live, tmp_path):
    empty = tmp_path / "not-a-backup"
    empty.mkdir()

    with pytest.raises(SystemExit):
        backup_module.restore(empty)
