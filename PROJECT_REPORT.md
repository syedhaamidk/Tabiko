# Tabiko — Project Report

**A food-discovery app for Bengaluru**, built on OpenStreetMap data.

| | |
|---|---|
| Report date | 2026-09-27 |
| Repository | `tabiko/` (own git repository, 6 commits, clean tree) |
| Tracked files | 133 |
| Backend tests | 283 passing |
| Frontend tests | 100 passing |
| Places in the database | 7,683 |
| Launch command | `docker compose up -d --build` |

---

## 1. What the application is

Tabiko helps someone decide where to eat, right now, near them. It is not a
review site and not a directory. The three things it does that a map app
normally does not:

- **It tells you the truth about its own coverage.** Every filter option carries
  a live count of how many places match it. Twenty-two options currently match
  nothing and are labelled "none yet" rather than hidden or faked.
- **It does not show you a map with nothing on it.** If you turn location off,
  cards disappear and you are treated as a first-time visitor, rather than being
  shown 7,000 undifferentiated results.
- **Directions never leave the app.** There is no "open in Google Maps" button.
  The route is drawn in-app over the same vendored geometry the map uses.

The brand is the word **Tabiko** and nothing else. No emoji labels anywhere in
the interface; the icon set is a hand-built inline SVG set.

---

## 2. Frameworks and tooling

### Backend

| | |
|---|---|
| Language | Python 3.12+ (3.14.2 in the local virtualenv) |
| Web framework | FastAPI 0.136.3 |
| ASGI server | Uvicorn 0.49.0 (`uvicorn[standard]`, uvloop) |
| ORM | SQLAlchemy 2.0.51 |
| Data validation | Pydantic 2.13.4 |
| Migrations | Alembic ≥1.13 |
| Auth tokens | PyJWT ≥2.9 |
| Password hashing | bcrypt ≥4.2 |
| Email validation | email-validator ≥2.2 |
| HTTP client | requests 2.32.5 |
| Database | SQLite (WAL mode). PostgreSQL driver available but unsupported for city builds |
| Tests | pytest ≥8.3, httpx2 |
| Lint / format | ruff ≥0.12 |

### Frontend

| | |
|---|---|
| Language | JavaScript (ES modules), JSX |
| UI library | React 18.3.1 |
| Map engine | Leaflet 1.9.4 via react-leaflet 4.2.1 — **used as a renderer only** |
| Build tool | Vite 7.3.6 |
| Tests | Vitest 5.0.2, Testing Library (react, jest-dom, user-event), jsdom 26 |
| Coverage | `@vitest/coverage-v8` |
| PWA | Hand-written manifest, service worker, and a Node script that rasterises the PNG icons at build time |

### Infrastructure

| | |
|---|---|
| Container | Dockerfile, two stages: Node builds the frontend, Python runtime serves it |
| Entrypoint | `docker/entrypoint.sh` — preflight, build city if empty, migrate, serve |
| Orchestration | `docker-compose.yml` with a named volume for the database |
| CI | GitHub Actions, 4 jobs |
| Line endings | `.gitattributes` pinning LF (see §8, bug 1) |

**On Leaflet:** the summary usually given of this project is "the map is
self-drawn". That is true of the *basemap* and misleading about the engine.
Leaflet is the rendering surface; what was removed is the **tile provider**.
The app fetches no map tiles from anyone. It renders GeoJSON geometry vendored
into the repository, styled per cuisine, which means no API key, no per-request
cost, and no third party between the user and the map.

---

## 3. Architecture

```
tabiko/
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI app, all read endpoints, security headers
│   │   ├── models.py          7 tables
│   │   ├── schemas.py         Pydantic request/response contracts
│   │   ├── database.py        engine, WAL pragmas, session factory
│   │   ├── auth.py            signing-secret guard, access + refresh tokens
│   │   ├── ratelimit.py       fixed-window per-client limiter
│   │   ├── place_index.py     in-memory projection of the city for map reads
│   │   ├── classifier.py      OSM tag → cuisine / venue type / theme
│   │   ├── craving_search.py  TF-IDF ranking over dish and review text
│   │   ├── trust.py           review verification tiers
│   │   ├── schemas/           filter vocabularies
│   │   └── ingestion/
│   │       ├── overpass_ingest.py   Overpass query, tiling, upsert
│   │       └── snapshot.py          the reproducibility pin
│   ├── migrations/versions/   6 migrations
│   ├── scripts/               preflight, build_city, load_probe, storage_probe
│   ├── data/                  osm_snapshot.json.gz + city_provenance.json
│   └── tests/                 19 files, 283 tests
├── frontend/
│   ├── src/                   39 files
│   ├── scripts/               4 build scripts (map data + PWA icons)
│   └── public/data/           vendored basemap geometry
├── docker/entrypoint.sh
├── Dockerfile
├── docker-compose.yml
└── .github/workflows/ci.yml
```

`backend-2/` is a deliberately retained, documented archive of an earlier feature
draft. It is superseded and must not be run as a second service.

---

## 4. The data

### Provenance

Every row records `source = "overpass"`. The city was fetched from the
OpenStreetMap Overpass API on **2026-09-27** and the raw response is committed
to the repository as `backend/data/osm_snapshot.json.gz` (349 kB gzipped,
2.0 MB raw, 7,890 elements).

**The bounding box is pinned to `12.75, 77.45, 13.15, 77.80`** — this is the
area the original hand-built database came from, not a value chosen later.

### Coverage

| Measure | Count | Share |
|---|---|---|
| Places | 7,683 | 100% |
| With an address | 7,683 | 100% |
| With a cuisine label | 7,683 | 100% |
| — of which from a real OSM `cuisine` tag | 3,119 | 40.6% |
| — of which derived from the venue tag | 4,564 | 59.4% |
| With accessibility flags | 1,143 | 14.9% |
| With dietary flags | 672 | 8.7% |
| With occasion ("good for") tags | 286 | 3.7% |
| OSM nodes / ways / relations | 7,413 / 269 / 1 | |
| Distinct cuisine strings | 109 | |
| **Dishes** | **0** | |
| **Reviews** | **0** | |
| **Users** | **0** | |

`raw_cuisine_tag` is deliberately left **empty** on derived rows, so a derived
value can never be mistaken for something OpenStreetMap actually said.

### What is not in the data, stated plainly

- **No menu data anywhere.** OSM carries none. Google Places does not return
  dish items. Scraping an aggregator is not something this project will do.
- **No reviews and no dishes**, so the craving radar has no dish text to rank.
- **9 of 11 occasion filters match nothing.** Only `outdoor` and `quick_bite`
  are populated. Filling the rest needs OSM tags the importer does not capture,
  or dish and review text that only readers can supply.
- **Cuisine for 59% of places is inferred**, not sourced.

---

## 5. API surface

30 endpoints. `/api` prefix in production, stripped by middleware so
development and production agree.

### Core
```
GET    /                                    SPA shell (production)
GET    /health                               readiness
GET    /health/live                          liveness (container healthcheck)
GET    /stats                                real counts, no invented numbers
GET    /filter-options                       every filter vocabulary + per-option counts
GET    /restaurants                          cards, with proximity + search
GET    /restaurants/{id}                     place detail
GET    /restaurants/points                   map points for the current viewport
```

### Authentication
```
POST   /auth/register                        rate limited: 5/min
POST   /auth/login                           rate limited: 10/min
POST   /auth/refresh                         rate limited: 30/min
POST   /auth/logout                          revoke one session, idempotent
GET    /auth/me
PATCH  /auth/me
```

### Reader-generated content
```
GET    /restaurants/{id}/dishes
POST   /restaurants/{id}/dishes              add one dish
POST   /restaurants/{id}/dishes/bulk         paste a whole menu
PATCH  /restaurants/{id}/confirm-menu
GET    /restaurants/{id}/stats
GET    /restaurants/{id}/theme               cuisine-aware design tokens
POST   /reviews
GET    /reviews/restaurant/{id}
GET    /reviews/flagged                      admin queue
PATCH  /reviews/{id}/moderation              admin flag/restore
```

### Saved places and search
```
GET    /favorites
PUT    /favorites/{id}                       idempotent
DELETE /favorites/{id}                       idempotent
GET    /favorites/places                     shortlist as full card records
GET    /search/craving?q=                    TF-IDF ranking, reports unmatched terms
```

### Build tooling (not part of the served app)
```
python -m scripts.preflight                   deployment gate
python -m scripts.build_city                 build the city from the snapshot
python -m scripts.build_city --verify        diff a rebuild against live
python -m scripts.build_city --refresh       fetch current OSM, rewrite the pin
python -m scripts.load_probe                 throughput measurement
python -m scripts.storage_probe              memory footprint
```

---

## 6. Database

7 tables, 6 migrations, currently at `0006_dish_contributors`.

| Migration | Adds |
|---|---|
| `0001_initial_schema` | Restaurants, dishes, reviews |
| `0002_auth_profiles` | Users, reviewer profiles, experience fields |
| `0003_venue_types` | Widened venue-type vocabulary (table recreated via `batch_alter_table`) |
| `0004_favorites` | Saved places, unique on (user, restaurant) |
| `0005_refresh_tokens` | Revocable sessions |
| `0006_dish_contributors` | `dishes.added_by_user_id`, `dishes.created_at` |

### Performance work

- **WAL mode + `synchronous=NORMAL` + 32 MB cache.** Write throughput went from
  **332 writes/s to ~24,000 writes/s**, measured.
- **A `_Ranked` NamedTuple projection** replaces full ORM instances on the
  proximity path.
- **`place_index.py`** holds an in-memory projection of the city for map reads,
  tested filter-by-filter against the SQL to make sure the two cannot disagree.
- **Viewport-based map fetching.** A city-wide map request was 1.19 MB and
  194 ms; fetching only the visible padded bounding box is **103 KB and 11 ms**.

### Index design notes worth knowing

- `dishes` is unique on `(restaurant_id, name)` so a menu cannot hold the same
  dish twice.
- `dishes.added_by_user_id` is `ON DELETE SET NULL`, **not** `CASCADE`. Deleting
  an account must not delete a menu other readers now rely on; the dish becomes
  unattributed and the UI says nothing rather than crediting nobody.
- `favorites` is unique on `(user_id, restaurant_id)`, which is what makes saving
  idempotent.

---

## 7. Features built and verified

### Discovery
- Map and cards driven by **one filter object**, so they cannot disagree about
  which places match.
- **Proximity search**: `origin_lat/origin_lon`, `radius_m`, `sort=distance`.
  Haversine in Python with a bounding-box pre-filter. A total count is returned
  in `X-Total-Count`. A radius without an origin is a 422, not a silent 200.
- **Place search** on name and address, debounced at 300 ms.
- **Craving search** over dish and review text with TF-IDF. Reports
  `unmatched_terms` and leads with them rather than presenting a confident
  ranking of irrelevant places. A query of only unknown terms returns nothing.
  Cached index: 6,213 ms cold before, **735 ms cold / ~35 ms warm** after.
- **Cards do not appear when location is off.** The reader is treated as a
  first-time visitor.
- **Every filter option shows its real count.**

### Map
- Two scales with a hard hand-off at zoom 14.5: city arterials below,
  neighbourhood detail above. No tile requests to any provider.
- In-app routing drawn over the same vendored geometry.
- Cuisine-aware theming, 8 palettes.

### Reader accounts
- Registration, login, profile, short-lived access token (30 min) plus a
  revocable rotating refresh token (30 days, only the digest stored).
- Rotation means a stolen refresh token is usable at most once. Replaying a
  spent token outside a 30-second grace window is treated as theft and revokes
  **every** session for that user.
- Client refreshes transparently on a 401, with a shared in-flight promise so two
  components cannot rotate the same token out from under each other.
- **Saved places** with an optimistic toggle, plus a shortlist view.

### Contributing a menu
Built because the menu layer is empty and there is no legitimate bulk source.

- The **empty state is an invitation**: a signed-in reader is offered a way to
  fill it; a signed-out reader is told why they cannot, and gets no dead button.
- **A whole menu goes in one request.** `POST /dishes/bulk` takes pasted text,
  one dish per line, tags after a comma. Duplicates are *reported*, not raised —
  a pasted list overlapping the existing menu is the normal case, and rejecting
  the batch would discard the new dishes along with the old ones.
- **Every dish records who typed it in**, and the contributor is credited on
  read. A verified critic is marked as such.
- Adding any dish clears the place's `menu_last_confirmed`, because a menu that
  just changed is not a freshly confirmed one. The UI re-reads rather than
  leaving a stale claim.
- Bulk entry has its own rate limit (20/min) and an 80-dish ceiling, because it
  is the one write a reader can repeat.

### Offline
- Manifest, service worker, programmatically rasterised PNG icons generated at
  build time.
- **`/api` is never cached.** Navigations fall back on a non-ok response *and*
  on a network failure. Build assets are precached from `index.html`.
- Hashed assets served `immutable`; the service worker and manifest deliberately
  are not, so a deploy cannot strand readers on the previous bundle.

---

## 8. Security

| Control | Detail |
|---|---|
| Signing secret | The app **refuses to import** without a real `TABIKO_JWT_SECRET` of at least 32 characters |
| Development opt-in | `TABIKO_ENV=development` is the *only* way to use the published dev secret, and preflight fails on it in a deployment |
| Passwords | bcrypt |
| Rate limiting | 10 logins/min, 5 registrations/min, 30 refreshes/min, 20 bulk dish writes/min, per client |
| Sessions | Rotating refresh tokens, digests only, replay detection, per-user mass revocation |
| CORS | A wildcard origin is refused; unset is fine for a same-origin deployment |
| Headers | CSP, `no-store` on auth routes, `X-Content-Type-Options`, `X-Frame-Options`, and related |
| Proxy trust | Off by default, because trusting `X-Forwarded-For` when nothing overwrites it makes rate limits meaningless |
| SQL | Parameterised throughout; no string-built SQL |

**Rate limiting is per process.** With 4 workers the effective limit is 4× the
configured value. Documented rather than hidden; a shared counter needs a shared
store.

---

## 9. Testing

### Backend — 283 tests across 19 files

| File | Tests | Covers |
|---|---|---|
| `test_preflight.py` | 36 | The deployment gate itself |
| `test_city_build.py` | 35 | Snapshot round-trip, digest, tiling, diff, target resolution |
| `test_place_index.py` | 26 | In-memory index vs SQL, filter by filter |
| `test_api.py` | 22 | Endpoint contracts |
| `test_dish_contributions.py` | 21 | Bulk paste, duplicates, contributor credit |
| `test_sessions.py` | 20 | Token rotation, replay, revocation |
| `test_security.py` | 20 | Secret guard, headers, rate limits, CORS |
| `test_map_points.py` | 15 | Viewport fetching |
| `test_craving_search.py` | 13 | Ranking, unmatched terms, cache |
| `test_favorites.py` | 12 | Idempotent save/unsave |
| `test_tag_matching.py` | 12 | Tag filter correctness |
| `test_static_serving.py` | 12 | SPA fallback, asset caching, API precedence |
| `test_proximity.py` | 11 | Distance maths, radius validation |
| `test_filter_options.py` | 11 | Counts and vocabularies |
| `test_ingestion.py` | 10 | Upsert semantics, re-ingestion |
| `test_classifier.py` | 4 | Cuisine derivation |
| `test_stats.py` | 2 | Honest counts |
| `test_migrations.py` | 1 | Schema matches models |

### Frontend — 100 tests across 7 files

| File | Tests |
|---|---|
| `components/RestaurantDetail.test.jsx` | 19 |
| `api.js` | 17 |
| `components/RestaurantCard.test.jsx` | 17 |
| `lib/filterQuery.js` | 15 |
| `lib/clusterPoints.js` | 13 |
| `lib/useUserLocation.js` | 10 |
| `lib/useFavorites.js` | 9 |

**Frontend coverage is roughly 15% of lines.** It is concentrated where the bugs
actually were — filter/query construction, the API layer, card and detail
interaction — and is not a claim of completeness.

### CI — 4 jobs

| Job | What it proves |
|---|---|
| `backend` | Lint, format, 283 tests, migrations match models, and two guards that the app **refuses to import** without a real secret |
| `frontend` | 100 tests, production build, `npm audit --audit-level=high` |
| `docker` | Image builds **and boots**, and the place count is asserted — not just that something answered |
| `snapshot` | A clean checkout builds the city with no network, the count matches the provenance record, and two builds are byte-identical |

---

## 10. Bugs found and fixed

Every one of these was found by running the thing, not by reading it.

### Frontend
| Bug | Effect |
|---|---|
| Unhandled 422 from the map request | Map silently blanked |
| Transparent icon | Invisible affordance |
| Service worker only handled network rejections | A 500 served a cached page and a bad state persisted |
| Missing key in the `FALLBACK` table | Crash on an unmapped value |
| `0.95.toFixed(1)` | 950 m displayed as *shorter* than 951 m |
| Favourites double-tap race | Save/unsave raced and lost writes |
| `addDish`, `createReview`, `updateProfile` used plain `fetch` | Three authenticated writes failed with a 401 on token expiry, skipping the transparent refresh — the one case the session machinery existed for |
| Bulk handler called `db.refresh()` on Pydantic objects | Every batch rolled back. Caught by a test before it reached the running app |

### Backend
| Bug | Effect |
|---|---|
| `_tag_membership` compared an escaped LIKE token to a raw column | `non_veg`, `gluten_free` and **all** accessibility flags were unfilterable |
| Refresh rotation set `revoked_at`, so replay detection could never fire | The theft response was dead code |

### Deployment — found by actually running the container
| Bug | Effect |
|---|---|
| Preflight checked for PWA icons in the frontend **source** tree | The runtime image has no `frontend/` directory, so **every container refused to start** while the icons sat in the built output where a browser would have fetched them. My first fix fell through to the source tree, which let an icon-less build pass |
| `check_schema` resolved `script_location` against the cwd | Running preflight from anywhere but `backend/` raised `CommandError` and destroyed the whole report |
| `--strict` failed a deploy while printing "0 failures" | A gate that reports success on a deploy it just blocked is a gate people learn to ignore |
| `preflight.py` had **zero tests** | The one component whose job is to fail correctly was untested. Now 36 tests |
| No `.dockerignore` | 4,538 files and 101 MB of Windows-built wheels copied into every image |
| `.dockerignore` used `*.db` | Docker's `*` does not cross `/`, so a 1.9 MB database was baked in despite being on the ignore list — the same trap as `.venv`, which the file's own comment described |
| No `.gitattributes` | `core.autocrlf` is `true` on Windows, so a clone gave `entrypoint.sh` 44 CR bytes. A CRLF shebang makes the kernel look for `/bin/sh\r`; the container dies before preflight runs and the build reports no error |
| `build_city` used `Base.metadata.create_all` | `alembic upgrade` hit *"table restaurants already exists"* on any fresh database. Only looked fine locally because an existing database already carried `alembic_version` |
| `build_city` ignored `TABIKO_DATABASE_URL` | Deployed with the database on a volume it reported *"imported 7683 places"* into one file while the service served an empty one from the other: a healthy container showing an empty map |
| My own new `city data` preflight check verified provenance but not the build | The container's check passed against a container with no data. Closed by having the entrypoint build the city |

### Process failures worth recording
- I reported there was no importer. There was — `app/ingestion/overpass_ingest.py`
  was already good. I had looked only in `scripts/` and generalised from that.
- I ran the default build, which replaces the database, **before** running
  `--verify`, destroying the original 7,728-row file I said I would diff
  against. The replacement is fresh, reproducible and slightly smaller.
- I ran a test from the wrong working directory and rebuilt the live database
  instead of the clone's.

---

## 11. Measured performance

One process, 8 concurrent users:

| Endpoint | 1 process | 4 processes |
|---|---|---|
| Map points (viewport) | 91 rps, 82 ms | **285 rps, 23 ms** |
| Card list with distance | 6.6 rps, 1,183 ms | **39 rps, 160 ms** |

| | |
|---|---|
| Craving search, cold | 6,213 ms → **735 ms** |
| Craving search, warm | **~35 ms** |
| City-wide map request | 1.19 MB, 194 ms → **103 KB, 11 ms** |
| SQLite writes | 332/s → **~24,000/s** |
| Memory per worker | ~120 MB (40 MB place index + 47 MB craving index) |
| Docker image | 440 MB → **285 MB**, `/app` at 3.8 MB |
| Frontend bundle | 400 KB JS (124 KB gzip) + 91 KB CSS (21 KB gzip) |
| Basemap payload | 269 KB citywide + 637 KB neighbourhood |

**10,000 simultaneous users is not a code problem.** One process plateaus at
4–5 rps on the card path, bounded by the GIL — 4 threads give zero speedup.
Worker *processes* fix it, and the entrypoint starts one per core. ~16–20 workers
would be needed for 10k simultaneous, plus a load balancer and a CDN. That is
infrastructure to buy.

---

## 12. Deployment

```bash
docker compose up -d --build
```

The image carries the 349 kB snapshot. The entrypoint runs preflight, builds the
city on first boot, migrates, and serves with one worker per core. `down` then
`up` finds the city already on the volume.

`TABIKO_JWT_SECRET` must be set in the environment or `.env`; compose refuses to
start without it, and the service would refuse anyway.

**`TABIKO_DATABASE_URL` is the line that matters.** Without it the database lands
inside the container's own filesystem, so replacing the container discards every
dish, review and account a reader created. The compose file points it at a volume.

### Verified end to end
A clean `git clone`, no database present, `docker compose up`:
builds 7,683 places → serves them → container destroyed → recreated → city still
there → zero console errors in a browser.

---

## 13. What is not done

| Gap | Why | What would fix it |
|---|---|---|
| **Menus and reviews are empty** | OSM has no menu data; Places returns no dish items; scraping is off the table | The contribution flow is built and unused. A place-claim flow is the scalable answer |
| **9 of 11 occasion filters match nothing** | OSM tags the importer does not capture | Capture more tags, or dish text from readers |
| **Cuisine is inferred for 59% of places** | That is what OSM contains | Only a better source |
| **No venue photos** | Needs a Google Places or Mapillary key | A key, then an imagery integration |
| **City map shows arterials, not every street** | 218,667 highway ways cannot be vendored | A tile provider. Would also unlock city-wide directions |
| **Not built for thousands of concurrent users** | A single process is GIL-bound | Worker processes plus a load balancer and a CDN |
| **Frontend coverage ~15%** | Effort went where the bugs were | More tests |
| **No place-claim flow** | Worthless without an audience | Restaurants only claim a listing worth claiming |
| **SQLite only for the city build** | `build_city` replays into a file | Point the importer at a server |

### The honest bottom line

The application is functionally complete and verified against real data. What it
lacks is **data and users, neither of which is code.** The most visible gap is
the empty menu; the most important next step is putting it in front of one real
person, because every remaining feature gets more valuable the moment someone
who is not the author uses it.

---

## 14. Repository history

```
cf38fc3  2026-09-27  Refresh the provenance record for the rebuilt database
e2bb3bc  2026-09-27  One command to deploy, and honour the configured database
66cc222  2026-09-27  Let migrations own the schema, and build the city at container boot
27aae3d  2026-09-27  Make the city reproducible from a clean clone
dd0b2c7  2026-09-27  Pin line endings so the container entrypoint can boot
f3397a2  2026-09-27  Tabiko: food discovery for Bengaluru, first commit
```

Before `f3397a2` the project existed only on one machine: the git root was the
home directory, and none of these 133 files had ever been committed.
