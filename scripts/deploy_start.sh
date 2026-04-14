#!/usr/bin/env sh
# Single entrypoint for Railway/Docker: migrate then Gunicorn (listens on $PORT via gunicorn.conf.py).
set -eu

cd /app

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.production}"

echo "[skymailr] DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE"
echo "[skymailr] PORT=${PORT:-8000}"

echo "[skymailr] migrate..."
python manage.py migrate --noinput

echo "[skymailr] gunicorn..."
exec gunicorn -c gunicorn.conf.py config.wsgi:application
