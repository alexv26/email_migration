#!/usr/bin/env bash
# Runs the rq worker and the web server in one Render service, to avoid
# paying for a separate worker service. Trade-off: if the worker subprocess
# crashes, gunicorn keeps running and the healthcheck stays green - jobs
# would silently stop being picked up until the whole service restarts.
# Render's per-process monitoring/auto-restart only applies to the process
# it starts directly (gunicorn here), not this backgrounded worker.
set -eu
cd "$(dirname "$0")"

# Load .env if present, without overriding real env vars already set (e.g.
# by Render's dashboard). Needed for launchd/Task Scheduler-style startup,
# which has no shell around to have already sourced it - previously this
# script relied on the caller having done that manually.
#
# Read line-by-line and export directly instead of `source .env`: many
# values here (app passwords, Fernet keys) legitimately contain spaces or
# `=` characters. A plain `source` word-splits unquoted values with spaces
# as separate shell commands; `read` with IFS='=' silently drops a value's
# trailing `=` (a real problem for base64 padding, e.g. Fernet keys) since
# it's treated as an empty trailing field rather than literal content.
# Parameter expansion on the first `=` avoids both problems.
if [ -f .env ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ''|'#'*) continue ;;
    esac
    key="${line%%=*}"
    value="${line#*=}"
    export "$key=$value"
  done < .env
fi

: "${PORT:=8000}"
: "${REDIS_URL:=redis://localhost:6379}"

rq worker --url "$REDIS_URL" default &

# -w 1: a second uvicorn worker roughly doubles the app's baseline memory
# for no real benefit at ~10 users, and memory is the tight resource on the
# Starter plan this service shares with the migration worker above.
exec gunicorn webapp.app:app -k uvicorn.workers.UvicornWorker -w 1 \
  --bind 0.0.0.0:"$PORT" --forwarded-allow-ips="*"
