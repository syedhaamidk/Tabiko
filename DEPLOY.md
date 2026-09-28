<div align="center">

<sub><b>HEY, FLAVOR CHASER — TAKING IT PUBLIC</b></sub>

# Deploying Tabiko for free

One small machine, one persistent volume, TLS included — on Fly.io's free
allowance. No server to manage, no domain to buy.

**✦ FREE ✦ ONE COMMAND DEPLOYS ✦ SLEEPS WHEN IDLE ✦**

</div>

---

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

## Day two

| | |
|---|---|
| **Sleeping** | The machine stops when nobody's visiting and wakes on the next request (a few seconds of cold start). This is what keeps it free. |
| **One machine, always** | Never scale past 1 (`fly scale count 1 -a tabiko` to be sure). Two writers on one SQLite file is corruption, not scaling. |
| **Out of memory?** | One worker holds ~120 MB of index. If the 256 MB machine OOMs, give it room: `fly scale memory 512 -a tabiko`. |
| **Backups** | Snapshot the volume from the Fly dashboard before any big change. The app's own `scripts/backup.py` also works over `fly ssh console`. |
| **Custom domain** | Optional, later: `fly certs add <your-domain>` and point DNS at the app. TLS is automatic either way. |
| **Logs** | `fly logs -a tabiko`. Health endpoint for uptime checks: `/health/live`. |

## What free doesn't cover

- **Cold starts.** An idle app takes a few seconds to wake. A reader's first tap after a quiet spell waits; every tap after that is fast.
- **Scale.** One box, one writer — same as the documented limit everywhere else in this repo. A crowd needs paid infrastructure, not code changes.
- **Alright, the fine print.** Free-allowance terms change; if Fly's free tier moves, this same `fly.toml` + `Dockerfile` deploys anywhere that runs a container with a persistent disk.

---

<div align="center">

*Cooked up with masala & main-character energy*

</div>
