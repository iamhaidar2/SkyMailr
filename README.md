# SkyMailr

Production-oriented **multi-tenant email orchestration** service for **TOMEO**, **BrainList**, and **ProjMan**: templated transactional and lifecycle mail, LLM-assisted **drafting only**, deterministic **Celery** delivery, provider abstraction (dummy / console / Postal), webhooks, suppression, and workflows.

## BrainList LLM patterns (inspected)

From `BrainList/backend/studio/providers.py` and tasks:

- **Environment**: `LLM_PROVIDER` = `dummy` | `openai` | `anthropic` | `deepseek` (default `dummy`).
- **Keys / endpoints**: `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`; `ANTHROPIC_API_KEY`; `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL` (default `https://api.deepseek.com`), `DEEPSEEK_MODEL`.
- **Factory**: `get_llm_provider()` selects implementation; **OpenAI** uses the official `openai` SDK with an **`httpx.Client`** HTTP client.
- **DeepSeek**: OpenAI-compatible client with custom `base_url`.
- **Anthropic**: separate client (`anthropic` SDK).

SkyMailr mirrors these names in `config/settings/base.py` and implements `get_llm_client()` in `apps/llm/router.py` with **`OpenAICompatibleLLMClient`**, **`AnthropicJsonClient`**, and **`DummyLLMClient`**. **Email sending never calls the LLM.**

## Architecture (layers)

| Layer | Responsibility |
|--------|------------------|
| **API** (`apps/api`) | DRF endpoints, tenant API key auth |
| **Orchestration** | Celery tasks: dispatch, retries, workflow ticks |
| **Templates** (`apps/email_templates`) | Versioned templates, Jinja2 sandbox render, approval, LLM draft/revise services |
| **Messages** (`apps/messages`) | Outbound queue, idempotency, events |
| **Providers** (`apps/providers`) | `BaseEmailProvider` + dummy / console / Postal |
| **LLM** (`apps/llm`) | Structured JSON generation, prompt builders under `apps/llm/prompts/` |
| **Workflows** (`apps/workflows`) | Steps stored in DB; LLM only drafts sequence JSON |

## Local setup

**Python 3.11+** recommended.

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # Windows
export DJANGO_SETTINGS_MODULE=config.settings.development   # Unix
# Windows: set DJANGO_SETTINGS_MODULE=config.settings.development
```

**Database**

- Default: **SQLite** (`db.sqlite3`) if `DATABASE_URL` is **unset**.
- If `DATABASE_URL` is set to a **remote** Postgres URL, ensure the host is reachable; otherwise **`migrate` may appear to hang** while connecting.

```bash
python manage.py migrate
python manage.py seed_skymailr
python manage.py create_tenant_api_key brainlist --name dev
python manage.py createsuperuser
python runserver 0.0.0.0:8000
```

**Celery** (separate terminals; Redis required):

```bash
celery -A config worker -l info
celery -A config beat -l info
```

Health checks:

- `GET /api/v1/health/`
- `GET /api/v1/providers/health/`

Internal dashboard (staff): `/internal/dashboard/`

## Docker Compose

Copy `.env.example` to `.env`, adjust secrets, then:

```bash
docker compose up --build
```

## Railway

### Required variables

- **`DATABASE_URL`** — add the Postgres service to the SkyMailr service and **reference** its `DATABASE_URL` (or paste the URL). If this is wrong or missing, **`migrate` can hang** and Gunicorn **never starts** → every request **502** (~15s timeout).
- **`DJANGO_SECRET_KEY`** — long random string (never commit).
- **`DJANGO_SETTINGS_MODULE`** — `config.settings.production`
- **`ALLOWED_HOSTS`** — e.g. `skymailr.com,www.skymailr.com,skymailr-production.up.railway.app` (comma-separated, no spaces unless part of the host).

### Start command (important)

The **Dockerfile** runs **`/app/scripts/deploy_start.sh`**, which:

1. `cd /app`
2. `python manage.py migrate --noinput`
3. `exec gunicorn -c gunicorn.conf.py config.wsgi:application` (binds **`$PORT`**)

**Clear the “Custom Start Command”** in Railway (leave it empty) so Railway uses the image **CMD**. A broken or truncated one-liner (e.g. `config.wsgi:appli`) prevents the app from starting.

If you must override, use only:

```bash
/app/scripts/deploy_start.sh
```

### If you still see 502

1. Open **Deploy logs**. If you see **only** Django migrate output (`No migrations to apply.`) and **nothing after that** (no `[skymailr]` lines, no Gunicorn “Listening”), your **Custom Start Command is probably only** `python manage.py migrate`. That runs migrations and then **exits** — **no web server** → **502**. **Clear** the custom start command so the Docker **`CMD`** runs `scripts/deploy_start.sh`, or set it to **`/app/scripts/deploy_start.sh`** only.
2. Look for Python tracebacks or `migrate` stuck after “Running migrations”.
3. Confirm Postgres is **connected** and `DATABASE_URL` is on the **SkyMailr** service.
4. Celery/Redis are optional until the web service is healthy.

Worker / beat (separate services): `celery -A config worker -l info` and `celery -A config beat -l info`.

- **Unset** `DATABASE_URL` locally if you are not using Postgres to avoid connection stalls.
- Optionally add **`ALLOWED_HOSTS_EXTRA`** for preview URLs (see `config/settings/production.py`).

## Source-app client

See `packages/skymailr_client/` — install with `pip install -e packages/skymailr_client`. Helpers: `send_verification_email`, `send_password_reset_email`, `send_collaborator_invite`, `send_account_deletion_confirmation`, `enroll_user_in_workflow`.

## Testing

```bash
set DATABASE_URL=
set DJANGO_SETTINGS_MODULE=config.settings.test
pytest
```

## Configuration reference

| Variable | Purpose |
|----------|---------|
| `EMAIL_PROVIDER` | `dummy` (default), `console`, `postal` |
| `POSTAL_*` | Postal HTTP API when `EMAIL_PROVIDER=postal` |
| `LLM_PROVIDER` | `dummy`, `openai`, `deepseek`, `anthropic` |
| `API_KEY_PEPPER` | Optional extra secret mixed into API key hashes |

---

## Next step: Postal on Hostinger VPS

1. Provision **Postal** on your VPS and obtain the **server API key** and **base URL** (HTTPS).
2. Point **DNS** (SPF, DKIM, return-path) for your sending domains at Postal’s docs; align `Tenant.sending_domain` / `TenantDomain` in SkyMailr.
3. Set environment on SkyMailr (Railway or Docker):

   - `EMAIL_PROVIDER=postal`
   - `POSTAL_BASE_URL=https://postal.yourdomain.com`
   - `POSTAL_SERVER_API_KEY=<postal server api key>`
   - `POSTAL_USE_TLS_VERIFY=true` (or `false` only for dev with self-signed certs)

4. Configure **webhooks** in Postal to POST to SkyMailr:  
   `https://<your-skymailr-host>/api/v1/webhooks/provider/postal/`  
   Optionally implement **HMAC** verification using `Tenant.webhook_secret` and header `X-SkyMailr-Signature` (see `ProviderWebhookService`).
5. Send a **test** message via `POST /api/v1/messages/send-template/` and confirm events in admin (`ProviderWebhookEvent`, `MessageEvent`).
6. Tune **rate limits** (`Tenant.rate_limit_per_minute`) and **Redis** capacity before full production traffic.
