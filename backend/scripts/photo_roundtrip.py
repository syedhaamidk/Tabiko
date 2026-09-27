"""Round-trip a real photograph through the running server.

Deliberately a standalone script rather than a test: the point is to prove the
path works against a real uvicorn process with real files on disk, which the
in-process TestClient suite cannot demonstrate. A hand-built PNG is written out,
uploaded over HTTP, attached to a real dish, and fetched back byte for byte.
"""

import hashlib
import json
import struct
import sys
import urllib.error
import urllib.request
import uuid
import zlib
from pathlib import Path

API = "http://127.0.0.1:8010"
EMAIL = "photo-roundtrip@tabiko.in"
PASSWORD = "roundtrip-pass-2026"


def png_bytes(width=48, height=48):
    """A real, decodable PNG built from scratch."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    rows = []
    for y in range(height):
        row = b"\x00"
        for x in range(width):
            # A gradient, so the file is not a flat block and a truncating bug
            # would change the hash.
            row += bytes(((x * 5) % 256, (y * 5) % 256, 180))
        rows.append(row)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def call(method, path, body=None, token=None, raw=None, content_type=None):
    data = (
        raw
        if raw is not None
        else (json.dumps(body).encode() if body is not None else None)
    )
    request = urllib.request.Request(API + path, data=data, method=method)
    if content_type:
        request.add_header("Content-Type", content_type)
    elif data:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers)


def main() -> int:
    failures = []

    def check(label, ok, detail=""):
        print(
            f"  {'OK  ' if ok else 'FAIL'}  {label}{('  ' + detail) if detail else ''}"
        )
        if not ok:
            failures.append(label)

    print("Photo round trip against a real server")
    print("=" * 52)

    # A reader account, created through the real endpoint.
    call(
        "POST",
        "/auth/register",
        {"name": "Photo Tester", "email": EMAIL, "password": PASSWORD},
    )
    status, raw, _ = call("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    token = json.loads(raw).get("access_token")
    check("logged in", bool(token))
    if not token:
        return 1

    # A real restaurant out of the committed city.
    _, raw, _ = call("GET", "/restaurants?limit=1")
    place = json.loads(raw)[0]
    print(f"\n  attaching to: {place['name']} (id {place['id']})")

    image = png_bytes()
    digest = hashlib.sha256(image).hexdigest()
    path = Path("C:/Users/syedh/AppData/Local/Temp/opencode/real-dish.png")
    path.write_bytes(image)
    print(f"\n  wrote a real {len(image)} byte PNG to {path.name}")
    print(f"  sha256 {digest[:40]}")

    print("\n  upload")
    status, raw, _ = call(
        "POST", "/uploads", raw=image, content_type="image/png", token=token
    )
    check("upload accepted", status == 201, f"status {status}")
    if status != 201:
        print(f"    {raw[:200]}")
        return 1
    uploaded = json.loads(raw)
    print(
        f"    -> {uploaded['url']}  ({uploaded['content_type']}, {uploaded['size']} bytes)"
    )

    print("\n  retrieve")
    status, body, headers = call("GET", uploaded["url"])
    check("fetched", status == 200, f"status {status}")
    check("bytes are identical", body == image)
    check("sha256 matches", hashlib.sha256(body).hexdigest() == digest)
    check(
        "served as image/png",
        headers.get("content-type") == "image/png",
        headers.get("content-type", "?"),
    )
    check("nosniff set", headers.get("x-content-type-options") == "nosniff")
    print(
        f"    content-length {len(body)}, cache-control {headers.get('cache-control')}"
    )

    print("\n  the file is on disk")
    stored = (
        Path("C:/Users/syedh/AppData/Local/Temp/opencode/uploads")
        / uploaded["url"].rsplit("/", 1)[1]
    )
    check("stored on disk", stored.is_file(), str(stored.name))
    check("stored bytes match", stored.is_file() and stored.read_bytes() == image)
    print(f"    {stored.stat().st_size} bytes at {stored}")

    print("\n  attach to a real dish")
    status, raw, _ = call(
        "POST",
        f"/restaurants/{place['id']}/dishes",
        {
            "name": f"Round Trip Dosa {uuid.uuid4().hex[:6]}",
            "image_url": uploaded["url"],
        },
        token=token,
    )
    check("dish created", status == 201, f"status {status}")
    if status == 201:
        dish = json.loads(raw)
        check("dish carries the photo", dish["image_url"] == uploaded["url"])
        _, raw, _ = call("GET", f"/restaurants/{place['id']}/dishes")
        listed = [d for d in json.loads(raw) if d["id"] == dish["id"]]
        check(
            "photo survives a re-read",
            listed and listed[0]["image_url"] == uploaded["url"],
        )
        print(f"    dish {dish['id']} '{dish['name']}' -> {dish['image_url']}")

    print("\n  reject a file that lies about its type")
    status, raw, _ = call(
        "POST",
        "/uploads",
        raw=b"<html><script>alert(1)</script></html>",
        content_type="image/png",
        token=token,
    )
    check("html-as-png rejected", status == 422, f"status {status}")
    print(f"    {json.loads(raw)['detail'][:80]}")

    print("\n  reject an image_url that points offsite")
    status, raw, _ = call(
        "POST",
        f"/restaurants/{place['id']}/dishes",
        {
            "name": f"Offsite {uuid.uuid4().hex[:6]}",
            "image_url": "https://example.com/p.gif",
        },
        token=token,
    )
    check("offsite url rejected", status == 422, f"status {status}")

    print("\n  reject path traversal on the fetch route")
    for attempt in ("..%2f..%2f..%2fbackend%2ftabiko.db", "....//tabiko.db", ".."):
        status, _, _ = call("GET", f"/uploads/{attempt}")
        check(
            f"traversal '{attempt[:24]}' refused",
            status in (400, 404),
            f"status {status}",
        )

    print()
    print("=" * 52)
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        return 1
    print("ROUND TRIP CONFIRMED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
