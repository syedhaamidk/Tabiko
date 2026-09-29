<div align="center">

<sub><b>HEY, FLAVOR CHASER — TAKING IT PUBLIC</b></sub>

# Deploying Tabiko for free

Two ways, both $0 and neither asks for a card.

**Right now, no account:** a Cloudflare quick tunnel in front of your local
Docker deployment. Public HTTPS URL in a minute, runs as long as your machine
and the container do. The URL is random and changes every restart — for sharing
with friends, not for launching.

```bash
# the app must already be up: docker compose up -d --build
cloudflared tunnel --url http://localhost:8010
# → https://<random-words>.trycloudflare.com
```

Get `cloudflared` from https://github.com/cloudflare/cloudflared/releases
(`cloudflared-windows-amd64.exe` on Windows, no install, no signup). Confirm
with `curl https://<your-url>/stats` — `places` should read **7683**.

**Always-on, still free:** Supabase Postgres + Render below. The app runs on
their machines, the data lives in a real database, and nothing on your desk
stays switched on. This is the one to use if the tunnel's limits bother you.

---

## Fly.io (the carded alternative)

Fly.io typically asks for a card at signup even for the free allowance, which
is why it sits second here despite working well: one small machine, one
persistent volume, TLS included — and `fly.toml` in the repo root already
describes it. If you go this way instead of Supabase+Render, SQLite stays the
database and nothing in this section changes.

## What you need

- A Fly.io account (free tier — email signup, no card for the free allowance).
- `flyctl` installed: https://fly.io/docs/flyctl/install/
- About 10 minutes. The first deploy builds the image (~5 min); after that it's fast.

## Deploy

```bash
# 1. Sign in
fly auth login

# 2. Create the app. Names are global, so if `tabiko` is taken pick your own
#    and put the same name in fly.toml under `app = "..."`.
fly apps create tabiko

# 3. The volume. This is where the city and everything readers create lives.
#    1 GB is plenty (the city database is ~2 MB).
fly volumes create tabiko_data --region bom --size 1 -a tabiko

# 4. The one secret. Generate it, set it, forget it. Never commit it.
python -c "import secrets; print(secrets.token_urlsafe(48))"
fly secrets set TABIKO_JWT_SECRET="<paste-what-that-printed>" -a tabiko

# 5. Ship it
fly deploy

# 6. Open it and confirm the city is really there
fly open -a tabiko
curl https://<your-app>.fly.dev/stats
```

`places` should read **7683**. If it reads `0`, the volume isn't mounted —
check `fly status -a tabiko` and that step 3 used the same app and region.

## Supabase + Render (the always-on free path)

Why these two: Supabase gives free Postgres without a card, Render runs the
container without a card, and the app's Postgres support is proven — migrations
0001–0009 apply cleanly, the transfer path is tested live in CI, and the rate
limiter, auth, reviews, follows and themes were all exercised against a real
server. The one thing that does not cross over is `scripts/backup.py`
(SQLite API) — back up from the Supabase dashboard instead.

### 1. The database (Supabase, ~5 min)

1. Sign up at supabase.com (free tier, no card) → **New project**, any name,
   region closest to your readers, and a strong **database password** — save it.
2. Wait for provisioning, then **Project Settings → Database → Connection
   string → URI**. It looks like
   `postgresql://postgres:<password>@db.<ref>.supabase.co:5432/postgres`.
   If your password has special characters, use the dashboard's URI as-is
   (it is already encoded) rather than retyping it.

### 2. Seed it from your machine

Your laptop builds the city from the committed snapshot and copies it over.
Nothing is uploaded except rows.

```bash
cd backend
python -m scripts.build_city            # builds tabiko.db if you don't have one
TABIKO_DATABASE_URL="<paste-the-supabase-uri>" \
  python -m scripts.transfer_city
```

Expected ending: `done: 7761 rows across 7 tables, all verified.` (7,683
places + 77 reference dishes + the seed account). The script migrates first,
refuses a non-empty database, and fails loudly on any count mismatch — there
is no `--force` because wiping a database is a decision, not a flag.

### 3. The app (Render, ~10 min)

1. Sign up at render.com (free tier, no card) → **New → Blueprint** → point it
   at your fork. `render.yaml` in the repo root describes the service.
2. When prompted, set the two secrets it cannot commit:
   - `TABIKO_DATABASE_URL` — the same Supabase URI.
   - `TABIKO_JWT_SECRET` — generate one:
     `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
3. Deploy. First boot runs migrations (no-op — already migrated) and serves.

Confirm: `curl https://<your-app>.onrender.com/stats` → `places: 7683`.

### 4. Frontend on Vercel (optional)

Render already serves the whole app on one origin, so this is strictly
optional — a faster global CDN for the shell, at the cost of two origins
that must agree with each other. Skip it and nothing breaks.

1. Vercel dashboard → **Add New → Project** → your fork. When asked:
   - **Root Directory:** `frontend` (not the repo root).
   - **Build Command / Output:** leave the auto-detected Vite defaults.
   - **Environment Variables:** `VITE_API_URL` = `https://<your-app>.onrender.com`
     (Production). The URL is baked into the bundle at build time, so setting
     it after deploying means deploying again.
2. Render dashboard → your service → **Environment** → set
   `TABIKO_CORS_ORIGINS` to `https://<your-vercel-app>.vercel.app` → Save.
   Without this, saving places and unfollowing people break while everything
   else works — those are the only buttons that send PUT/DELETE, the only
   methods that trigger preflights.
3. If you did the Google step: add the Vercel URL to the OAuth client's
   **Authorized JavaScript origins** too, or Google will not issue tokens to it.

Confirm: open the Vercel URL, save a place while signed in, unfollow someone.
If both work, the origins agree.

### 4. Google sign-in on production (optional, after the URL exists)

Google only issues tokens to registered origins, and the production origin
doesn't exist until the first deploy — so this comes last:

1. Google Cloud Console → your OAuth client → **Authorized JavaScript
   origins** → add `https://<your-app>.onrender.com` alongside
   `http://localhost:5173`.
2. Render dashboard → your service → **Environment** → add
   `TABIKO_GOOGLE_CLIENT_ID` with the client ID → **Save** (redeploys).
3. Open the app: the Google button appears. The server's CSP opens the
   script, iframe and session-state directives for `accounts.google.com`
   only while that variable is set — without it the policy stays strict.

Skip this entirely and nothing breaks: no variable means no button and a
503 on the endpoint, exactly like local dev without one.

## Day two on the free path

| | |
|---|---|
| **Sleeping** | Render sleeps the app after idle and wakes it on request (cold start ~30 s). Supabase pauses databases after 7 idle days — restore with one click in their dashboard. Regular visitors prevent both. |
| **One instance, always** | `render.yaml` pins one. More gain nothing here and multiply connections against a small free database. |
| **Uploads are ephemeral** | Photos live on Render's disk, which is wiped on restart. Dishes, reviews, follows and accounts are safe in Postgres; dish *photos* are not. Object storage is the fix, listed as future work. |
| **Logs / health** | Render dashboard logs; `/health/live` for uptime checks. |

---

## What free doesn't cover (every path above)

- **Cold starts.** An idle app takes a few seconds to wake. A reader's first tap after a quiet spell waits; every tap after that is fast.
- **Scale.** One box, one writer — same as the documented limit everywhere else in this repo. A crowd needs paid infrastructure, not code changes.
- **Alright, the fine print.** Free-allowance terms change; if Fly's free tier moves, this same `fly.toml` + `Dockerfile` deploys anywhere that runs a container with a persistent disk.

---

## Use it on your phone (the mobile app is the website, installed)

There is no native wrapper and none is planned: store fees, two build
chains, and review queues, for an app whose offline story — a self-drawn
map with zero tile requests — already works in a browser. Install it from
the deployed URL instead (needs HTTPS, so the Vercel address, not localhost):

- **Android (Chrome):** open the app → ⋮ menu → **Install app** (or **Add to
  Home screen**). It lands on the home screen, opens standalone with no
  browser chrome, and works offline for the map and shell.
- **iPhone (Safari):** open the app → **Share → Add to Home Screen**. Same
  standalone result. (Apple only offers installation from Safari, not Chrome.)

The install contract — manifest, icon sizes, notch viewport, offline shell
that never caches the API — is asserted in `frontend/src/lib/pwa.test.js`,
because a broken install shows no error: the app just quietly stops being
installable.

If store presence or push notifications ever justify it, the path is
Capacitor wrapping this exact codebase (no rewrite): but that means a Mac
for iOS builds, $25 one-time for Google Play, and $99/year for the App
Store. Until then, this is the mobile app.

---

<div align="center">

*Cooked up with masala & main-character energy*

</div>
