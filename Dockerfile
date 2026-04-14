FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

RUN chmod +x scripts/deploy_start.sh

ENV DJANGO_SETTINGS_MODULE=config.settings.development
ENV DJANGO_SECRET_KEY=collectstatic-only

RUN python manage.py collectstatic --noinput

ENV DJANGO_SETTINGS_MODULE=config.settings.production

# Railway sets PORT at runtime — gunicorn.conf.py binds to $PORT (defaults to 8000 locally).
EXPOSE 8000

# Use scripts/deploy_start.sh so migrate + gunicorn always run from /app with correct cwd.
CMD ["/app/scripts/deploy_start.sh"]
