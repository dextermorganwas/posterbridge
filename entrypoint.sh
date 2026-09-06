#!/bin/sh
# Runs a single uvicorn worker (see app/cache.py's claim_app_state_slot
# docstring for why PosterBridge isn't designed for WORKERS > 1 yet).
# tini (the container's PID 1, set as ENTRYPOINT) forwards SIGTERM to this
# process so `docker stop` / `docker compose down` trigger uvicorn's
# --timeout-graceful-shutdown drain instead of an immediate kill, which in
# turn runs the FastAPI lifespan shutdown block in app/main.py.
set -e

exec uvicorn app.main:app \
    --host "${HOST:-0.0.0.0}" \
    --port "${PORT:-8000}" \
    --log-level "${LOG_LEVEL:-info}" \
    --timeout-graceful-shutdown "${GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS:-20}"
