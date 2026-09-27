# Archived Tabiko backend snapshot

This directory is the earlier feature draft (authentication, craving search,
reviewer profiles, and restaurant experience fields).

Its features have been merged into the maintained API in [`../backend`](../backend).
Do not run this directory as a second service: it uses an older schema, a
separate database file, and different dependency versions.

Run the maintained backend and the Vite frontend instead:

```bash
cd ../backend
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8010

cd ../frontend
npm install
npm run dev
```
