# Tabiko

**Big flavor. Zero boring bites.**

Tabiko is a full-stack Bengaluru food radar:

- a hardened FastAPI + SQLAlchemy backend with authentication, ingestion,
  reviews, trust signals, and migrations;
- a responsive React/Vite frontend with cuisine-aware themes, craving search,
  filters, a map, and review/dish flows.

OpenStreetMap-derived place data is displayed with attribution in the UI.

## Project layout

```text
backend/                  Maintained API and tests
  app/                    FastAPI, auth, search, trust, ingestion, themes
  migrations/             Alembic migrations
frontend/                 React 18 + Vite frontend
backend-2/                Archived feature draft; do not run as a service
```

## Backend

From `backend/`:

```bash
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate

pip install -r requirements-dev.txt
alembic upgrade head
```

Optional OSM seed data:

```bash
python -m app.ingestion.overpass_ingest --radius 3000
```

Start the API on port 8010 (port 8000 is already occupied on this machine):

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8010
```

- Health: <http://127.0.0.1:8010/health>
- Swagger UI: <http://127.0.0.1:8010/docs>
- ReDoc: <http://127.0.0.1:8010/redoc>

## Frontend

From `frontend/`:

```bash
npm install
npm run dev
```

Open <http://127.0.0.1:5173>. Vite proxies `/api` to
`http://127.0.0.1:8010`; override with the `BACKEND_URL` environment variable.

```bash
# PowerShell example
$env:BACKEND_URL="http://127.0.0.1:8010"
npm run dev
```

## Main API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/auth/register` | Create an account and return a JWT |
| `POST` | `/auth/login` | Authenticate |
| `GET/PATCH` | `/auth/me` | Read/update the current profile |
| `GET` | `/restaurants` | Search, tag filters, distance sort and radius (paged) |
| `GET` | `/restaurants/points` | Minimal map positions for the whole city |
| `GET` | `/filter-options` | Canonical cuisine / venue / diet / occasion values |
| `GET` | `/stats` | Real headline counts (places, cuisines, reviews) |
| `GET` | `/favorites` | The signed-in reader's saved place ids |
| `GET` | `/favorites/places` | Those saved places as full card records |
| `PUT` | `/favorites/{id}` | Save a place (idempotent) |
| `DELETE` | `/favorites/{id}` | Unsave a place (idempotent) |
| `GET` | `/restaurants/{id}/theme` | Cuisine-aware design tokens |
| `GET/POST` | `/restaurants/{id}/dishes` | List/add dishes |
| `POST` | `/restaurants/{id}/dishes/bulk` | Add a whole pasted menu in one request |
| `PATCH` | `/restaurants/{id}/confirm-menu` | Confirm menu freshness |
| `GET` | `/search/craving?q=...` | Rank venues by text similarity |
| `POST` | `/reviews` | Create an authenticated, idempotent review |
| `GET` | `/reviews/restaurant/{id}` | List non-flagged reviews |
| `GET` | `/reviews/flagged` | Admin moderation queue |
| `PATCH` | `/reviews/{id}/moderation` | Admin flag/restore operation |
| `GET` | `/restaurants/{id}/stats` | Rating/trust aggregates |

Reviews use the authenticated user; clients cannot post as another `user_id`.
Send a stable UUID in `client_request_id` when retrying, so a duplicate
submission returns `409` before it changes aggregates.

### Proximity

`/restaurants` and `/restaurants/points` accept the same parameters, and the UI
sends one filter object to both, so the cards and the map can never disagree:

| Parameter | Meaning |
|---|---|
| `origin_lat`, `origin_lon` | Reader's position. Must be sent as a pair. |
| `radius_m` | 1–50000. Only valid with an origin. |
| `sort` | `name` (default) or `distance`. `distance` requires an origin. |
| `search` | Case-insensitive match on name or address. |

With an origin, rows are ordered by real distance and `distance_m` is returned on
each record. `X-Total-Count` carries the full match count so the UI can say
"142 places match" without paging everything. Violations are `422`, not silently
ignored — a radius that quietly did nothing would be worse than an error.

A `checked_in` tier is granted only when submitted device coordinates are within
150 metres of the venue. This is device-reported proximity, not cryptographic
proof of presence. Client-claimed `order_confirmed` tiers are downgraded until a
receipt flow exists.

## Configuration

```text
TABIKO_DATABASE_URL=sqlite:///./tabiko.db
TABIKO_AUTO_CREATE_SCHEMA=false
TABIKO_ENV=production
TABIKO_JWT_SECRET=replace-with-a-long-random-secret
TABIKO_ADMIN_EMAILS=you@example.com
TABIKO_API_KEY=optional-moderation-service-key
TABIKO_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
TABIKO_OVERPASS_URL=https://overpass-api.de/api/interpreter
TABIKO_USER_AGENT=tabiko/0.5 (Bengaluru food radar; contact@example.com)
TABIKO_LOGIN_RATE_LIMIT=10
TABIKO_REGISTER_RATE_LIMIT=5
TABIKO_REFRESH_RATE_LIMIT=30
TABIKO_TRUST_PROXY=false
TABIKO_ACCESS_TOKEN_SECONDS=1800
TABIKO_REFRESH_TOKEN_DAYS=30
TABIKO_REFRESH_GRACE_SECONDS=30
TABIKO_STATIC_DIR=./static
```

- `TABIKO_JWT_SECRET` **must** be set to at least 32 random characters outside
  local development; the app refuses to start without it. Generate one with
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- `TABIKO_ENV=development` permits the published dev secret. Never set it in a
  deployment.
- Emails in `TABIKO_ADMIN_EMAILS` receive `is_admin=true` at registration.
- `TABIKO_API_KEY`, when set, additionally protects admin moderation routes.
- `TABIKO_TRUST_PROXY=true` makes the limiter read `X-Forwarded-For`. Only correct
  when something in front overwrites that header.
- `TABIKO_STATIC_DIR` serves a built frontend from the API, so the app and the API
  share an origin. A path that does not exist is a startup failure, not a warning.
- `TABIKO_ACCESS_TOKEN_SECONDS` is how long a bearer token lives. Short is the
  point; the client refreshes transparently.
- Use Alembic for schema changes; `create_all` is only for disposable databases.
- PostgreSQL users should install `backend/requirements-postgres.txt`.
- Copy `backend/.env.example` to `backend/.env` for the full list; `.env` is gitignored.

### A note on API keys

Any key must stay server-side. Vite inlines every `VITE_*` variable into the
client bundle, so a key placed in frontend code (or a `VITE_` prefixed variable)
is readable by anyone who loads the page. Third-party map and imagery keys
belong in `backend/.env` and should be proxied through the API.

No map key is required today. The frontend draws its own basemap from vendored
OpenStreetMap geometry and makes zero tile requests.

## Frontend design

The UI is a loud, maximal street-festival system built around a custom Tabiko
SVG mark and two original icon sets: cuisine glyphs for places and a Tabiko
interface icon set (`InterfaceIcon`) for every control, chip, badge, and empty
state. No emoji are used in the product surface. Every restaurant receives a
deterministic icon, color pair, and pattern combination across cards, detail
pages, and map markers.

Filters use a custom accessible listbox (`InterfaceSelect`) instead of a native
`<select>`, so the popup can be themed. It supports Arrow/Home/End navigation,
Enter/Space to commit, Escape to cancel, Tab to dismiss, outside click to close,
and a leading "Any …" entry that resets the filter. Each option carries its own
icon, and the trigger exposes `role="combobox"` with `aria-activedescendant`.

The map is drawn by Tabiko itself. There is no tile provider, no API key, and
no runtime network request for the basemap: real OpenStreetMap geometry for the
neighborhood is vendored into `frontend/src/data/neighborhoodMap.json` and
rendered as styled vector layers on a blank Leaflet canvas, so both themes are
genuinely our own drawing rather than a recolored tile set.

Regenerate the geometry after moving to a new area:

```bash
cd frontend
node scripts/build-neighborhood-map.mjs
node scripts/build-neighborhood-map.mjs --center 12.9784,77.6408 --span 0.011,0.013
```

The script fetches roads, water, green space, and land use from Overpass,
applies Douglas–Peucker simplification per road class, drops tiny fragments,
and keeps the result around 40 KB. Because the data is ODbL-derived, the map
renders an OpenStreetMap attribution control.

Both themes — **Sunset** and **After dark** — recolor the drawn layers live, and
the header legend is generated from the current result set, so the cuisine key
and counts always match the visible places instead of a static list.
Landmarks and street labels fade in above zoom 15.4, and landmarks within 70 m
of a Tabiko marker are suppressed so pins never double-draw.

### In-app directions

Directions are computed inside Tabiko and never hand the user off to a
third-party maps app. `frontend/src/lib/routePlanner.js` builds a walkable
routing graph from the same vendored streets the map draws, so the route line
and the visible streets can never disagree.

- Open a marker's popup and choose **Directions** to walk from the current map
  centre, or use **Start from my location** to route from the device position
  (permission is only requested after an explicit click, and declining falls
  back to the map centre with an explanation).
- Cost weights per road class push routes onto footpaths and quiet lanes rather
  than main roads, and the result is distance, walking time, and turn-by-turn
  steps with compass headings.
- The route is drawn in the active theme and the map fits to it. Filtering the
  destination out clears the route instead of leaving a stale line.

Walking directions only work **inside Rajajinagar**, the one area with vendored
street-level geometry. A place elsewhere in the city gets a clear explanation
rather than a silent failure. City-wide directions would need a routing graph
for all of Bengaluru, which is the same data limit described under the map
above.

Two details make this work on simplified geometry:

1. **Coordinate order.** Vendored data is `[lat, lon]` to match the rest of the
   app, but GeoJSON requires `[lon, lat]`. The conversion happens in one place
   (`toGeoJsonPoint` in `MapView.jsx`); getting it wrong silently drops every
   layer off-screen because Leaflet reads the values in the wrong hemisphere.
2. **T-junction detection.** Simplification drops the shared vertex where one
   street ends on another, so a rendered network can look connected while being
   many separate pieces. `buildStreetGraph` snaps nodes onto nearby street
   segments to rebuild those crossings. The 30 m radius is measured, not
   guessed: 14 m leaves about 7% of real place-to-place pairs unroutable, and
   30 m connects every pair in a 435-pair test.

The graph is built lazily on the first route request (~44 ms) and cached.
Routing uses a binary-heap Dijkstra, which took queries from ~101 ms average to
~1.3 ms on the denser network.

Because routing depends on junction vertices surviving simplification, the build
script defaults to a tighter tolerance scale. `--tolerance-scale` trades payload
size against routing fidelity:

```bash
node scripts/build-neighborhood-map.mjs --tolerance-scale 0.35
```

The basemap is served from `public/data/neighborhoodMap.json` rather than
imported, so ~620 KB of geometry stays a separately cacheable request instead of
inflating the JavaScript bundle. `--max-buildings` and `--min-building-area`
control how many building footprints are kept, since a dense city has tens of
thousands of them.

### Filters

The five filter menus are generated from `GET /filter-options` rather than a
hand-typed list, so the UI can never offer a value the API would reject:

- `cuisine` comes from `classifier.CANONICAL_CUISINES` — the only labels the
  classifier can ever store.
- `type_tag` comes from the `RestaurantType` enum, which is why adding a venue
  type needs an enum change *and* the `0003_venue_types` migration.
- `dietary`, `good_for` and `accessibility` come from the matching
  `schemas.*` tuples.

**Every option publishes a count.** A vocabulary is a promise, and 22 of the 51
values the menus advertised could never match anything:

| Group | Reachable | Never matches |
|---|---|---|
| Cuisine | 17/20 | Tiffin, Arabian & Lebanese, African |
| Place | 5/13 | fine dine, cloud kitchen, canteen, dhaba, street stall, hotel restaurant, takeaway, unclassified |
| Diet | 5/7 | egg, gluten free |
| Good for | 2/11 | date, solo, group, family, work, late night, pet friendly, budget, live music |
| Access | 3/3 | — |

An option at zero is shown as "none yet" and struck through rather than hidden.
Dropping it would hide the fact that the data does not cover it, and the
vocabulary is canonical — a reader looking for a gap should be able to see it.
Counts are city-wide and unfiltered by design: recomputing them per active filter
would make the number under a reader's finger change as they narrow, and costs a
scan per render.

`tests/test_filter_options.py` asserts that every advertised count equals the
number of rows the corresponding filter actually returns, for every value in
every group. That invariant is what caught the escaping bug below.

**Access is a filter now.** 1,327 places carried `wheelchair_accessible`,
`not_wheelchair_accessible` or `seating` with no way to ask for them. Promoting
`schemas.ACCESSIBILITY_FLAGS` to a filter group makes that data reachable.

### Tag matching

These fields hold several comma-separated tags in one string, so filtering means
"contains this whole tag", anchored so `veg` cannot match `vegan` and `%, %` is
not a match-all.

The equality branch compares the **unescaped** value; LIKE escaping applies only
to the wildcard patterns. Reusing the escaped token made every value containing
an underscore unmatchable no matter what was stored — so `non_veg`,
`gluten_free` and all three accessibility flags were silently dead, and the
counts in `/filter-options` disagreed with what the filters returned.
`tests/test_tag_matching.py` covers the escaping, the prefix trap, spaced
separators, case-insensitivity and wildcards.

The frontend only supplies the display `label` and `icon` for each value, and
keeps a bundled fallback list so filtering still works if the request fails.
`tests/test_filter_options.py` asserts that every advertised value is accepted
by the `/restaurants` filters, that the classifier never emits a cuisine outside
the canonical list, and that an unknown venue type is still rejected.

Menus with more than a handful of entries get a search field; typing filters the
list, `Escape` clears the query, and the highlighted option still resolves to
the right value in the filtered list.

### Search, proximity and saved places

Three additions on top of the filter menus, all sharing the single filter object
described under [Proximity](#proximity):

- **Place search** matches names and addresses, debounced at 300 ms, and reports
  the real match count from `X-Total-Count`. It is separate from the craving
  radar on purpose: that ranks venues by the text of their dishes and reviews,
  this finds the thing you can actually name.
- **Radius and order** are opt-in. "Anywhere" and A–Z stay the default, because
  having loaded the whole city, only a reader who asks for a radius should lose
  the rest. Both are disabled until the browser grants a position, and requesting
  one happens on a click rather than on page load.
- **Saved places** are a personal shortlist, not a filter over the current page —
  a saved place is usually nowhere near the page that happens to be loaded, so
  `GET /favorites/places` serves it from the database. Saving is optimistic and
  rolls back on failure, and both `PUT` and `DELETE` are idempotent so a double
  tap can neither duplicate a row nor raise a `404`.

The location gate still wraps the cards in the saved view. That is a deliberate
constraint: cards never appear while location is off, in any view.

### Offline

The app is installable and its map works with no connection, which is only
possible because the basemap is our own vector data rather than a tile server.
`frontend/public/sw.js` precaches the shell, the content-hashed build assets
(discovered from `index.html`, since their names change every build) and both map
payloads on install.

Three rules, in priority order:

1. **`/api` is never cached.** Places, saved places and reviews all change, and a
   stale "3 spots near you" is worse than an honest error.
2. **Navigations fall back to the cached shell on a non-ok response as well as a
   network failure**, because a gateway or captive portal can answer with a real
   `502` rather than rejecting the request.
3. **Build assets are cache-first**, which is safe because their URLs are
   content-hashed.

Regeneration is `npm run icons`, which also runs as part of `npm run build`. The
icons are rasterised directly by `frontend/scripts/build-pwa-icons.mjs` using
signed distance fields in the same 64-unit design space as `BrandMark.jsx`, so
there is one geometry rather than two drawings that can drift.

### Two map scales

The map draws at two scales and hands over between them at **zoom 14.5**, so the
two layers are never drawn on top of each other:

| Layer | Zoom | Contents | Payload |
|---|---|---|---|
| City overview | below 14.5 | 2,277 arterial ways (motorway→secondary), 696 water bodies, 410 green spaces, 220 locality labels | 263 KB (58 KB gzip) |
| Neighborhood detail | 14.5 and in | 1,883 streets, 4,000 buildings, 55 parks, 30 named roads | 622 KB (119 KB gzip) |

`MIN_ZOOM` is 11, which frames the whole metropolitan area — the vendored extent
is 53 x 40 km. Panning is bounded to that extent.

Why not the full network: Bengaluru's complete highway layer is **218,667 ways**
(~1.1M points), which is far too much to vendor. The arterial skeleton is 7,705
raw ways and simplifies down to 2,277 at city scale, which is what makes a
self-drawn city map practical at all.

Locality labels are ranked by importance (0 = city … 9 = other) and revealed
progressively: 6 labels at city zoom, 111 at z12.8, all 220 by z13.8. Without
that, names like "DOLLARS COLONY" bury the map.

```bash
cd frontend
node scripts/build-citywide-map.mjs
node scripts/build-citywide-map.mjs --bbox 12.75,77.45,13.15,77.80
```

Both datasets live in `public/data/` and load lazily, so neither inflates the
JavaScript bundle. The city overview is treated as optional: if that request
fails, the map still works at street level.

Two implementation notes worth keeping:

- `MapContainer` only reads map options at creation, and the bounds depend on
  data that arrives later, so `maxBounds` is applied imperatively via
  `BoundsBridge`. Passing it as a prop silently does nothing.
- `ZoomWatcher` needs an explicit `minZoom = 0` default. Without it,
  `zoom >= undefined` is always false and the gated subtree never mounts.

### Data coverage

The seeded area is **all of greater Bengaluru** — bbox `12.75,77.45,13.15,77.80`,
about 44 x 38 km. That yields **7,728 named food venues** from OSM, spanning
12.756–13.150 N and 77.462–77.796 E.

| Filter | Options with results |
|---|---|
| Cuisine | 17 of 20 (Cafe/Bakery 1,771, Regional 575, Desserts & Sweets 469, Italian 372, Chinese 160, South Indian 135, Other Asian 108, North Indian 55, Mexican 47, Continental 33, Seafood 20, Thai 20, Biryani 17, …) |
| Place | 5 of 13 (family restaurant 3,261, cafe 2,234, Darshini/QSR 1,742, bar 438, food court 53) |
| Diet | 5 of 7 (veg 653, vegan 64, halal 42, jain 8, non-veg 2) |
| Good for | 2 of 11 (outdoor 269, quick bite 31) |

`Multi-cuisine` is the honest floor, not a bug: most OSM places carry no
`cuisine` tag, so a restaurant genuinely does not declare one. It is now 4,075
places (52.7%), down from 5,933 (76.8%) before cuisine derivation.

Where OSM is silent, the venue tag is used instead — a `shop=bakery` is a bakery
and `amenity=cafe` is a cafe. This is **derivation, not OSM data**, so
`raw_cuisine_tag` is left empty on those rows and a derived value is never
mistaken for something the source said. It is only applied when the place has no
`cuisine` tag at all, and never overwrites a cuisine already recorded.

Re-seed after changing the taxonomy:

```bash
cd backend
# City-wide, area based. A bbox query is far cheaper than a 25 km `around:`
# radius, which is why --bbox exists.
python -m app.ingestion.overpass_ingest --bbox 12.75,77.45,13.15,77.80 --replace
# Single neighborhood
python -m app.ingestion.overpass_ingest --lat 12.9915 --lon 77.5520 --radius 1200
```

The importer derives the venue type from the OSM amenity/shop tag, not just the
cuisine value. This matters more than it sounds: most places carry no `cuisine`
tag at all, so a cuisine-only classifier left the majority of places as
`unclassified` and gave the venue filter nothing to match. It now maps
`restaurant`/`diner` → family restaurant, `fast_food`/`bbq` → Darshini/QSR,
`bar`/`pub` → bar, `food_court` → food court stall, and the cafe-like shops to
cafe. A re-ingest only upgrades a place that is currently `unclassified`, so
curated or better-evidenced types are never overwritten.

`good_for` is also widened beyond the four original values, and a few
unambiguous OSM tags are mapped onto occasion labels (`outdoor_seating`,
`dog`, `child_friendly`). Nothing is inferred from a place name.

### City-wide markers

Seven thousand places cannot be seven thousand DOM nodes, so the map clusters
them on a zoom-derived grid (`src/lib/clusterPoints.js`):

| Zoom | Rendered |
|---|---|
| 16+ | individual pins (39 in view) |
| 15 / 14 / 13 / 12 / 11 | 51 / 67 / 78 / 73 / 60 cluster bubbles |

Markers come from `GET /restaurants/points`, a deliberately minimal payload:
6 fields instead of a full record. For the whole city that is 170 KB gzipped,
versus roughly 3 MB if the map used `/restaurants` rows. The endpoint takes the
same filters as `/restaurants` so the two can never disagree about what a filter
means, plus an optional bounding box so a zoomed-in view only pays for what it
can show. It is declared before `/restaurants/{restaurant_id}` so `points` is
never parsed as an id.

Cards are unaffected by scale: they fetch one page of 100 rich records at a
time and reveal 48 at a time, so browsing a city-wide result set still costs a
single request until the reader asks for more.

Auto-fit is skipped above 400 results, since fitting a city-wide set would yank
the viewport out to the whole city on every filter change.

### Paging

`/restaurants` caps a page at 100. The client fetches the first page eagerly and
pulls the next one only when the reader presses **Show more places**.

### Location gate

The card list is location-first: it stays hidden until the browser reports a
granted geolocation permission, and a first-time visitor is treated the same as
someone who declined — no cards, plus an explicit **Turn on location** action and
a shortcut to the food map. The permission state is read via
`navigator.permissions` so no prompt fires on page load, and it re-checks if the
user flips the setting in browser UI.

The map is deliberately *not* gated, so browsing every place works without
sharing a location.

Permission and position are separate states on purpose. A granted permission
with a failed GPS fix still shows the full list, because a weak signal should not
hide the whole city — it just falls back to A–Z ordering. Losing permission also
discards the stored fix, so a stale position can never keep driving the sort.

### Craving search

`GET /search/craving` ranks venues by TF-IDF cosine similarity over the text that
actually exists: place names, cuisines and tags, plus dish and review text.

Two constraints, both learned from running it against the real city rather than a
handful of seeded rows:

**The index is cached.** Building it means reading every restaurant, dish and
review. Doing that per query — with `selectinload` rather than lazy loads — cost
**6.2 s** per search once 7,728 places were loaded, against 43 ms for the plain
place search it duplicated. It is now rebuilt only when the corpus row counts
change: **735 ms** cold, **~35 ms** warm. Flagging a review changes the
searchable text without changing any count, so moderation invalidates explicitly.

**It will not answer what it cannot answer.** Most places have no dish or review
text, so a craving like "comfort food" matches nothing. Cosine similarity then
scores the query as just "food" and cheerfully ranks venues named "Food" and
"FOOD COURT". Every result now reports `unmatched_terms` — the query terms with
no occurrence anywhere in the corpus — and the UI leads with that rather than
presenting a confident ranking of irrelevant places. A query of only unknown
terms returns nothing at all.

This is the honest ceiling until real dish and review text exists. The endpoint's
contract is unchanged apart from the added field, so it can be swapped for
embedding search without touching the client.

### Contributing a menu

There are no dishes in the database, and no legitimate bulk source for them:
OpenStreetMap carries no menu data, Google Places returns no dish items, and
scraping an aggregator is not something this project will do. Re-ingesting
cannot fix it.

So the menu layer is built to be filled by the people who actually ate there.
Three things make that possible without a claim or verification system:

**The empty state is an invitation.** A place with no dishes says so plainly and
offers a signed-in reader a way to fill it, rather than showing a shrug. Signed
out it explains why the reader cannot contribute yet. There is no dead button
either way.

**A whole menu goes in at one request.** `POST /restaurants/{id}/dishes/bulk`
takes a pasted block of text — one dish per line, tags after a comma, which is
how a menu is read off a board. Typing twenty dishes through twenty form
submissions is the reason nobody fills one in. The response reports `added` and
`skipped` separately, and duplicates are reported rather than raised: a pasted
list overlapping the existing menu is the normal case, and rejecting the batch
would throw away the new dishes along with the old ones. Case is ignored, a name
repeated inside one paste is collapsed, and a dish with no comma is a name and
nothing else.

**Every dish records who typed it in.** `dishes.added_by_user_id` is credited on
read, so a reader can see a menu was written by a person rather than appearing
from nowhere, and a verified critic is marked as such. The foreign key is `ON
DELETE SET NULL`, not `CASCADE`: deleting an account must not delete a menu other
readers now rely on. The dish becomes unattributed, and the UI says nothing about
its source rather than crediting nobody.

Two consequences worth stating plainly. Adding any dish clears the place's
`menu_last_confirmed`, because a menu that just changed is not a freshly
confirmed one — the UI re-reads the place rather than leaving the stale claim on
screen. And bulk entry is the one write a reader can repeat, so it carries its
own rate limit (20/min) and an 80-dish ceiling per request.

This is the front door to a place-claim flow, not a substitute for one. Claiming
a listing is the only path that scales on its own, and it only works once there
is an audience worth claiming a listing for.

### Performance

Measured on the loaded city (7,728 places) with `backend/scripts/load_probe.py`
and `backend/scripts/storage_probe.py`. Both are closed-loop probes, so throughput
is requests per second from a fixed number of concurrent clients.

**Ranking does not materialise records.** The proximity and map endpoints used to
`SELECT` every column of every candidate, build 7,728 ORM objects, compute
distances, and return 48 rows. Profiling the 142 ms that took:

| Step | Cost |
|---|---|
| `SELECT` all 7,728 as full ORM objects | 88.6 ms |
| `SELECT` all 7,728 as raw rows | 29.1 ms |
| `SELECT` id/lat/lon only | 8.5 ms |
| haversine + sort + page 48 | 15.4 ms |

Ranking now reads six columns into a `NamedTuple`, and the card endpoint re-reads
full records only for the page it returns. The map endpoint needs six fields per
place, so the projection *is* the response and no ORM object is built at all.

**WAL is on.** SQLite's default rollback journal serialises readers against the
writer. Measured with eight concurrent writers on this database:

| Config | Writes/sec |
|---|---|
| `journal=delete`, `synchronous=FULL` (was the default) | 332 |
| `journal=wal`, `synchronous=FULL` | 2,001 |
| `journal=wal`, `synchronous=NORMAL` (now) | 38,678 |

WAL is set in `app/database.py` and degrades quietly on filesystems that cannot
support it.

**What that bought**, `/restaurants?origin=…`:

| Concurrent | p50 before | p50 after | rps before | rps after |
|---|---|---|---|---|
| 1 | 142 ms | 89 ms | 7.0 | 10.8 |
| 8 | 3,394 ms | 1,361 ms | 2.2 | 5.3 |
| 25 | 7,523 ms | 4,532 ms | 1.9 | 4.2 |
| 50 | 100% timeout | 8,457 ms | — | 4.5 |

**What is still the ceiling.** Throughput plateaus at 4–5 rps no matter the
concurrency, and that is the GIL: the same pure-Python distance work at 1, 2 and
4 threads gives 122.6×, 113.7× and 120.7× throughput — four threads buy nothing.
Only worker *processes* help, which is why the deployment answer is several
processes behind a balancer rather than a bigger thread pool.

### The map asks for a viewport, not the city

`/restaurants/points` is now given the visible bounding box, padded by half a
screen on every side, debounced at 400 ms, and rounded to ~1 km so ordinary
panning reuses the response already held. The previous points stay on screen
while a new box loads, so panning never flashes the map empty.

| Request | Payload | Latency |
|---|---|---|
| Whole city | 1,193,425 B | 194 ms |
| Padded viewport | 103,450 B (9%) | 11 ms |

A bounded request is served from `app/place_index.py`, an in-memory projection of
the columns the map returns, rebuilt only when the place table changes. It is a
cache and nothing more: `tests/test_place_index.py` asserts, filter by filter,
that it returns exactly the ids the database would.

### Building the city

The city is a build output, not a hand-made artifact:

```bash
cd backend
python -m scripts.build_city              # build from the committed snapshot
python -m scripts.build_city --verify     # diff a rebuild against the live data
python -m scripts.build_city --refresh    # fetch current OSM, rewrite the pin
```

`backend/data/` holds `osm_snapshot.json.gz` (348 KB, the raw Overpass response)
and `city_provenance.json` (the bbox, the digest, when it was fetched, how many
places it produced). **A clean clone builds 7,683 places with no network, no API
key, and no rate limit** — two builds from one snapshot produce byte-identical
tables, verified by SHA-256 over every row.

**The pin is the payload, not a date.** Two alternatives were tried and rejected
on evidence:

- *A pinned Overpass date.* A `[date:"..."]` query a year old against
  overpass-api.de returns nothing, which is indistinguishable from a working
  query over an empty area. The pin would have been an unverifiable claim.
- *Re-running the query on every deploy.* The endpoints are free, shared and
  rate-limited. While this was being written all three configured mirrors
  returned 504, and a single city-wide query is the shape that gets rate-limited
  — a 4×4 grid of 16 small queries each answered.

Refreshing is therefore a deliberate act that can fail without breaking anything:
`--refresh` only rewrites the snapshot after a complete success, so a failed run
leaves the previous pin working.

`--verify` is the honest check on all of it. It builds into a scratch database
and reports what differs from the live one, separating **identity** drift (places
new or gone, meaning OSM changed) from **attribute** drift (a place's cuisine or
flags changed, meaning this project's derivation changed). Conflating the two
makes both unreadable. It changes nothing.

### Launching

```bash
docker compose up -d --build
```

That is a complete deployment: the image carries the snapshot, the entrypoint
builds the city on first boot, and `docker compose down` followed by `up` finds
the city already on the volume. `TABIKO_JWT_SECRET` must be set in the
environment or `.env`; compose refuses to start without it, and the service
would refuse anyway.

**`TABIKO_DATABASE_URL` is the line that matters.** Without it the database
lands at `/app/tabiko.db`, inside the container's own filesystem, so replacing
the container throws away every dish, review and account a reader created. The
compose file points it at a mounted volume.

Three bugs in this path were found by deploying it rather than reading it, and
all three are now tests:

- `build_city` created its schema with `Base.metadata.create_all`, so `alembic
  upgrade` hit *"table restaurants already exists"* on a genuinely fresh
  database. It only looked fine locally because an existing database already
  carried `alembic_version` at head. Migrations are now the only thing that
  creates tables.
- `build_city` ignored `TABIKO_DATABASE_URL` and always wrote to
  `backend/tabiko.db`. Deployed with the database on a volume, it reported
  *"imported 7683 places"* into one file while the service served an empty one
  from the other — a healthy container showing an empty map.
- `.dockerignore` used `*.db`, which Docker matches against the whole relative
  path where `*` does not cross a `/`. A 1.9 MB local database was baked into
  every image despite being on the ignore list. It needs `**/*.db`, the same
  trap as `.venv` earlier in the same file.

### Scaling out

`Dockerfile` and `docker/entrypoint.sh` run Alembic and then serve with one
worker process per core. In production the API also serves the built frontend, so
the app, the API and the map data share one origin.

The image is verified end to end, not assumed: built, run, and confirmed serving
the full city from one origin with `/stats` reporting 7,728 places, zero console
errors, hashed assets immutable and `sw.js` uncached. Doing that found three bugs
that reading the code did not, all of them now fixed and covered by tests:

- **The container would not start at all.** Preflight checked for the PWA icons
  in the frontend *source* tree, and the runtime image has no `frontend/`
  directory. The icons were in the built output the whole time, where a browser
  would have fetched them without complaint. The first fix fell back to the
  source tree, which meant a genuinely icon-less build passed as long as a
  developer had `npm run icons` output lying around; the build output is now the
  only thing checked when a static directory is configured.
- **One raising check took down the whole report.** `check_schema` resolved
  `script_location` against the current working directory, so running preflight
  from anywhere but `backend/` raised `CommandError` and the operator got a
  traceback and no information about the other seven settings. Paths are now
  absolute, and a check that raises is reported as a failure instead of
  aborting the gate.
- **`--strict` failed the deploy while printing "0 failures".** The summary now
  says the warnings are what blocked it, because a gate that reports success on
  a blocked deploy is a gate people learn to ignore.

`scripts/preflight.py` had no tests at all before this — the one component whose
job is to fail correctly. It has 29 now, including the three regressions above.

`.dockerignore` keeps the build context to what the image needs. Without it,
`COPY backend/ ./` pulled in `backend/.venv` — 4,538 files and 101 MB of
Windows-built wheels that nothing in a Linux container can import. The image went
from 440 MB to **285 MB**, with `/app` at 3.8 MB. The `**/` prefixes matter: a
bare `.venv` matches only `./.venv`, so the virtualenv at `backend/.venv` was
copied in anyway and the file read as if the problem were handled.

Measured at 8 concurrent users:

| Endpoint | 1 process | 4 processes |
|---|---|---|
| Map points (viewport) | 91 rps, 82 ms | **285 rps, 23 ms** |
| Card list with distance | 6.6 rps, 1,183 ms | **39 rps, 160 ms** |

Each worker holds its own index: about **40 MB** for the place projection and
**47 MB** more once the craving index is loaded, so budget roughly 120 MB per
worker. That is the price of not sharing memory, and it is why the count follows
cores.

Reaching 10,000 *simultaneous* users needs roughly 16–20 workers from these
measurements, which is a 16–20 core machine or five smaller ones behind a load
balancer, plus a CDN in front of the static assets. That is an infrastructure
purchase, not a code change. The measurements above are from one 4-worker process
group on this machine, not a load test against a fleet.

### Security

Three things were open, one of them serious. All are covered by
`tests/test_security.py`.

**The signing secret fell back to a published constant.** `TABIKO_JWT_SECRET` was
optional; without it every token was signed with a literal string that is in this
repository's source. Anyone holding that value could mint a token for any user id,
including an admin, and the failure was silent. The app now refuses to start
unless a real secret of at least 32 characters is set, and says how to generate
one. `TABIKO_ENV=development` is the only way to opt back into the known value,
which is what local development and the test suite use.

**The anonymous auth endpoints were unlimited.** `bcrypt` costs roughly a tenth of
a second per verification, so unthrottled login was both a password-guessing
opener and a cheap way to tie up the worker pool. `app/ratelimit.py` caps each
client address per minute, checked *before* the hash is computed: 10 logins and 5
registrations by default, with `Retry-After` on the 429.

The counters are per worker process, so with `--workers 4` the effective ceiling
is roughly four times the configured value. That is fine for one box and wrong for
a fleet, which needs a shared store. `X-Forwarded-For` is ignored unless
`TABIKO_TRUST_PROXY` is set, because otherwise a caller could rotate identities by
setting the header.

**No response carried security headers.** Now: `X-Content-Type-Options`,
`X-Frame-Options`, `Referrer-Policy`, a CSP that forbids inline and eval'd script,
HSTS over HTTPS, and `Cache-Control: no-store` on authenticated routes so a
shared cache cannot hold someone's saved places.

### Sessions

Access tokens are short-lived (**30 minutes**) and stateless, so verifying a
request costs no database round trip. The session itself is a **refresh token**:
32 random bytes whose SHA-256 is stored, never the token. It is the only thing
that can mint a new access token, and revoking it ends the session at once.

| Route | Purpose |
|---|---|
| `POST /auth/login` | Access token, refresh token, `expires_in` |
| `POST /auth/refresh` | Exchange a refresh token for a new pair |
| `POST /auth/logout` | Revoke one session (idempotent, unauthenticated) |

This replaces a single seven-day token that could not be revoked: a leaked
credential stayed valid for a week, and signing out only discarded the browser's
copy. Rotation means each refresh burns the old token, so a stolen one is usable
at most once. Replaying a spent token outside a 30-second grace window is treated
as theft and revokes every session for that user — two parties holding one token
means one of them is not the reader.

The client refreshes transparently: a 401 triggers one refresh and one retry, with
a shared in-flight promise so two components refreshing at once cannot rotate the
same token out from under each other. `expires_in` is exposed so it can refresh
before the request fails rather than discovering it as an error.

Only the digest is stored, so reading the `refresh_tokens` table hands nobody a
usable credential. Expired rows are inert and `purge_expired_sessions` is a
scheduled call rather than a background worker, which this service does not have.

### Before deploying

`python -m scripts.preflight` reports anything that would fail silently, and
exits non-zero. The container entrypoint runs it before migrating, so a
misconfigured deployment refuses to start rather than serving a blank page.

```text
[ok  ] signing secret  set, 49 characters
[ok  ] environment     production
[warn] database        SQLite. Fine for a single box; use PostgreSQL before running more than one instance...
[ok  ] frontend build  served from /app/static
[ok  ] app icons       present
[ok  ] CORS origins    https://tabiko.example
[ok  ] proxy trust     not trusting forwarded headers (safe default)
[ok  ] migrations      head is 0005_refresh_tokens
```

Add `--strict` to treat warnings as failures.

## Verification

Backend:

```bash
cd backend
pytest -q
ruff check app tests migrations
ruff format --check app tests migrations
alembic check
```

Frontend:

```bash
cd frontend
npm run build
npm test
npm run test:coverage
npm audit
```

The frontend suite is not decoration. Every bug found by hand in this codebase was
a frontend bug — a 422 that blanked the map, a transparent icon, a service worker
that only handled network rejections, a `FALLBACK` table missing a key, a
`0.95.toFixed(1)` that made 950 m read as a shorter distance than 951 m. The
tests that would have caught each of those now exist.

Two more turned up while building the menu contribution flow. `addDish`,
`createReview` and `updateProfile` spread `authHeaders()` into a plain `fetch`
instead of going through `authFetch`, so a reader with an expired access token
had those three writes fail with a 401 that the transparent refresh would
otherwise have handled invisibly — the one case where the session machinery was
most needed. And the bulk handler serialized its rows into Pydantic objects
during the insert loop, then called `db.refresh()` on them afterwards, which is
not a mapped instance; the batch would have rolled back on every call. The
latter was caught by a test before it ever reached the running app, which is the
point of writing them.

### Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request. Until it existed
these checks only ran when someone remembered to ask — which is how a formatting
regression got in while this section was being written.

| Job | Checks |
|---|---|
| `backend` | Ruff lint and format, 283 tests, migrations match the models, and two guards that the app **refuses to import** without a real signing secret or with a short one |
| `frontend` | 100 tests, a production build (which regenerates the PWA icons), `npm audit --audit-level=high` |
| `snapshot` | Builds the city from the committed snapshot on a clean checkout with no network, asserts the place count against the provenance record, and builds twice to prove the result is byte-identical |
| `docker` | Builds the image, then runs it and waits for `/health/live`, so a Dockerfile that builds but cannot boot still fails. The container has no database and builds the city from the committed snapshot on first boot, so this also proves the snapshot is loadable and the entrypoint's build step works |

The signing-secret guards matter more than they look: the published dev secret
once fell back silently, and a test asserting the refusal is the only thing that
stops it returning.

Note the git repository currently lives in the home directory rather than in
this project, so the workflow will not run until `tabiko/` is its own repository.

The offline behaviour is checked against a real production build rather than
assumed: serve `dist`, load once so the worker installs, stop the server, reload.
The shell, the hashed bundle and the basemap must all still render, and `/api`
must fail rather than serve something stale.

## Known limits

- **Walking directions cover Rajajinagar only.** It is the one area with street
  geometry. Elsewhere the app says so explicitly rather than drawing a straight
  line and calling it a route. City-wide routing needs a city-wide graph, which
  is the same data limit described under the two map scales.
- **The city map shows arterials, not every street.** 218,667 highway ways cannot
  be vendored into a static payload. City zoom draws the arterial skeleton; the
  neighborhood layer has full street coverage.
- **Venue imagery is absent.** Real photos need Google Places or Mapillary, and
  neither key is configured. Nothing is stubbed in their place.
- **Cuisine is thin for 52.7% of places.** That is what OpenStreetMap actually
  contains. Derivation from the venue tag narrowed it; the rest is missing at the
  source, not in the classifier.
- **9 of 11 occasion filters match nothing, and the menu now says so.** Only
  `outdoor` (269) and `quick_bite` (31) are populated; `date`, `group`, `family`,
  `work`, `late_night`, `pet_friendly`, `budget`, `live_music` and `solo` have no
  rows. They are labelled "none yet" rather than hidden, which is honest but is
  not a substitute for the data. Filling them needs OSM tags the importer does
  not yet capture, or dish and review text that only readers can supply.
- **The dish and review corpus is still empty.** The paths to fill it now exist
  (see [Contributing a menu](#contributing-a-menu)) but nobody has used them, so
  the craving radar has no dish text to rank. The mechanism is built; the data is
  not there yet.
- **The city is a frozen snapshot, and it will go stale.** It is reproducible and
  auditable, but the OSM payload was fetched on 2026-09-27 and OSM is edited
  constantly. `python -m scripts.build_city --refresh` updates it, and
  `--verify` reports the drift without changing anything. Preflight warns once
  the snapshot passes a year, and requires the provenance record to exist at all,
  because a deployment with no data is otherwise invisible: it boots, passes
  every check, and shows an empty map.
  The bbox is pinned to `12.75,77.45,13.15,77.80`, which is the area the
  original hand-built database came from. Widening it is a decision, not a
  typo fix, and the count will move.
- **The dish and review corpus is still empty.** The paths to fill it now exist
  (see [Contributing a menu](#contributing-a-menu)) but nobody has used them, so
  the craving radar has no dish text to rank. The mechanism is built; the data is
  not there yet.
- **Building for a real server database is not supported.** `build_city` replays
  into a SQLite file and refuses a non-SQLite `TABIKO_DATABASE_URL` rather than
  quietly writing to a file nothing reads. A PostgreSQL deployment needs the
  importer pointed at the server; until then, single box only.
- **It is not built for thousands of concurrent users.** One process plateaus at
  4–5 rps on the card path, bounded by the GIL rather than the database. Worker
  *processes* fix it — 4 workers take the map from 91 to 285 rps and the card
  list from 1,183 ms to 160 ms — and `docker/entrypoint.sh` starts one per core.
  But 10,000 simultaneous users is a fleet, a load balancer and a CDN, which is
  infrastructure to buy rather than code to write.

## Taxonomy

- **Cuisine:** South Indian, North Indian, Chinese, Continental, Italian,
  Cafe/Bakery, Street Food, Multi-cuisine
- **Type:** Cafe, Family restaurant, Fine dine, Cloud kitchen, Darshini/QSR,
  Bar/microbrewery, Food court stall, Unclassified
- **Dietary:** Veg, Non-veg, Vegan, Jain, Halal
