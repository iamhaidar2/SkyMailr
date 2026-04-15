# Railway deployment and recovery

This is a **runbook**, not marketing copy. SkyMailr ships a **Dockerfile** that runs `scripts/deploy_start.sh` (migrate + gunicorn).

## Services to provision

| Service | Role |
|---------|------|
| **Web** | SkyMailr container; HTTP traffic |
| **Postgres** | `DATABASE_URL` — required for production-style deploy |
| **Redis** | Broker for Celery (worker + beat) |
| **Worker** | `celery -A config worker -l info` (same image, different command) |
| **Beat** | `celery -A config beat -l info` |

Celery/Redis can be deferred only if you accept **no background dispatch** — not acceptable for real email. For a **healthy production**, run worker + beat.

## Required environment variables (web)

| Variable | Example / note |
|----------|----------------|
| `DATABASE_URL` | From Railway Postgres plugin — must be attached to the **SkyMailr** service |
| `DJANGO_SECRET_KEY` | Long random string; never commit |
| `DJANGO_SETTINGS_MODULE` | `config.settings.production` |
| `ALLOWED_HOSTS` | Comma-separated: `skymailr.com,www.skymailr.com,your-app.up.railway.app` (no stray spaces) |
| `REDIS_URL` or `CELERY_BROKER_URL` | Point to Redis for workers |

**Email (until Postal is wired):**

- `EMAIL_PROVIDER=dummy` or `console` for smoke tests only.
- For real sends: `EMAIL_PROVIDER=postal` + `POSTAL_BASE_URL`, `POSTAL_SERVER_API_KEY`, etc. (see [10-hostinger-postal-setup-plan.md](10-hostinger-postal-setup-plan.md)).

**HTTPS / forms:**

- `CSRF_TRUSTED_ORIGINS` — e.g. `https://skymailr.com,https://www.skymailr.com` — required so login and POST forms work behind HTTPS.

**Optional:**

- `ALLOWED_HOSTS_EXTRA` — extra hosts (e.g. preview URLs) merged in `production.py`
- `SECURE_SSL_REDIRECT` — defaults to true in production

## Start command behavior

**Correct:** Empty “Custom Start Command” in Railway so the image **CMD** runs:

- `scripts/deploy_start.sh` → `migrate --noinput` → `gunicorn` on `$PORT`

**Broken pattern:** Custom command **only** `python manage.py migrate` — migrates then **exits** → **no HTTP server** → **502** on every request (~15s timeout).

**If you must override**, use exactly:

```bash
/app/scripts/deploy_start.sh
```

## Custom domain

1. Add domain in Railway; point DNS CNAME to Railway target.
2. Add host to `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.

## Common 502 causes

1. **Wrong/missing `DATABASE_URL`** — migrate hangs or crashes; gunicorn never listens. **Fix:** Attach Postgres variable to the web service; verify URL.
2. **Custom start command** only runs migrate. **Fix:** Clear it or set to `/app/scripts/deploy_start.sh`.
3. **Crash on boot** — check Deploy logs for Python traceback (missing env, import error).
4. **Worker/beat down** — web may be “up” but mail never leaves `queued` (see [09-debugging-and-runbook.md](09-debugging-and-runbook.md)).

## Verify a healthy deployment

- [ ] `GET https://<host>/api/v1/health/` → `{"status":"ok",...}`
- [ ] `GET https://<host>/api/v1/providers/health/` → JSON with `provider`, `ok`
- [ ] `/login/` loads over HTTPS without CSRF errors
- [ ] Deploy logs show gunicorn listening after migrate
- [ ] Worker logs show Celery ready; beat scheduling tasks (optional: grep for beat tick)

## Confirm branch / commit

Use Railway’s **Deployments** UI: git commit SHA, branch, build logs. Tag releases in git if you need to correlate production to a revision.

## If production is broken — order of checks

1. **Deploy logs** — traceback? migrate stuck? gunicorn started?
2. **`DATABASE_URL`** — present and valid?
3. **Start command** — not migrate-only?
4. **`ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS`** — match actual URL?
5. **Redis + worker + beat** — for anything beyond static health?
6. **Recent migrations** — failed migration leaves app in bad state; read full traceback.

## Related

- Production checklists: [11-production-checklists.md](11-production-checklists.md)
- Debugging: [09-debugging-and-runbook.md](09-debugging-and-runbook.md)
