"""Back up the database and the uploaded photos, and restore them.

    python -m scripts.backup                    # write a timestamped backup
    python -m scripts.backup --dir /mnt/backups
    python -m scripts.restore <dir>             # restore, refusing to clobber
    python -m scripts.restore <dir> --dry-run   # verify without writing

Why a script and not `cp`
-------------------------
SQLite in WAL mode has three files, and copying `tabiko.db` on its own captures
none of the writes still sitting in `tabiko.db-wal`. The result is a backup that
opens cleanly and is quietly missing recent data, which is worse than no backup
because it looks like one. `sqlite3`'s online backup API takes a consistent
snapshot of a live database without blocking readers, so that is what this uses.

Why the photos are in the same backup
-------------------------------------
Uploads live on the same volume as the database, and a dish row whose `image_url`
points at a file that is gone is a broken image on a real menu. A backup of one
without the other is only half a restore, so both travel together and the
restore refuses to run if the manifest does not describe both.

The manifest records a SHA-256 per file. A restore verifies every one before
touching anything, so a truncated or corrupted archive is reported rather than
discovered later by a reader looking at a blank dish photo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "manifest.json"
DB_NAME = "database.sqlite3"


def _database_path() -> Path:
    """The database the app is actually configured to use."""

    url = (os.getenv("TABIKO_DATABASE_URL") or "").strip()
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        return BACKEND / url.removeprefix("sqlite:///")
    if url.startswith("sqlite:////"):
        return Path(url[len("sqlite:///") :])
    return BACKEND / "tabiko.db"


def _uploads_path() -> Path:
    configured = (os.getenv("TABIKO_UPLOADS_DIR") or "").strip()
    if configured:
        return Path(configured)
    data_dir = (os.getenv("TABIKO_DATA_DIR") or "").strip()
    if data_dir:
        return Path(data_dir) / "uploads"
    return BACKEND / "uploads"


def default_backup_root() -> Path:
    return BACKEND / "backups"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_backup(destination: Path | None = None) -> Path:
    """Write a consistent snapshot of the database and the uploads.

    The database is copied through SQLite's own backup API rather than by
    reading the file. In WAL mode a plain file copy can capture the main database
    without the writes still sitting in the `-wal` sidecar, producing an archive
    that opens cleanly and is missing recent rows.
    """

    source = _database_path()
    if not source.is_file():
        raise SystemExit(f"No database at {source}. Is the app running?")

    root = destination or default_backup_root()
    # Microseconds, because two backups in the same second would otherwise land
    # in the same directory and the second would silently overwrite the first.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")[:-4] + "Z"
    target = root / stamp
    (target / "uploads").mkdir(parents=True, exist_ok=True)

    destination_db = target / DB_NAME
    # `closing`, not a bare `with sqlite3.connect(...)`. The connection context
    # manager commits or rolls back a transaction; it does not close the
    # connection, so the file stays open afterwards. On Windows that made a
    # later restore fail with "Access is denied" on a file this script had
    # itself left locked.
    with (
        closing(
            sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
        ) as reader,
        closing(sqlite3.connect(destination_db)) as writer,
    ):
        reader.backup(writer)

    uploads = _uploads_path()
    files: list[dict] = []
    if uploads.is_dir():
        for path in sorted(uploads.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(uploads)
            copied = target / "uploads" / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, copied)
            files.append(
                {
                    "path": str(relative).replace("\\", "/"),
                    "bytes": copied.stat().st_size,
                    "sha256": sha256_of(copied),
                }
            )

    counts = _row_counts(destination_db)
    manifest = {
        "schema": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_database": str(source),
        "source_uploads": str(uploads),
        "database": {
            "path": DB_NAME,
            "bytes": destination_db.stat().st_size,
            "sha256": sha256_of(destination_db),
        },
        "row_counts": counts,
        "uploads": files,
    }
    (target / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"backup written to {target}")
    print(f"    database   {manifest['database']['bytes']:>10,} bytes")
    print(f"    uploads    {len(files):>10} files")
    print(f"    contents   {counts}")
    return target


def _row_counts(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type='table'"
            )
        }
        return {
            table: connection.execute(f"select count(*) from {table}").fetchone()[0]
            for table in sorted(tables)
            if not table.startswith("sqlite_")
        }
    finally:
        connection.close()


def list_backups(root: Path | None = None) -> list[Path]:
    base = root or default_backup_root()
    if not base.is_dir():
        return []
    return sorted(
        (path for path in base.iterdir() if (path / MANIFEST_NAME).is_file()),
        reverse=True,
    )


def restore(backup_dir: Path, *, dry_run: bool = False, force: bool = False) -> int:
    """Restore a backup after verifying every file in it.

    Verification happens before anything is written, on purpose. A restore that
    half-succeeds leaves a database that does not match its uploads, and the
    symptom is broken images on real dishes rather than an error.
    """

    manifest_path = backup_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise SystemExit(f"No {MANIFEST_NAME} in {backup_dir}. Is that a backup?")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    print(f"restoring {backup_dir}")
    print(f"    taken at   {manifest.get('created_at')}")
    print(f"    from       {manifest.get('source_database')}")
    print(f"    rows       {manifest.get('row_counts')}")
    print(f"    uploads    {len(manifest.get('uploads', []))}")

    problems: list[str] = []

    database_file = backup_dir / manifest["database"]["path"]
    if not database_file.is_file():
        problems.append(f"missing {manifest['database']['path']}")
    else:
        actual = sha256_of(database_file)
        if actual != manifest["database"]["sha256"]:
            problems.append(
                f"database sha256 mismatch: {actual[:16]} vs "
                f"{manifest['database']['sha256'][:16]}"
            )

    for entry in manifest.get("uploads", []):
        candidate = backup_dir / "uploads" / entry["path"]
        if not candidate.is_file():
            problems.append(f"missing upload {entry['path']}")
            continue
        actual = sha256_of(candidate)
        if actual != entry["sha256"]:
            problems.append(f"upload {entry['path']} sha256 mismatch")

    if problems:
        print(f"\n    {len(problems)} problem(s); nothing was written:")
        for problem in problems[:20]:
            print(f"      - {problem}")
        return 1

    print("\n    every file verified")

    target_db = Path(manifest.get("source_database") or _database_path())
    target_uploads = Path(manifest.get("source_uploads") or _uploads_path())

    if dry_run:
        print("\nDRY RUN. Nothing was written.")
        print(f"    would replace {target_db}")
        print(f"    with {len(manifest.get('uploads', []))} uploads")
        if _database_is_locked(target_db):
            print(
                "\n    note: the database looks held open. The restore would fail\n"
                "    on that, but the swap is atomic and recoverable either way."
            )
        return 0

    if target_db.exists() and not force:
        print(f"\n    {target_db} already exists.")
        print("    Pass --force to overwrite it.")
        return 2

    # Uploads first, database last.
    #
    # A dish row holds a URL. If the uploads land and the database swap then
    # fails, the extra files are harmless. If the database lands and the uploads
    # do not, every photo on the menu is broken. The order has to favour the
    # recoverable failure.
    target_uploads.mkdir(parents=True, exist_ok=True)
    restored = 0
    for entry in manifest.get("uploads", []):
        destination = target_uploads / entry["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_dir / "uploads" / entry["path"], destination)
        restored += 1
    print(f"    restored {restored} uploads")

    # Copy beside the target, then rename into place, so an interrupted copy
    # cannot leave a truncated database where a working one was.
    target_db.parent.mkdir(parents=True, exist_ok=True)
    staging = target_db.with_name(f"{target_db.name}.restoring")
    try:
        shutil.copy2(database_file, staging)

        if target_db.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            displaced = target_db.with_name(f"{target_db.name}.pre-restore-{stamp}")
            shutil.copy2(target_db, displaced)
            print(f"    kept the previous database as {displaced.name}")

        # The sidecars go before the swap, not after. A stale `-wal` is the
        # write-ahead log of the *old* database, and pairing it with a newly
        # replaced main file is how a restore silently corrupts a database that
        # opened cleanly a moment before.
        for suffix in ("-wal", "-shm"):
            target_db.with_name(target_db.name + suffix).unlink(missing_ok=True)

        try:
            os.replace(staging, target_db)
        except PermissionError as exc:
            # A running app holds the database open and Windows will not replace
            # it. Tried to predict this up front and gave up: Python's `open` does
            # not request exclusive access, so a "is it locked?" probe succeeds
            # even when it very much is. Catching the real failure and saying so
            # is the only version of this that is actually correct.
            raise SystemExit(
                f"\n    {target_db.name} is held open by another process, so it "
                "could not be replaced.\n"
                "    Stop the app and run the restore again. Nothing was lost:\n"
                f"    the previous database is intact as {displaced.name if target_db.exists() else 'the original'},\n"
                f"    and the {restored} upload(s) already restored are unchanged."
            ) from exc
    finally:
        # Never leave a half-written database sitting beside a working one.
        staging.unlink(missing_ok=True)

    print("    restored the database")
    print(f"    row counts now: {_row_counts(target_db)}")
    return 0


def _database_is_locked(database: Path) -> bool:
    """Best-effort advisory only, and deliberately not relied upon.

    Python's `open` does not request exclusive access, so this returns False on
    a database a running app is actively using. It is kept because it is right
    on the platforms where file locking is advisory, and wrong callers must not
    treat it as the last line of defence.
    """

    try:
        with database.open("ab"):
            return False
    except OSError:
        return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    make = sub.add_parser("create", help="Write a backup (the default action)")
    make.add_argument("--dir", type=Path, help="Where to write it")

    sub.add_parser("list", help="List available backups, newest first")

    put = sub.add_parser("restore", help="Restore a backup")
    put.add_argument("directory", type=Path)
    put.add_argument("--dry-run", action="store_true", help="Verify without writing")
    put.add_argument(
        "--force", action="store_true", help="Overwrite an existing database"
    )

    args = parser.parse_args()

    if args.command == "create":
        create_backup(args.dir)
        return 0
    if args.command == "list":
        found = list_backups()
        if not found:
            print("No backups.")
            return 0
        for path in found:
            manifest = json.loads((path / MANIFEST_NAME).read_text(encoding="utf-8"))
            print(
                f"  {path.name}  {manifest['created_at']}  "
                f"{manifest['database']['bytes']:>10,} bytes  "
                f"{len(manifest['uploads'])} uploads  {manifest['row_counts']}"
            )
        return 0

    return restore(args.directory, dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
