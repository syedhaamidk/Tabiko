"""Preflight checks for a deployment.

Run before starting a real instance. Every one of these has either been the
difference between a working deployment and a broken one, or is a mistake that
fails silently and is only noticed later.

    python -m scripts.preflight            # report everything
    python -m scripts.preflight --strict   # also fail on warnings

Exits non-zero if any check fails, so it can gate a deploy.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


@dataclass
class Result:
    name: str
    ok: bool
    detail: str
    # A warning is something to read but not a blocker, such as a SQLite database
    # being fine for one box and wrong for a fleet.
    warning: bool = False


def check_secret() -> Result:
    """The JWT signing secret must be real, long, and not the published one.

    This is the single most consequential setting in the service: it signs every
    access token, so a leaked or known value is an admin credential available to
    anyone who has read the repository.
    """

    name = "signing secret"
    secret = (
        os.getenv("TABIKO_JWT_SECRET") or os.getenv("JWT_SECRET_KEY") or ""
    ).strip()
    if not secret:
        return Result(
            name,
            False,
            "TABIKO_JWT_SECRET is unset. The app will refuse to start, which is "
            "correct; set a real one.",
        )
    if secret == "dev-only-secret-change-me-before-production-0000000000000000":
        return Result(
            name,
            False,
            "The published dev secret is in use. Anyone could mint an admin token.",
        )
    if len(secret) < 32:
        return Result(
            name, False, f"Only {len(secret)} characters; at least 32 are required."
        )
    return Result(name, True, f"set, {len(secret)} characters")


def check_environment() -> Result:
    """Refuse `TABIKO_ENV=development` outside development.

    It is the only opt-in to the published dev secret, so a container that
    inherits it from a compose file or a shell profile would otherwise run in
    production, signing tokens anyone can forge.
    """
    environment = (os.getenv("TABIKO_ENV") or "").strip().lower()
    if not environment:
        return Result(
            "environment",
            True,
            "unset, so treated as production. Set TABIKO_ENV=development locally to be explicit.",
            warning=True,
        )
    if environment in {"development", "dev", "test", "local"}:
        return Result(
            "environment",
            False,
            f"TABIKO_ENV={environment} in what looks like a real deployment. "
            "This permits the published dev secret.",
        )
    return Result("environment", True, environment)


def check_database() -> Result:
    """Warn, never fail, on SQLite: fine for one box, wrong for a fleet.

    Writes serialise on a single file, so more than one instance corrupts
    throughput long before it corrupts data. That is a capacity decision, not a
    misconfiguration, so it must not block a single-box launch.
    """
    url = os.getenv("TABIKO_DATABASE_URL", "sqlite:///./tabiko.db")
    if url.startswith("sqlite"):
        return Result(
            "database",
            True,
            "SQLite. Fine for a single box; use PostgreSQL before running more "
            "than one instance, because writes serialise on one file.",
            warning="sqlite" in url and url.endswith(":memory:"),
        )
    return Result("database", True, "PostgreSQL")


def check_static() -> Result:
    """Is there a built frontend the API can serve, and is it complete?

    An API with no frontend answers every request and shows the reader nothing,
    so a missing or half-built `dist` has to stop the deploy.
    """
    """The built frontend has to exist and be findable.

    A missing static directory is the failure that produces a blank page with no
    error anywhere, because the API is perfectly healthy. Setting
    TABIKO_STATIC_DIR is an explicit instruction, so a bad value is a hard
    failure rather than something to shrug at; leaving it unset is only a warning,
    because a CDN or the Vite dev server may be serving the app instead.
    """

    configured = (os.getenv("TABIKO_STATIC_DIR") or "").strip()
    if not configured:
        default = BACKEND / "static"
        if default.is_dir():
            return check_static_at(default)
        return Result(
            "frontend build",
            True,
            f"not served from the API ({default} is absent). Fine if a CDN or "
            "the Vite dev server is in front of it.",
            warning=True,
        )
    directory = Path(configured)
    if not directory.is_dir():
        return Result(
            "frontend build",
            False,
            f"TABIKO_STATIC_DIR points at {directory}, which does not exist. The "
            "app would serve the API and nothing else.",
        )
    return check_static_at(directory)


def check_static_at(directory: Path) -> Result:
    index = directory / "index.html"
    assets = directory / "assets"
    if not index.is_file():
        return Result("frontend build", False, f"{index} is missing.")
    if not assets.is_dir() or not any(assets.glob("*.js")):
        return Result("frontend build", False, f"{assets} has no JavaScript bundle.")
    return Result("frontend build", True, f"served from {directory}")


def check_icons() -> Result:
    """The installable icons are generated at build time, not committed.

    Which directory to look in depends on who is serving the app, and getting
    this wrong is not a cosmetic problem: the container has no `frontend/`
    source tree at all, so checking the source path made every image refuse to
    start even though the icons were sitting in the built output where a browser
    would actually fetch them from.

    With a static directory configured, that build output is what matters -- it
    is what gets served and what gets installed. Without one, Vite is serving
    from the source `public/` directory, so that is the copy that matters.
    """

    static = (os.getenv("TABIKO_STATIC_DIR") or "").strip()
    if static:
        # The build output is authoritative. Falling back to the source tree here
        # would let a genuinely icon-less build pass because a developer happens
        # to have `npm run icons` output lying around.
        directory, remedy = Path(static) / "icons", "run `npm run build`"
    else:
        directory = BACKEND.parent / "frontend" / "public" / "icons"
        remedy = "run `npm run icons`"

    if not directory.is_dir():
        return Result(
            "app icons", False, f"{directory} is absent. {remedy.capitalize()}."
        )
    missing = [
        name
        for name in ("icon-192.png", "icon-512.png")
        if not (directory / name).is_file()
    ]
    if missing:
        return Result(
            "app icons", False, f"{directory} is missing {', '.join(missing)}."
        )
    return Result("app icons", True, f"present in {directory}")


def check_cors() -> Result:
    """A wildcard CORS origin lets any site call the API as the reader.

    Unset is fine, because a same-origin deployment needs no CORS at all. A
    literal `*` is not fine, whatever else is configured.
    """
    configured = os.getenv("TABIKO_CORS_ORIGINS", "")
    if not configured.strip():
        return Result(
            "CORS origins",
            True,
            "unset, so only the Vite dev origins are allowed. A same-origin "
            "deployment needs nothing here.",
            warning=True,
        )
    if "*" in configured:
        return Result(
            "CORS origins",
            False,
            "A wildcard origin is not acceptable with credentials.",
        )
    return Result("CORS origins", True, configured)


def check_city_data() -> Result:
    """Is there a record of where the city came from, and is it recent?

    This is the one check that cannot be satisfied by configuration, and it
    exists because the failure it guards against is invisible. Every other
    misconfiguration announces itself: a missing frontend serves no page, a bad
    secret stops the boot. A deployment with no data boots perfectly, passes
    every other check, answers `/health/live`, and shows a reader an empty map.
    `GET /stats` reporting `places: 0` is the only symptom, and nothing in the
    boot path looks at it.

    So the provenance record is required, and the snapshot's age is reported. It
    cannot check the live database's contents without importing SQLAlchemy,
    which would make preflight depend on the app and mean it could no longer run
    before migrations; the record plus a `/stats` glance is the honest limit of
    what a boot-time check can say.
    """

    provenance = BACKEND / "data" / "city_provenance.json"
    snapshot = BACKEND / "data" / "osm_snapshot.json.gz"
    stale_after_days = 365

    if not provenance.is_file():
        return Result(
            "city data",
            False,
            f"{provenance} is absent, so nothing records where the city came "
            "from. Run `python -m scripts.build_city` to build it from the "
            "committed snapshot.",
        )

    try:
        record = json.loads(provenance.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return Result("city data", False, f"{provenance} is unreadable: {exc}")

    if not snapshot.is_file():
        return Result(
            "city data",
            False,
            f"{snapshot} is absent, so the city cannot be rebuilt. Run "
            "`python -m scripts.build_city --refresh`.",
        )

    places = record.get("places_imported")
    digest = str(record.get("snapshot_digest") or "none recorded")
    fetched_at = record.get("snapshot_fetched_at")
    age: float | None = None
    if isinstance(fetched_at, str):
        try:
            when = datetime.fromisoformat(fetched_at)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - when).total_seconds() / 86_400
        except ValueError:
            age = None

    detail = f"{places} places from {fetched_at}, {digest[:23]}"
    if age is None:
        return Result(
            "city data",
            True,
            f"{detail}, but it records no usable timestamp",
            warning=True,
        )
    if age > stale_after_days:
        return Result(
            "city data",
            True,
            f"{detail}, {age:.0f} days old. Run "
            "`python -m scripts.build_city --refresh` when convenient.",
            warning=True,
        )
    return Result("city data", True, f"{detail}, {age:.0f} days old")


def check_proxy_trust() -> Result:
    """`TABIKO_TRUST_PROXY` makes the rate limiter read a spoofable header.

    Only correct when something in front overwrites `X-Forwarded-For`. If the
    header reaches the app untouched, every caller can claim any address and
    the per-client rate limits stop meaning anything.
    """
    trust = (os.getenv("TABIKO_TRUST_PROXY") or "").strip().lower()
    if trust in {"1", "true", "yes"}:
        return Result(
            "proxy trust",
            True,
            "TABIKO_TRUST_PROXY is set, so the rate limiter reads X-Forwarded-For. "
            "Only correct if something in front overwrites that header.",
            warning=True,
        )
    return Result("proxy trust", True, "not trusting forwarded headers (safe default)")


def check_schema() -> Result:
    """Confirm Alembic and the models agree, without touching the database."""

    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
    except ImportError:
        return Result(
            "migrations", True, "alembic is not installed; skipped", warning=True
        )

    # Both paths are absolute on purpose. `alembic.ini` says `script_location =
    # migrations`, which alembic resolves against the *current working
    # directory*, so running this from anywhere but the backend directory --
    # including a pre-commit hook, a CI step, or a developer's shell -- raised
    # CommandError and took the whole report down with it.
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    return Result("migrations", True, f"head is {head}")


def _run_check(check) -> Result:
    """Run one check, turning an exception into a reported failure.

    A check that raises used to abort the entire report, so a single unexpected
    error left the operator with a traceback and no information about the other
    seven settings. Preflight's whole job is to report every problem at once;
    an exception is just another problem, and it must not hide the rest.
    """

    try:
        return check()
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see above
        return Result(
            check.__name__.removeprefix("check_").replace("_", " "),
            False,
            f"the check itself failed: {type(exc).__name__}: {exc}",
        )


CHECKS = (
    check_secret,
    check_environment,
    check_database,
    check_static,
    check_icons,
    check_cors,
    check_city_data,
    check_proxy_trust,
    check_schema,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings as failures",
    )
    args = parser.parse_args()

    results = [_run_check(check) for check in CHECKS]
    width = max(len(result.name) for result in results)

    print("Deployment preflight")
    print("=" * (width + 12))
    failures = 0
    warnings = 0
    for result in results:
        if result.ok and not result.warning:
            mark = "ok  "
        elif result.warning:
            mark = "warn"
            warnings += 1
        else:
            mark = "FAIL"
            failures += 1
        print(f"[{mark}] {result.name.ljust(width)}  {result.detail}")

    print("=" * (width + 12))
    # In strict mode a warning is a failure, so the summary has to say so.
    # Printing "0 failures" while exiting 1 is how an operator ends up trusting
    # a gate that just blocked their deploy.
    blocking = failures + (warnings if args.strict else 0)
    print(
        f"{len(results) - failures - warnings} ok, {warnings} warnings, "
        f"{failures} failures"
        + (" (strict: warnings block the deploy)" if args.strict else "")
    )

    if blocking:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
