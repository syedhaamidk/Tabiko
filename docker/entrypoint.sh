#!/bin/sh
# Bring the schema up to date, then serve.
#
# Several worker *processes* rather than threads: the heavy read path is
# CPU-bound in Python, and the GIL means threads buy nothing there. Processes are
# the only way to use more than one core, and they are what turns the measured
# single-process throughput into a total.

set -e

HOST="${TABIKO_HOST:-0.0.0.0}"
PORT="${TABIKO_PORT:-8010}"

# One worker per core unless told otherwise, with a floor so a small box still
# gets a process and a ceiling so a large one does not thrash.
if [ -z "${TABIKO_WORKERS}" ]; then
    CORES="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)"
    if [ "$CORES" -lt 2 ]; then
        WORKERS=2
    elif [ "$CORES" -gt 8 ]; then
        WORKERS=8
    else
        WORKERS="$CORES"
    fi
else
    WORKERS="$TABIKO_WORKERS"
fi

echo "tabiko: checking the deployment configuration"
# Refuses to start on a missing or published signing secret, a wildcard CORS
# origin, or a static directory that is not there. Cheap, and it turns a silent
# misconfiguration into a loud one at boot rather than a blank page later.
python -m scripts.preflight

echo "tabiko: applying migrations"
python -m alembic upgrade head

echo "tabiko: serving on $HOST:$PORT with $WORKERS worker processes"
exec python -m uvicorn app.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WORKERS" \
    --no-access-log \
    --timeout-keep-alive 30
