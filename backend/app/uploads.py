"""Uploading and serving reader photos.

Uploads are the classic place for a file-upload vulnerability, so the rules are
strict and each one is there for a reason:

- **The declared `Content-Type` is not believed.** A client can send
  `Content-Type: image/png` with an HTML file inside it. The bytes are checked
  against real magic numbers instead, and a file that is not actually an image
  is rejected.
- **The filename is never used.** A client-supplied name is how path traversal
  happens (`../../etc/passwd`) and how a double extension sneaks past a naive
  check. The stored name is generated from the content's hash.
- **The size is capped while reading, not after.** Reading the whole body and
  then measuring it means the process already paid the memory cost.
- **Re-encoded extensions come from the sniffed type**, not from the upload.

The alternative -- accepting whatever and trusting the browser -- is what turns
a photo feature into a way to serve someone else's script from your origin.

There is no object store in this deployment, so files live on the same volume as
the database. That is the smallest thing that works and it is honest about its
limits: see migration 0008 for what it costs.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

# Ceiling for a single upload. Photographs get compressed by phones; anything
# past this is not a dish photo.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# (magic prefix, sniffed type, extension). Longest prefix first, so a format
# whose signature starts with another's bytes is matched correctly.
_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
    (b"BM", "image/bmp", "bmp"),
)

# WEBP's container is "RIFF" .... "WEBP", so it needs an offset check rather than
# a plain prefix.
_WEBP_HEAD = b"RIFF"
_WEBP_TAG = b"WEBP"


@dataclass(frozen=True)
class StoredImage:
    """Where a stored image ended up, and how to serve it."""

    name: str
    content_type: str
    size: int
    path: Path

    @property
    def url(self) -> str:
        return f"/uploads/{self.name}"


def uploads_dir() -> Path:
    """Resolve the upload directory, defaulting next to the database.

    Defaulting to the database's own directory means a single `TABIKO_DATA_DIR`
    covers both, and the compose file's `/data` volume keeps them together --
    which is what makes one backup of that volume sufficient.
    """

    configured = (os.getenv("TABIKO_UPLOADS_DIR") or "").strip()
    if configured:
        return Path(configured)
    data_dir = (os.getenv("TABIKO_DATA_DIR") or "").strip()
    if data_dir:
        return Path(data_dir) / "uploads"
    from .database import BACKEND_DIR

    return Path(BACKEND_DIR) / "uploads"


def sniff(head: bytes) -> tuple[str, str] | None:
    """Return (content type, extension) for real image bytes, or None.

    Checking the bytes is the whole point. A request that says it is a PNG and
    carries an HTML document is the ordinary case, not an exotic one.
    """

    for magic, content_type, extension in _SIGNATURES:
        if head.startswith(magic):
            return content_type, extension
    if head[:4] == _WEBP_HEAD and head[8:12] == _WEBP_TAG:
        return "image/webp", "webp"
    return None


def store(data: bytes) -> StoredImage:
    """Persist validated image bytes and return where they went."""

    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"That image is {len(data) // 1024} KB. The limit is "
            f"{MAX_UPLOAD_BYTES // 1024} KB."
        )
    if not data:
        raise ValueError("That file was empty.")

    detected = sniff(data[:32])
    if detected is None:
        raise ValueError(
            "That is not a PNG, JPEG, GIF, WEBP or BMP. Those are the only "
            "formats accepted."
        )
    content_type, extension = detected

    # Content-addressed: the same photo uploaded twice is stored once, and the
    # name cannot be guessed from its contents. The random suffix stops two
    # different people uploading the same image from colliding on one path.
    digest = hashlib.sha256(data).hexdigest()
    name = f"{digest[:32]}-{secrets.token_hex(6)}.{extension}"

    directory = uploads_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    # Exclusive create: a name collision must not silently overwrite someone's
    # photo, however unlikely the suffix makes that.
    with path.open("xb") as handle:
        handle.write(data)

    return StoredImage(name=name, content_type=content_type, size=len(data), path=path)


def load(name: str) -> StoredImage | None:
    """Find a stored upload by name, refusing anything that is not a bare name.

    The route parameter is attacker-controlled, so this re-validates rather than
    trusting the caller. A name containing a separator, a `..`, or anything
    outside the generated alphabet resolves to None.
    """

    if not name or "/" in name or "\\" in name or ".." in name or name.startswith("."):
        return None
    if len(name) > 128:
        return None

    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789.-_")
    if not set(name) <= allowed:
        return None

    path = uploads_dir() / name
    if not path.is_file():
        return None

    _, _, extension = name.rpartition(".")
    content_type = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "bmp": "image/bmp",
    }.get(extension.lower(), "application/octet-stream")

    return StoredImage(
        name=name,
        content_type=content_type,
        size=path.stat().st_size,
        path=path,
    )
