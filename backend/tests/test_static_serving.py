"""Serving the built frontend from the API process.

Two things are easy to get wrong here and both were wrong at least once while
this was being built, so both are pinned down:

- A catch-all SPA route declared near the top of `main.py` swallows every GET
  endpoint declared below it, because FastAPI matches in registration order. A
  client asking `/restaurants` gets HTML and a 200 instead of JSON.
- Mounting the hashed bundle without a cache header means every reader
  re-downloads it, which is the one thing the hashed names exist to prevent.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

STATIC_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "dist"

pytestmark = pytest.mark.skipif(
    not (STATIC_ROOT / "index.html").is_file(),
    reason="the frontend has not been built",
)


@pytest.fixture
def static_client(monkeypatch):
    """The app with static serving on, so the routes are actually registered."""

    # The env var is read at import time, so the module has to be reloaded with
    # it set rather than patched afterwards.
    monkeypatch.setenv("TABIKO_STATIC_DIR", str(STATIC_ROOT))
    import importlib

    from app import main

    importlib.reload(main)
    from app import database

    importlib.reload(database)
    main.Base.metadata.create_all(bind=database.engine)
    with TestClient(main.app) as client:
        yield client
    monkeypatch.delenv("TABIKO_STATIC_DIR", raising=False)
    importlib.reload(main)


def test_an_api_route_is_not_shadowed_by_the_spa_catch_all(static_client):
    """The bug this file exists for: HTML where JSON was asked for."""

    response = static_client.get("/restaurants", params={"limit": 1})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert isinstance(response.json(), list)


def test_the_api_answers_under_the_prefix_the_client_uses(static_client):
    """The built app hard-codes `/api`; in development that is the Vite proxy.

    Without a matching route in production the client asked for
    `/api/restaurants`, got the SPA shell, and rendered its error state. Dev and
    production have to agree on the prefix.
    """

    for path in ("/api/restaurants?limit=1", "/api/stats", "/api/filter-options"):
        response = static_client.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith("application/json"), path

    assert static_client.get("/api/health/live").json() == {"status": "ok"}


def test_the_prefix_and_the_bare_path_agree(static_client):
    bare = static_client.get("/stats").json()
    prefixed = static_client.get("/api/stats").json()
    assert bare == prefixed


def test_the_prefix_does_not_swallow_the_spa(static_client):
    # A path that merely starts with the letters "api" must still be the shell.
    response = static_client.get("/apiary")
    assert response.headers["content-type"].startswith("text/html")


def test_other_api_routes_still_answer(static_client):
    assert static_client.get("/health/live").json() == {"status": "ok"}
    assert static_client.get("/stats").status_code == 200
    assert static_client.get("/filter-options").status_code == 200


def test_the_shell_is_served_for_the_root(static_client):
    response = static_client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<div id="root">' in response.text


def test_a_client_owned_route_falls_back_to_the_shell(static_client):
    # The client owns its routing, so an unknown path is the shell, not a 404.
    response = static_client.get("/some/deep/route")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_the_shell_is_never_cached_statically(static_client):
    # A cached index.html would leave every reader on the previous bundle.
    assert "no-cache" in static_client.get("/").headers.get("cache-control", "")


def test_the_manifest_and_service_worker_are_served_uncached(static_client):
    for path in ("/manifest.webmanifest", "/sw.js"):
        response = static_client.get(path)
        assert response.status_code == 200, path
        assert "immutable" not in response.headers.get("cache-control", ""), path


def test_hashed_assets_are_cached_hard(static_client):
    assets = sorted((STATIC_ROOT / "assets").glob("*.js"))
    if not assets:
        pytest.skip("no built assets")

    response = static_client.get(f"/assets/{assets[0].name}")

    assert response.status_code == 200
    assert "immutable" in response.headers.get("cache-control", "")


def test_map_data_is_served_from_the_same_origin(static_client):
    # The basemap is our own vector data, which is what makes the app work
    # offline; it has to be reachable without a second host.
    response = static_client.get("/data/citywide.json")

    assert response.status_code == 200
    assert "arterials" in response.json()


def test_a_traversal_cannot_escape_the_build_directory(static_client):
    for path in ("/../app/main.py", "/..%2F..%2Fapp%2Fmain.py"):
        response = static_client.get(path)
        # Either the router rejects it or it falls back to the shell. What it must
        # never do is hand back a source file.
        assert "FastAPI(" not in response.text, path
