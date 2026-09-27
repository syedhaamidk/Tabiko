"""Preflight is the gate a deployment passes through.

It exists to turn a misconfiguration into a loud failure at boot rather than a
blank page an hour later, which means its own failures are expensive. Two have
already happened, both found by actually building and running the container
rather than by reading the code:

`check_icons` looked for the icons in the frontend *source* tree. The runtime
image has no `frontend/` directory at all, so every container refused to start --
while the icons sat in the built output where a browser would have fetched them
without complaint.

The first fix fell through to the source tree when the static directory had no
icons, which is worse: a genuinely icon-less build passed as long as a developer
happened to have `npm run icons` output lying around.

These tests exist so that class of mistake is caught here rather than by a
container refusing to boot.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.ingestion import snapshot as snap
from scripts import preflight

ICON_NAMES = ("icon-192.png", "icon-512.png")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Start every test from a deployable baseline.

    Without this, a developer's own environment leaks in: their real secret, their
    real static directory, whatever `TABIKO_ENV` they left it on.
    """

    for name in (
        "TABIKO_JWT_SECRET",
        "JWT_SECRET_KEY",
        "TABIKO_ENV",
        "TABIKO_STATIC_DIR",
        "TABIKO_CORS_ORIGINS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TABIKO_JWT_SECRET", "x" * 48)
    monkeypatch.setenv("TABIKO_ENV", "production")


@pytest.fixture
def build(tmp_path):
    """A plausible built frontend: an index, a bundle, and icons."""

    directory = tmp_path / "static"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text("<html></html>")
    (directory / "assets" / "app.js").write_text("// bundle")
    icons = directory / "icons"
    icons.mkdir()
    for name in ICON_NAMES:
        (icons / name).write_bytes(b"\x89PNG")
    return directory


# ---------- the icons check ----------


def test_icons_are_read_from_the_served_build(monkeypatch, build):
    """The build output is what a browser fetches, so it is what gets checked."""

    monkeypatch.setenv("TABIKO_STATIC_DIR", str(build))

    result = preflight.check_icons()

    assert result.ok, result.detail
    assert str(build / "icons") in result.detail


def test_icons_are_read_from_the_source_tree_when_nothing_is_served(
    monkeypatch, tmp_path
):
    """Development serves through Vite, which reads frontend/public directly."""

    public = tmp_path / "frontend" / "public" / "icons"
    public.mkdir(parents=True)
    for name in ICON_NAMES:
        (public / name).write_bytes(b"\x89PNG")
    monkeypatch.setattr(preflight, "BACKEND", tmp_path / "backend")

    result = preflight.check_icons()

    assert result.ok, result.detail
    assert str(public) in result.detail


def test_a_build_with_no_icons_fails(monkeypatch, build):
    """A build missing its icons cannot be installed on a phone."""

    for name in ICON_NAMES:
        (build / "icons" / name).unlink()
    monkeypatch.setenv("TABIKO_STATIC_DIR", str(build))

    result = preflight.check_icons()

    assert not result.ok
    assert "missing" in result.detail


def test_a_build_with_no_icons_does_not_fall_back_to_the_source_tree(
    monkeypatch, build, tmp_path
):
    """The regression that made the first fix useless.

    A developer with `npm run icons` output on disk must not be able to make a
    broken build pass. When a static directory is configured it is the
    authoritative copy, full stop.
    """

    public = tmp_path / "frontend" / "public" / "icons"
    public.mkdir(parents=True)
    for name in ICON_NAMES:
        (public / name).write_bytes(b"\x89PNG")
    monkeypatch.setattr(preflight, "BACKEND", tmp_path / "backend")

    for name in ICON_NAMES:
        (build / "icons" / name).unlink()
    monkeypatch.setenv("TABIKO_STATIC_DIR", str(build))

    result = preflight.check_icons()

    assert not result.ok
    assert str(build / "icons") in result.detail


def test_an_absent_icons_directory_fails_and_names_the_fix(monkeypatch, build):
    import shutil

    shutil.rmtree(build / "icons")
    monkeypatch.setenv("TABIKO_STATIC_DIR", str(build))

    result = preflight.check_icons()

    assert not result.ok
    # The message has to be actionable, because it is the last thing anyone
    # reads before the container gives up.
    assert "npm run build" in result.detail


# ---------- the other gates ----------


def test_an_unset_secret_fails(monkeypatch):
    monkeypatch.delenv("TABIKO_JWT_SECRET")

    assert not preflight.check_secret().ok


def test_the_published_dev_secret_fails(monkeypatch):
    monkeypatch.setenv(
        "TABIKO_JWT_SECRET",
        "dev-only-secret-change-me-before-production-0000000000000000",
    )

    result = preflight.check_secret()

    assert not result.ok
    assert "dev secret" in result.detail


def test_a_short_secret_fails(monkeypatch):
    monkeypatch.setenv("TABIKO_JWT_SECRET", "too-short")

    assert not preflight.check_secret().ok


def test_a_real_secret_passes(monkeypatch):
    monkeypatch.setenv("TABIKO_JWT_SECRET", "z" * 48)

    assert preflight.check_secret().ok


def test_development_mode_fails_as_a_deployment(monkeypatch):
    """`TABIKO_ENV=development` is the only opt-in to the dev secret.

    Preflight is what turns that opt-in from a silent risk into a boot failure,
    so it has to notice the flag itself.
    """

    monkeypatch.setenv("TABIKO_ENV", "development")

    assert not preflight.check_environment().ok


def test_a_wildcard_cors_origin_fails(monkeypatch):
    monkeypatch.setenv("TABIKO_CORS_ORIGINS", "*")

    assert not preflight.check_cors().ok


def test_unset_cors_is_only_a_warning(monkeypatch):
    """A same-origin deployment needs no CORS origins at all."""

    result = preflight.check_cors()

    assert result.ok
    assert result.warning


def test_a_static_dir_that_does_not_exist_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("TABIKO_STATIC_DIR", str(tmp_path / "never-built"))

    result = preflight.check_static()

    assert not result.ok
    assert "does not exist" in result.detail


def test_a_static_dir_with_no_bundle_fails(monkeypatch, build):
    for child in (build / "assets").iterdir():
        child.unlink()
    monkeypatch.setenv("TABIKO_STATIC_DIR", str(build))

    result = preflight.check_static()

    assert not result.ok
    assert "JavaScript" in result.detail


def test_a_complete_build_passes(monkeypatch, build):
    monkeypatch.setenv("TABIKO_STATIC_DIR", str(build))

    result = preflight.check_static()

    assert result.ok
    assert not result.warning


def test_an_unset_static_dir_is_only_a_warning():
    """Nothing to serve is fine when something else is in front."""

    result = preflight.check_static()

    assert result.ok
    assert result.warning


# ---------- the city data check ----------


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A backend directory with a plausible snapshot and provenance record."""

    directory = tmp_path / "backend"
    (directory / "data").mkdir(parents=True)
    monkeypatch.setattr(preflight, "BACKEND", directory)
    return directory / "data"


def write_provenance(data_dir, **overrides):
    record = {
        "schema": 1,
        "city": "Bengaluru",
        "bbox": [12.75, 77.45, 13.15, 77.8],
        "snapshot_digest": "sha256:" + "a" * 64,
        "snapshot_fetched_at": "2026-09-27T00:00:00+00:00",
        "places_imported": 7683,
    }
    record.update(overrides)
    (data_dir / "city_provenance.json").write_text(json.dumps(record))
    return record


def write_snapshot(data_dir):
    path = data_dir / "osm_snapshot.json.gz"
    envelope = snap.build_envelope(
        [{"type": "node", "id": 1, "tags": {"name": "A"}}],
        bbox=(12.75, 77.45, 13.15, 77.8),
    )
    snap.write_snapshot(path, envelope)
    return path


def test_a_fresh_city_passes(data_dir):
    write_provenance(data_dir)
    write_snapshot(data_dir)

    result = preflight.check_city_data()

    assert result.ok and not result.warning
    assert "7683 places" in result.detail


def test_a_missing_provenance_fails(data_dir):
    """The silent-empty-city case: healthy boot, no data, nothing fails.

    Nothing else in the boot path can catch this, which is the reason the check
    exists at all.
    """

    write_snapshot(data_dir)

    result = preflight.check_city_data()

    assert not result.ok
    assert "build_city" in result.detail


def test_a_provenance_record_with_no_snapshot_fails(data_dir):
    """The record would claim a city nothing can rebuild."""

    write_provenance(data_dir)

    result = preflight.check_city_data()

    assert not result.ok
    assert "--refresh" in result.detail


def test_unreadable_provenance_fails_rather_than_being_skipped(data_dir):
    (data_dir / "city_provenance.json").write_text("{ not json")
    write_snapshot(data_dir)

    result = preflight.check_city_data()

    assert not result.ok
    assert "unreadable" in result.detail


def test_an_old_city_is_a_warning_not_a_failure(data_dir):
    """Stale data is a debt. Refusing to boot over it would be worse."""

    old = (datetime.now(timezone.utc) - timedelta(days=800)).isoformat()
    write_provenance(data_dir, snapshot_fetched_at=old)
    write_snapshot(data_dir)

    result = preflight.check_city_data()

    assert result.ok
    assert result.warning
    assert "--refresh" in result.detail


def test_a_city_with_no_usable_timestamp_warns(data_dir):
    write_provenance(data_dir, snapshot_fetched_at="sometime last year")
    write_snapshot(data_dir)

    result = preflight.check_city_data()

    assert result.ok
    assert result.warning
    assert "timestamp" in result.detail


def test_the_real_check_passes_on_the_committed_city():
    """Not a fixture: the snapshot and record actually in the repository."""

    result = preflight.check_city_data()

    assert result.ok, result.detail
    assert "places" in result.detail


# ---------- the report ----------


def all_checks():
    return [check() for check in preflight.CHECKS]


def test_a_clean_production_configuration_has_no_failures(monkeypatch, build):
    monkeypatch.setenv("TABIKO_STATIC_DIR", str(build))

    assert [r for r in all_checks() if not r.ok] == []


def test_a_broken_configuration_is_reported_not_raised(monkeypatch, build):
    """One bad setting must not stop the other checks from reporting.

    A deployer reading the output needs the whole list, not the first failure.
    """

    monkeypatch.setenv("TABIKO_JWT_SECRET", "short")
    monkeypatch.setenv("TABIKO_ENV", "development")
    monkeypatch.setenv("TABIKO_CORS_ORIGINS", "*")
    monkeypatch.setenv("TABIKO_STATIC_DIR", str(build / "nope"))

    failed = {r.name for r in all_checks() if not r.ok}

    assert "signing secret" in failed
    assert "environment" in failed
    assert "CORS origins" in failed
    assert "frontend build" in failed


def test_every_check_reports_under_a_name(monkeypatch, build):
    """The report is read by a person scanning for the line that failed."""

    monkeypatch.setenv("TABIKO_STATIC_DIR", str(build))

    results = all_checks()

    assert len(results) == len(preflight.CHECKS)
    assert {r.name for r in results} == {
        "signing secret",
        "environment",
        "database",
        "frontend build",
        "app icons",
        "CORS origins",
        "city data",
        "proxy trust",
        "migrations",
    }


def test_main_exits_zero_on_a_clean_configuration(monkeypatch, build, capsys):
    monkeypatch.setenv("TABIKO_STATIC_DIR", str(build))
    monkeypatch.setattr(sys, "argv", ["preflight"])

    assert preflight.main() == 0
    assert "0 failures" in capsys.readouterr().out


def test_main_exits_non_zero_and_prints_the_failure(monkeypatch, build, capsys):
    monkeypatch.setenv("TABIKO_JWT_SECRET", "short")
    monkeypatch.setenv("TABIKO_STATIC_DIR", str(build))
    monkeypatch.setattr(sys, "argv", ["preflight"])

    assert preflight.main() == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "1 failures" in out


def test_strict_mode_turns_warnings_into_failures(monkeypatch, build, capsys):
    """Warnings are about a fleet, not a box, so they only block on request."""

    monkeypatch.setenv("TABIKO_STATIC_DIR", str(build))
    # An unset static dir is the warning, and this is a clean run otherwise.
    monkeypatch.delenv("TABIKO_STATIC_DIR")

    monkeypatch.setattr(sys, "argv", ["preflight"])
    assert preflight.main() == 0
    assert "0 failures" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["preflight", "--strict"])
    assert preflight.main() == 1
    # The summary has to admit it is blocking, or an operator sees "0 failures"
    # on a deploy that just failed and learns to ignore the gate.
    assert "strict: warnings block the deploy" in capsys.readouterr().out


def test_preflight_runs_from_any_working_directory(tmp_path, monkeypatch, capsys):
    """It runs from the container entrypoint, where the cwd is not the repo.

    It has to resolve `alembic.ini` and its own neighbours from the module, not
    from wherever it happened to be invoked.
    """

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TABIKO_JWT_SECRET", "y" * 48)
    monkeypatch.setattr(sys, "argv", ["preflight"])

    assert preflight.main() == 0
    assert "head is" in capsys.readouterr().out


def test_preflight_does_not_write_to_the_database(tmp_path, monkeypatch):
    """It runs before migrations, so it must not create or alter the schema.

    A preflight that wrote would make its own report untrustworthy: it could turn
    a clean deploy into a failing one, or the reverse.
    """

    monkeypatch.setenv("TABIKO_JWT_SECRET", "y" * 48)
    monkeypatch.setattr(sys, "argv", ["preflight"])
    target = tmp_path / "probe.db"
    monkeypatch.setenv("TABIKO_DATABASE_URL", f"sqlite:///{target.as_posix()}")

    preflight.main()

    assert not target.exists(), "preflight created a database file"


def test_the_schema_check_reads_the_migration_head(monkeypatch, build):
    """It confirms the migrations on disk, not the database, so it is safe to
    run before anything is applied."""

    result = preflight.check_schema()

    assert result.ok
    assert "head is" in result.detail


def test_every_check_explains_itself():
    """Each line of the report is a sentence someone has to act on."""

    for check in preflight.CHECKS:
        assert check.__doc__, f"{check.__name__} has no docstring"


def test_a_check_that_raises_is_reported_rather_than_crashing(monkeypatch, capsys):
    """One unexpected error must not cost the operator the other seven results.

    `check_schema` used to raise `CommandError` from any working directory but
    the backend one, which aborted the whole report with a traceback. Preflight
    exists to tell you everything that is wrong at once, so an exception is just
    another finding.
    """

    def explodes():
        raise RuntimeError("something nobody anticipated")

    monkeypatch.setattr(preflight, "CHECKS", (explodes, preflight.check_secret))
    monkeypatch.setattr(sys, "argv", ["preflight"])

    assert preflight.main() == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "RuntimeError" in out
    # The surviving check still reported, which is the whole point.
    assert "signing secret" in out


def test_a_raising_check_is_reported_as_a_failure_by_the_runner():
    """The isolation lives in the runner, not in each individual check."""

    def explodes():
        raise ValueError("boom")

    result = preflight._run_check(explodes)

    assert not result.ok
    assert "ValueError" in result.detail
    assert "boom" in result.detail


def test_the_schema_check_survives_any_working_directory(tmp_path, monkeypatch):
    """The regression: alembic resolved `script_location` against the cwd.

    Running preflight from anywhere but the backend directory -- a pre-commit
    hook, a CI step, a shell prompt -- raised CommandError. Both paths are now
    absolute, so the check is where it is run from.
    """

    for directory in (tmp_path, Path("C:/"), Path(preflight.BACKEND)):
        monkeypatch.chdir(directory)
        result = preflight.check_schema()

        assert result.ok, f"failed from {directory}: {result.detail}"
        assert "head is" in result.detail
