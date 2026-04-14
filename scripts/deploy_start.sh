#!/usr/bin/env sh
# Single entrypoint for Railway/Docker: migrate then Gunicorn (listens on $PORT via gunicorn.conf.py).
set -eu

cd /app

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.production}"

# Log to stderr (unbuffered) so Railway deploy logs always show this even before Django loads.
log() { printf '%s\n' "$*" >&2; }

log "[skymailr] entrypoint | DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE PORT=${PORT:-unset}"
log "[skymailr] (If deploy logs stop after migrate with no line below, clear Railway Custom Start Command.)"

log "[skymailr] migrate..."
python -u manage.py migrate --noinput

log "[skymailr] migrate done; starting gunicorn via python -m (binds PORT in gunicorn.conf.py)..."
exec python -m gunicorn -c gunicorn.conf.py config.wsgi:application
