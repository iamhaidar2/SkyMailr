# Local development

## Prerequisites

- **Python 3.11** (recommended; matches `.python-version` and CI expectations).
- **Redis** if you run Celery (not strictly required to boot Django if you only hit health/UI without sending).
- **Node.js** only if you change Tailwind/CSS sources (see below).

## Virtualenv and dependencies

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
.venv\Scripts\pip install -r requirements.txt

# macOS/Linux
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment

```bash
# Windows (cmd)
set DJANGO_SETTINGS_MODULE=config.settings.development

# PowerShell
$env:DJANGO_SETTINGS_MODULE="config.settings.development"

# Unix
export DJANGO_SETTINGS_MODULE=config.settings.development
```

**Email / provider (local default):**

```bash
# Optional; default is dummy
set EMAIL_PROVIDER=dummy
```

**Database:**

- If **`DATABASE_URL` is unset**, Django uses **SQLite** (`db.sqlite3` in project root).
- If you set `DATABASE_URL` to a **remote Postgres**, ensure the host is reachable — **`migrate` can appear to hang** on connect failure.

Unset for pure local SQLite:

```bash
set DATABASE_URL=
```

## Migrations and seed

```bash
python manage.py migrate
python manage.py seed_skymailr
```

## API key for a tenant

After seed (creates tenants such as `brainlist` depending on seed data):

```bash
python manage.py create_tenant_api_key brainlist --name dev
```

Copy the printed key once; it is not shown again.

## Superuser (operator UI)

```bash
python manage.py createsuperuser
```

Staff users can log into `/login/`.

## Run the web app

```bash
python manage.py runserver 0.0.0.0:8000
```

**Useful URLs**

| URL | Purpose |
|-----|---------|
| `/` | Dashboard (requires staff login) |
| `/login/` | Operator login |
| `/api/v1/health/` | JSON health (no auth) |
| `/api/v1/providers/health/` | Provider adapter health (no auth) |
| `/service/` | Machine-readable service metadata |

## Celery worker and beat

Requires **Redis** (default `REDIS_URL=redis://localhost:6379/0` unless overridden).

Terminal 1:

```bash
celery -A config worker -l info
```

Terminal 2:

```bash
celery -A config beat -l info
```

Without worker + beat, **queued messages are not dispatched** until something runs `sweep_dispatch_queue` (beat schedule in production). With `CELERY_TASK_ALWAYS_EAGER=True` (tests only), tasks run inline.

## Tailwind / CSS

Built CSS lives at `apps/ui/static/ui/css/app.css`. The Docker image **does not** run Node.

After editing templates that need **new** Tailwind classes or `tailwind.config.js`:

```bash
npm install
npm run build:css
```

Commit the generated `app.css` if it changed.

## What “dummy provider” means

`EMAIL_PROVIDER=dummy` (default): outbound “sends” are **stored in the database** (`DummyStoredEmail`) and succeed without network I/O. Use this for **local dev and automated tests**. It does **not** prove DNS, Postal, or deliverability.

## LLM (optional)

Default `LLM_PROVIDER=dummy` — no external LLM calls. To use real drafting:

- Set `LLM_PROVIDER` to `openai`, `anthropic`, or `deepseek` per `config/settings/base.py`.
- Provide the corresponding API keys / base URLs.

**Email sending never calls the LLM** — only template draft/revise flows do.

## Docker Compose (optional)

```bash
copy .env.example .env
# edit .env
docker compose up --build
```

Useful when you want Postgres/Redis without local installs; see repo `docker-compose` files if present.
