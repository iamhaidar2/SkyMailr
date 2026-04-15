# Production checklists

Binary checklists — tick or fail.

## Pre-deploy (Railway / container)

- [ ] `DJANGO_SETTINGS_MODULE=config.settings.production`
- [ ] `DJANGO_SECRET_KEY` set and long/random
- [ ] `DATABASE_URL` attached to **web** service and valid
- [ ] `ALLOWED_HOSTS` includes production hostname(s)
- [ ] `CSRF_TRUSTED_ORIGINS` includes `https://...` for operator UI
- [ ] Redis URL present for Celery if using workers
- [ ] Image uses **`scripts/deploy_start.sh`** (or full equivalent) — not migrate-only
- [ ] Branch/commit recorded in Railway deployment

## Post-deploy verification

- [ ] `GET /api/v1/health/` returns 200 JSON
- [ ] `GET /api/v1/providers/health/` returns 200
- [ ] `/login/` loads over HTTPS without CSRF failure
- [ ] Staff login works
- [ ] Gunicorn listening in logs; no boot traceback

## New tenant onboarding

- [ ] `Tenant` created with correct `slug` and sender defaults
- [ ] API key created and stored in app secrets
- [ ] Templates + **approved** versions for required keys
- [ ] Test send in staging with `dummy` or `console` before production Postal

## Pre-Postal (SkyMailr-only)

- [ ] Core API tests pass on Python 3.11 (`py -3.11 -m pytest tests/`)
- [ ] Worker + beat running if email queue is used
- [ ] `EMAIL_PROVIDER` explicitly set (`dummy`/`console` for non-prod send)

## Post-Postal first-send

- [ ] `POSTAL_BASE_URL` reachable from Railway (no self-signed surprises unless `POSTAL_USE_TLS_VERIFY=false` temporarily)
- [ ] `POSTAL_SERVER_API_KEY` valid
- [ ] Test message shows `sent` then webhook updates (if applicable)
- [ ] SPF/DKIM records published for sending domain
- [ ] Webhook URL publicly reachable from Postal

## Regression / MVP gate (before calling MVP “done”)

- [ ] Templated send works end-to-end on target environment
- [ ] Idempotent replay returns same message id
- [ ] Second tenant cannot read first tenant’s messages (spot-check API)
- [ ] Operator can log in, switch tenant, open templates
- [ ] Celery processes a queued message (or document why not in dev)

## Incident response (quick)

- [ ] Identify: web vs worker vs DB vs Redis vs external Postal
- [ ] Logs: Railway deploy + worker + beat
- [ ] Rollback: previous Railway deployment if recent change broke boot
