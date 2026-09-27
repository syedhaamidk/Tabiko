"""A committed snapshot of what Overpass returned, and the pin built on it.

Reproducibility here does not come from pinning an Overpass date. It cannot.
The public instances do not keep history: a `[date:"..."]` query against
overpass-api.de for a year ago returns nothing, which is indistinguishable from
a working query over an area with no restaurants. Pinning a date would mean
trusting an answer that cannot be told apart from an empty one.

It also cannot come from re-running the query. The endpoints are free, shared
and heavily rate-limited; a single city-wide query is exactly the shape that
gets a 504, and all three configured mirrors timed out while this was being
written.

So the pin is the payload itself. A gzipped, self-describing JSON envelope is
committed, and rebuilding the city replays it. That makes the build a pure
function of the repository: no network, no rate limit, no clock, and the same
rows every time. Refreshing to newer data is a deliberate act (`--refresh`) that
can fail without breaking anything, because the previous snapshot is still there.

The envelope records the bounding box, when it was fetched, which endpoint
answered, and a digest of the contents, so a diff between two snapshots is
possible without trusting either one's filename.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Bumped only if the envelope's own shape changes, so a loader can refuse a
# snapshot it does not understand rather than misread it.
SNAPSHOT_SCHEMA = 1


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def digest_elements(elements: list[dict[str, Any]]) -> str:
    """A content digest over OSM identities only.

    Deliberately not the whole payload. Tags change, coordinates get corrected,
    and a name gets respelled; none of that means the snapshot is a different
    snapshot. What identifies a snapshot is the *set of OSM objects* in it, so
    this hashes sorted `type-id` pairs and nothing else. Two snapshots with the
    same digest contain the same places, however differently they describe them.

    Attribute drift is a separate question, answered by comparing rows rather
    than by this number.
    """

    identities = sorted(
        f"{element.get('type')}-{element.get('id')}"
        for element in elements
        if isinstance(element, dict)
    )
    joined = "\n".join(identities).encode("utf-8")
    return "sha256:" + hashlib.sha256(joined).hexdigest()


def build_envelope(
    elements: list[dict[str, Any]],
    *,
    bbox: tuple[float, float, float, float] | None = None,
    endpoint: str | None = None,
    fetched_at: datetime | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Wrap raw Overpass elements in a self-describing envelope."""

    return {
        "schema": SNAPSHOT_SCHEMA,
        "bbox": list(bbox) if bbox else None,
        "endpoint": endpoint,
        "fetched_at": (fetched_at or utc_now()).isoformat(),
        "element_count": len(elements),
        "digest": digest_elements(elements),
        "note": note,
        "elements": elements,
    }


def write_snapshot(path: Path, envelope: dict[str, Any]) -> Path:
    """Write the envelope gzipped and deterministically.

    `sort_keys` and a fixed mtime mean re-saving an unchanged snapshot produces
    byte-identical output, so it shows up as no diff instead of churning the
    repository every time the build runs.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

    with gzip.GzipFile(filename="", mode="wb", fileobj=path.open("wb"), mtime=0) as gz:
        gz.write(payload)
    return path


def read_snapshot(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return the elements and the envelope's metadata.

    The recorded digest is re-checked on load. A snapshot whose contents no
    longer match its own header has been truncated or hand-edited, and importing
    it would produce a city that quietly disagrees with the record of itself.
    """

    with gzip.open(path, "rb") as gz:
        envelope = json.loads(gz.read().decode("utf-8"))

    if not isinstance(envelope, dict):
        raise TypeError(
            f"{path} holds a {type(envelope).__name__}, not a snapshot envelope"
        )
    schema = envelope.get("schema")
    if schema != SNAPSHOT_SCHEMA:
        raise ValueError(
            f"{path} has snapshot schema {schema!r}, this build understands "
            f"{SNAPSHOT_SCHEMA}. Refusing rather than misreading it."
        )

    elements = envelope.get("elements")
    if not isinstance(elements, list):
        # ValueError, not TypeError: this is a damaged file, and every other
        # integrity failure below raises ValueError too, so a caller can catch
        # one thing for "this snapshot cannot be trusted".
        raise ValueError(f"{path} has no elements list")  # noqa: TRY004

    recorded = envelope.get("digest")
    actual = digest_elements(elements)
    if recorded and recorded != actual:
        raise ValueError(
            f"{path} is corrupt: header records {recorded}, contents hash to "
            f"{actual}. Refusing to import a snapshot that disagrees with itself."
        )

    metadata = {key: value for key, value in envelope.items() if key != "elements"}
    return elements, metadata


def snapshot_age_days(
    metadata: dict[str, Any], *, now: datetime | None = None
) -> float | None:
    """How old the snapshot is, in days, or None if it does not say."""

    fetched_at = metadata.get("fetched_at")
    if not isinstance(fetched_at, str):
        return None
    try:
        when = datetime.fromisoformat(fetched_at)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    reference = now or utc_now()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return (reference - when).total_seconds() / 86_400
