# syntax=docker/dockerfile:1

# Two stages: the frontend is built once and its static output is served by the
# API process, so there is no second runtime to keep in step.

FROM node:22-alpine AS frontend
WORKDIR /build
# Copy the manifests first so a source-only change reuses the installed tree.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./
COPY --from=frontend /build/dist ./static

# Alembic runs on start rather than at build time, so a migration is never
# baked into an image and the schema is never behind the code.
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# One worker per core, capped, because the API is CPU-bound on the GIL and extra
# threads cannot help. Override TABIKO_WORKERS for a smaller box.
ENV TABIKO_WORKERS=4 \
    TABIKO_HOST=0.0.0.0 \
    TABIKO_PORT=8010 \
    TABIKO_STATIC_DIR=/app/static

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8010/health/live', timeout=4).status==200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
