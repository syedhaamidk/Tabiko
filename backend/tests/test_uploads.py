"""Photo upload and retrieval, exercised with real files.

Upload is the part of an API most likely to have a hole in it, so the tests are
written around the ways that usually goes wrong rather than around the happy
path:

- a file that lies about its type,
- a filename that tries to escape the upload directory,
- a body large enough to hurt if it is buffered before it is measured,
- an `image_url` that points somewhere other than this service.

The happy path is a real PNG, written byte by byte, uploaded, and fetched back
out over HTTP.
"""

import struct
import zlib

import pytest

from app import uploads


def png_bytes(width=2, height=2, colour=(255, 0, 128)):
    """A genuine, decodable PNG. Hand-built so the test owns the exact bytes."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(colour) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def jpeg_bytes() -> bytes:
    """A JPEG is harder to build by hand, so this is a signature plus padding.

    The sniffer only reads magic numbers, and that is the whole contract being
    tested -- the point is that the *declared* content type is not what decides.
    """

    return b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF\x00" + b"\x00" * 32 + b"\xff\xd9"


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    directory = tmp_path / "uploads"
    monkeypatch.setenv("TABIKO_UPLOADS_DIR", str(directory))
    yield directory


@pytest.fixture
def db_engine_redirect(monkeypatch, db_engine):
    """The upload rate limit writes to `app.database.engine` directly."""

    from app import database as database_module

    monkeypatch.setattr(database_module, "engine", db_engine)
    return db_engine


# ---------- sniffing ----------


def test_a_png_is_recognised():
    assert uploads.sniff(png_bytes()[:32]) == ("image/png", "png")


def test_a_jpeg_is_recognised():
    assert uploads.sniff(jpeg_bytes()[:32]) == ("image/jpeg", "jpg")


def test_a_webp_is_recognised_despite_its_offset_signature():
    assert uploads.sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ("image/webp", "webp")


def test_html_is_not_an_image_however_it_is_labelled():
    """The ordinary case, not an exotic one.

    A browser posting `Content-Type: image/png` with a document inside it is the
    normal shape of a file-upload vulnerability, and trusting the header is what
    turns it into stored XSS served from the app's own origin.
    """

    payload = b"<!doctype html><script>alert(document.cookie)</script>"
    assert uploads.sniff(payload[:32]) is None


def test_a_script_named_png_is_rejected():
    assert uploads.sniff(b"#!/bin/sh\nrm -rf /") is None


def test_an_empty_file_is_not_an_image():
    assert uploads.sniff(b"") is None


# ---------- storing ----------


def test_a_real_png_round_trips_through_the_filesystem(upload_dir):
    original = png_bytes(4, 4)
    stored = uploads.store(original)

    assert stored.path.is_file()
    assert stored.path.read_bytes() == original
    assert stored.content_type == "image/png"
    assert stored.size == len(original)
    assert stored.url == f"/uploads/{stored.name}"


def test_the_stored_name_comes_from_the_content_not_the_client(upload_dir):
    """A client-supplied filename is how path traversal happens."""

    stored = uploads.store(png_bytes())
    assert ".." not in stored.name
    assert "/" not in stored.name
    assert stored.name.endswith(".png")


def test_two_uploads_of_the_same_image_get_different_paths(upload_dir):
    """Same bytes, two files: the random suffix stops a collision overwriting."""

    a = uploads.store(png_bytes())
    b = uploads.store(png_bytes())
    assert a.name != b.name
    assert a.path.read_bytes() == b.path.read_bytes()


def test_a_lying_content_type_is_refused(upload_dir):
    with pytest.raises(ValueError, match="not a PNG"):
        uploads.store(b"<html>nope</html>")


def test_an_empty_upload_is_refused(upload_dir):
    with pytest.raises(ValueError, match="empty"):
        uploads.store(b"")


def test_an_oversized_upload_is_refused(upload_dir):
    padded = png_bytes() + b"\x00" * (uploads.MAX_UPLOAD_BYTES + 1)
    with pytest.raises(ValueError, match="limit"):
        uploads.store(padded)


# ---------- loading ----------


def test_a_stored_image_loads_back(upload_dir):
    stored = uploads.store(png_bytes())
    loaded = uploads.load(stored.name)
    assert loaded is not None
    assert loaded.path == stored.path
    assert loaded.content_type == "image/png"


@pytest.mark.parametrize(
    "name",
    [
        "../../../etc/passwd",
        "..%2f..%2fetc%2fpasswd",
        "sub/dir.png",
        "sub\\dir.png",
        "",
        ".hidden",
        "name with spaces.png",
        "a" * 200 + ".png",
    ],
)
def test_a_traversal_attempt_resolves_to_nothing(upload_dir, name):
    """`name` comes straight off the URL, so it is attacker-controlled.

    Even if a name like this somehow existed on disk, this function must not
    hand it back.
    """

    assert uploads.load(name) is None


def test_loading_a_name_that_does_not_exist_returns_none(upload_dir):
    assert uploads.load("0" * 32 + "-abcdef123456.png") is None


# ---------- over HTTP ----------


def test_upload_and_serve_over_http(client, upload_dir, db_engine_redirect):
    """The actual round trip, through the API rather than the module."""

    original = png_bytes(3, 3)

    response = client.post(
        "/uploads",
        content=original,
        headers={"Content-Type": "image/png"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["content_type"] == "image/png"
    assert body["size"] == len(original)
    assert body["url"].startswith("/uploads/")

    fetched = client.get(body["url"])
    assert fetched.status_code == 200
    assert fetched.content == original
    # nosniff is what stops a browser treating mismatched bytes as script.
    assert fetched.headers["x-content-type-options"] == "nosniff"
    assert fetched.headers["content-type"] == "image/png"


def test_uploading_needs_an_account(anon_client, upload_dir, db_engine_redirect):
    response = anon_client.post(
        "/uploads", content=png_bytes(), headers={"Content-Type": "image/png"}
    )
    assert response.status_code == 401


def test_uploading_a_non_image_is_refused_over_http(
    client, upload_dir, db_engine_redirect
):
    response = client.post(
        "/uploads",
        content=b"<html><script>x</script></html>",
        headers={"Content-Type": "image/png"},
    )
    assert response.status_code == 422
    assert "PNG" in response.json()["detail"]


def test_serving_a_missing_image_is_404(client, upload_dir, db_engine_redirect):
    assert client.get("/uploads/deadbeefdeadbeef-123456.png").status_code == 404


def test_a_dish_can_carry_a_photo(client, upload_dir, db_engine_redirect, seeded_data):
    uploaded = client.post(
        "/uploads", content=png_bytes(), headers={"Content-Type": "image/png"}
    ).json()

    dish = client.post(
        f"/restaurants/{seeded_data['restaurant_id']}/dishes",
        json={"name": "Ghee Roast Dosa", "image_url": uploaded["url"]},
    )
    assert dish.status_code == 201
    assert dish.json()["image_url"] == uploaded["url"]

    listed = client.get(f"/restaurants/{seeded_data['restaurant_id']}/dishes").json()
    assert any(d["image_url"] == uploaded["url"] for d in listed)


def test_a_review_can_carry_a_photo(
    client, upload_dir, db_engine_redirect, seeded_data
):
    uploaded = client.post(
        "/uploads", content=jpeg_bytes(), headers={"Content-Type": "image/jpeg"}
    ).json()

    review = client.post(
        "/reviews",
        json={
            "restaurant_id": seeded_data["restaurant_id"],
            "rating": 5,
            "text": "Worth the walk, and the dosa is worth the photo.",
            "image_url": uploaded["url"],
        },
    )
    assert review.status_code == 201
    assert review.json()["image_url"] == uploaded["url"]


def test_a_dish_works_fine_with_no_photo(
    client, upload_dir, db_engine_redirect, seeded_data
):
    dish = client.post(
        f"/restaurants/{seeded_data['restaurant_id']}/dishes",
        json={"name": "Idli Sambar"},
    )
    assert dish.status_code == 201
    assert dish.json()["image_url"] is None


# ---------- the image_url is not an arbitrary URL ----------


def test_an_image_url_pointing_offsite_is_refused(
    client, upload_dir, db_engine_redirect, seeded_data
):
    """Otherwise a dish photo is a tracking pixel every menu reader loads."""

    response = client.post(
        f"/restaurants/{seeded_data['restaurant_id']}/dishes",
        json={"name": "Sneaky", "image_url": "https://example.com/pixel.gif"},
    )
    assert response.status_code == 422
    assert "upload endpoint" in response.json()["detail"]


def test_a_data_uri_is_refused(client, upload_dir, db_engine_redirect, seeded_data):
    response = client.post(
        f"/restaurants/{seeded_data['restaurant_id']}/dishes",
        json={"name": "Sneaky", "image_url": "data:image/png;base64,AAAA"},
    )
    assert response.status_code == 422


def test_a_path_to_something_else_on_this_origin_is_refused(
    client, upload_dir, db_engine_redirect, seeded_data
):
    response = client.post(
        f"/restaurants/{seeded_data['restaurant_id']}/dishes",
        json={"name": "Sneaky", "image_url": "/openapi.json"},
    )
    assert response.status_code == 422


def test_a_never_uploaded_path_is_refused(
    client, upload_dir, db_engine_redirect, seeded_data
):
    """Well-formed but absent. The URL has to correspond to a real file."""

    response = client.post(
        f"/restaurants/{seeded_data['restaurant_id']}/dishes",
        json={
            "name": "Ghost",
            "image_url": "/uploads/" + "0" * 32 + "-abcdef123456.png",
        },
    )
    assert response.status_code == 422
    assert "not found" in response.json()["detail"]
