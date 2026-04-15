# Debugging and operational runbook

Symptom → **likely cause** → **what to check** → **fix**

---

## Failed send (API returns 400 or message `failed`)

| Symptom | Cause | Check | Fix |
|---------|--------|------|-----|
| 400 `Template has no approved...` | No approved version | Template detail / admin: `is_current_approved` | Approve a version |
| 400 / `last_error` mentions variable | Missing/invalid context | `TemplateVariable` required keys | Fix caller JSON |
| Message `failed`, `last_error` set | Render/sanitize error | `MessageEvent` payload | Fix template or context |
| Stuck `queued` forever | No Celery worker/beat | Worker logs, Redis | Start worker + beat; check `REDIS_URL` |

**Tools:** `GET /api/v1/messages/<id>/`, `GET /api/v1/messages/<id>/events/`, Django admin `OutboundMessage`, `MessageEvent`.

---

## Failed template render (preview or send)

1. Confirm **variables** in admin vs JSON keys (case-sensitive names).
2. Run **preview** with the same context as send.
3. Read **`last_error`** on failed `OutboundMessage` rows.

---

## Idempotency confusion

| Symptom | Explanation |
|---------|-------------|
| Second request returns **200** not **201** | Same `idempotency_key` + tenant — **by design** |
| “Duplicate” content after fixing template | Old idempotency key still maps to **old** message — use a **new** key for a new logical send |
| Failed first attempt, retry returns **200** | Failed message is stored; same key replays stored row |

**Check:** `IdempotencyKeyRecord` in admin (tenant + key hash).

---

## Tenant mismatch

| Symptom | Check |
|---------|--------|
| 404 on message/template/workflow | Object belongs to **another** tenant — API key tenant must match |
| Operator UI “wrong template” | **Active tenant** in header vs template’s tenant |
| Webhook updates wrong message | Rare: `provider_message_id` collision across systems — verify IDs in Postal vs SkyMailr |

---

## Workflow not progressing

1. **Beat** running? `celery -A config beat -l info`
2. **`next_run_at`** in the future? Wait or adjust clock (tests: use `freezegun`).
3. **Step errors** in execution `last_error` — template missing, render failed (see failed send).
4. **Enrollment metadata** — `template_context` must include required variables.

---

## Webhook issues

| Symptom | Check |
|---------|--------|
| Event in DB but message unchanged | Payload `message_id` / `id` must match `OutboundMessage.provider_message_id` |
| No `ProviderWebhookEvent` | Request never reached app — DNS, TLS, Railway routing |
| Signature / security | `ProviderWebhookService` supports `X-SkyMailr-Signature` when `tenant_secret` passed — **production wiring may be incomplete** |

**Inspect:** `ProviderWebhookEvent` in admin; compare `normalized` JSON to Postal’s format.

---

## Railway 502

1. Deploy logs: **gunicorn** listening after migrate?
2. **Custom start command** only `migrate`? → Remove; use image CMD or `/app/scripts/deploy_start.sh`.
3. **`DATABASE_URL`** wrong → connect hang / crash.
4. **`ALLOWED_HOSTS` / CSRF** — less often 502, more often 400/disallowed host.

See [04-railway-deployment.md](04-railway-deployment.md).

---

## Logs

| Source | What to look for |
|--------|------------------|
| **Railway deploy logs** | Boot traceback, gunicorn bind, migrate |
| **Celery worker** | `dispatch_message_task` exceptions, retries |
| **Django / Gunicorn** | 500 tracebacks, request paths |
| **Dummy provider** | Log line “DummyEmailProvider stored message …” |

SkyMailr does not ship a separate log aggregation product — use Railway logs or your forwarder.

---

## Health endpoints

- `GET /api/v1/health/` — app up, JSON time.
- `GET /api/v1/providers/health/` — `provider` name + `ok` + `detail` from `health_check()`.

### What “provider healthy” means

- **dummy:** In-process check — **does not** prove internet, DNS, or Postal.
- **postal:** `PostalEmailProvider.health_check()` GETs your `POSTAL_BASE_URL` (host/TLS reachability), then POSTs to `api/v1/send/message` with an **empty JSON body** so Postal returns a normal JSON `status` (e.g. parameter error) — that proves the **server API key** works without sending mail. It is **not** a full deliverability test.

Before blaming Postal in production: confirm **worker** processed the message (`sent` vs `failed` on `OutboundMessage`), then **webhooks** and **Postal dashboard** for that message id.

---

## Before assuming Postal is broken

1. Message reached **`sent`** in SkyMailr?
2. **`provider_message_id`** set?
3. Webhook URL reachable from Postal’s network (public HTTPS)?
4. DNS for sending domain points at Postal as per **their** docs?

---

## Related

- [04-railway-deployment.md](04-railway-deployment.md)
- [12-known-limitations.md](12-known-limitations.md)
