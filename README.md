# SkyMailr

**Multi-tenant email orchestration** for **TOMEO**, **BrainList**, **ProjMan**, and future apps: templated and raw sends, **Celery** delivery, provider abstraction (**dummy** / **console** / **Postal**), webhooks, suppressions, and workflows. **LLMs** are used only for **drafting/revising** template content — never for sending mail.

## Documentation

| | |
|--|--|
| **[Overview](docs/00-overview.md)** | What it is, tenants, maturity |
| **[Architecture](docs/01-architecture.md)** | Layers, flows, models |
| **[Local development](docs/02-local-development.md)** | Setup, env, Celery, Tailwind |
| **[Testing](docs/03-testing.md)** | pytest, Python **3.11** |
| **[Railway deployment](docs/04-railway-deployment.md)** | Env, 502 recovery, workers |
| **[Operator UI](docs/05-operator-ui-guide.md)** | Staff app tour |
| **[API & auth](docs/06-api-and-auth.md)** | Bearer keys, endpoints, client |
| **[Tenants & onboarding](docs/07-tenants-and-onboarding.md)** | New app checklist |
| **[Templates & workflows](docs/08-templates-and-workflows.md)** | Approve, variables, steps |
| **[Debugging runbook](docs/09-debugging-and-runbook.md)** | Common failures |
| **[Hostinger + Postal plan](docs/10-hostinger-postal-setup-plan.md)** | **Next phase** — VPS + Postal |
| **[Production checklists](docs/11-production-checklists.md)** | Deploy / go-live ticks |
| **[Known limitations](docs/12-known-limitations.md)** | Scope boundaries |

Full index: **[docs/README.md](docs/README.md)**.

## Quick start (local)

**Python 3.11** recommended (see `.python-version`).

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
set DJANGO_SETTINGS_MODULE=config.settings.development
python manage.py migrate
python manage.py seed_skymailr
python manage.py create_tenant_api_key brainlist --name dev
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000
```

- **Operator UI:** `/login/` then `/` (staff user).
- **Health:** `GET /api/v1/health/` · `GET /api/v1/providers/health/`
- **Default email provider:** `EMAIL_PROVIDER=dummy` — stores “sends” in DB; no real delivery.

Details: **[docs/02-local-development.md](docs/02-local-development.md)**.

## Tests

```bash
py -3.11 -m pytest tests/
```

See **[docs/03-testing.md](docs/03-testing.md)** (includes Python 3.14 / Django test-client caveat).

## Railway (production-shaped)

Docker **`CMD`** runs `scripts/deploy_start.sh` (migrate + gunicorn). Needs `DATABASE_URL`, `DJANGO_SECRET_KEY`, `DJANGO_SETTINGS_MODULE=config.settings.production`, `ALLOWED_HOSTS`, and usually `CSRF_TRUSTED_ORIGINS` for HTTPS.

**Runbook:** **[docs/04-railway-deployment.md](docs/04-railway-deployment.md)**.

## Python client (source apps)

```bash
pip install -e packages/skymailr_client
```

Helpers such as `SkyMailrClient.send_verification_email` — see **`packages/skymailr_client/skymailr_client.py`** and **[docs/06-api-and-auth.md](docs/06-api-and-auth.md)**.

## Configuration (high level)

| Variable | Role |
|----------|------|
| `EMAIL_PROVIDER` | `dummy` (default), `console`, `postal` |
| `POSTAL_*` | When `EMAIL_PROVIDER=postal` |
| `LLM_PROVIDER` | `dummy`, `openai`, `anthropic`, `deepseek` — **template drafting only** |
| `API_KEY_PEPPER` | Optional extra secret for API key hashing |

BrainList-aligned LLM env names live in **`config/settings/base.py`**; router: **`apps/llm/router.py`**.

## Docker Compose

```bash
copy .env.example .env
docker compose up --build
```

## Next phase: real mail (Postal)

SkyMailr does **not** include a live Postal install. After the app is stable on Railway, the typical path is **Postal on a VPS** (e.g. Hostinger), DNS (SPF/DKIM/DMARC), then set `EMAIL_PROVIDER=postal` and webhook URL — **[docs/10-hostinger-postal-setup-plan.md](docs/10-hostinger-postal-setup-plan.md)**.

## License / project

Internal product orchestration service; see repository for license if present.
