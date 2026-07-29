#!/usr/bin/env bash
# Runs the rq worker and the web server in one Render service, to avoid
# paying for a separate worker service. Trade-off: if the worker subprocess
# crashes, gunicorn keeps running and the healthcheck stays green - jobs
# would silently stop being picked up until the whole service restarts.
# Render's per-process monitoring/auto-restart only applies to the process
# it starts directly (gunicorn here), not this backgrounded worker.
set -eu

rq worker --url "$REDIS_URL" default &

exec gunicorn webapp.app:app -k uvicorn.workers.UvicornWorker -w 2 \
  --bind 0.0.0.0:"$PORT" --forwarded-allow-ips="*"
