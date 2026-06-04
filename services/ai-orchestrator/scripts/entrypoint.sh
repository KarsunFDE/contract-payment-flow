#!/bin/sh
# entrypoint.sh — bootstrap Atlas search indexes, then exec the API server.
#
# Finding 4: nothing ran scripts/create_indexes.py, so a fresh
# `docker-compose up --build` came up with both Atlas search indexes missing
# and every POST /retrieve returned 502 'Both retrieval paths failed' until
# someone ran the script by hand. This entrypoint makes index creation
# automatic and idempotent on every container start.
#
# create_indexes.main() is idempotent (skips existing indexes by name, then
# waits for both to be queryable) so re-running on every restart is safe.
# compose gates this service on `mongodb: service_healthy`, so Mongo is up by
# the time we run — a straight run-then-exec is sufficient.
#
# §10 no-silent-failure: if index creation exits non-zero we abort the
# container (set -e + explicit exit) rather than starting an API that would
# 502 on every retrieve. The container then crash-restarts loudly instead of
# serving a broken stack quietly.
set -e

echo "[entrypoint] ensuring Atlas search indexes (python -m scripts.create_indexes)..."
python -m scripts.create_indexes

echo "[entrypoint] indexes ready — starting uvicorn"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
