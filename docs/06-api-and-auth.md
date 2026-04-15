# API and authentication

Base URL: `https://<your-host>/` — API routes have **no** `/api` prefix mismatch; they live under `/api/v1/`.

## Two auth modes

| Mode | Mechanism | Used by |
|------|-----------|---------|
| **Tenant API key** | `Authorization: Bearer <raw_key>` | Source apps, `skymailr_client` |
| **Session + staff** | Django login cookie | Operator UI, Django admin |

**API views** use DRF + custom `TenantAPIKeyAuthentication`: valid key → `ApiTenantUser` wrapping a **`Tenant`** instance. `HasTenant` requires that user.

**Admin-only API:** e.g. `POST /api/v1/tenants/api-keys/` requires `IsAdminUser` (Django admin user), not just a tenant key.

## Tenant API keys

- Created via `python manage.py create_tenant_api_key <slug> --name <label>` or admin/UI.
- **Stored hashed** (`key_hash`); raw key shown **once**.
- Optional env: `API_KEY_PEPPER` — extra secret mixed into hashing (see `config/settings`).

## Important endpoints (summary)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/v1/health/` | None | Liveness |
| GET | `/api/v1/providers/health/` | None | Provider adapter check |
| POST | `/api/v1/messages/send/` | Bearer | Raw HTML/text send |
| POST | `/api/v1/messages/send-template/` | Bearer | Templated send |
| GET | `/api/v1/messages/<uuid>/` | Bearer | Message detail |
| GET | `/api/v1/messages/<uuid>/events/` | Bearer | Event timeline |
| POST | `/api/v1/messages/<uuid>/retry/` | Bearer | Retry failed/deferred |
| POST | `/api/v1/messages/<uuid>/cancel/` | Bearer | Cancel queued/rendered/deferred |
| GET | `/api/v1/templates/` | Bearer | List templates **for tenant** |
| POST | `/api/v1/templates/generate/` | Bearer | LLM draft template |
| POST | `/api/v1/templates/<uuid>/revise/` | Bearer | LLM revise |
| POST | `/api/v1/templates/<uuid>/approve/` | Bearer | Approve latest version |
| POST | `/api/v1/templates/<uuid>/preview/` | Bearer | Render preview (logs render) |
| POST | `/api/v1/workflows/` | Bearer | Create/get workflow |
| POST | `/api/v1/workflows/<uuid>/enroll/` | Bearer | Enroll recipient |
| POST | `/api/v1/subscriptions/unsubscribe/` | None | Public unsubscribe (needs `tenant_slug` in body) |
| POST | `/api/v1/webhooks/provider/<provider>/` | None | Provider callbacks |
| POST | `/api/v1/tenants/api-keys/` | **Admin** | Create key for tenant by slug |
| GET | `/api/v1/suppressions/` | Bearer | List suppressions for tenant |

Full routing: `config/urls.py`.

## Example: templated send

```http
POST /api/v1/messages/send-template/
Authorization: Bearer sk_live_...
Content-Type: application/json

{
  "template_key": "email_verification",
  "to_email": "user@example.com",
  "context": { "user_name": "Ada", "verify_url": "https://..." },
  "source_app": "brainlist",
  "message_type": "transactional",
  "idempotency_key": "optional-unique-string"
}
```

**Success:** HTTP **201** first time; **200** on idempotent replay with same body key.

**Failure (e.g. render):** HTTP **400** with `detail`; failed message may be persisted — replay with same idempotency key returns **200** with same message id (see tests).

## Idempotency

- **Scope:** Per **tenant** + opaque `idempotency_key` string (hashed).
- **Use when:** At-least-once callers (retries, webhooks) could duplicate sends.
- **Do not reuse** keys for logically different sends.

## Message lifecycle (operator/API perspective)

Typical progression: `queued` → `sending` → `sent` → (webhook) `delivered` / `bounced` / …

Failures: `failed`, `deferred` (retry with backoff). **Retry** allowed from failed/deferred; **cancel** from queued/rendered/deferred (see `message_actions`).

## Source apps: safe usage

1. Store **`SKYMAILR_API_KEY`** per environment; rotate via new key + revoke old in admin.
2. Set **`source_app`** to a stable identifier (`brainlist`, `projman`, …) for filtering in logs.
3. Use **template keys** agreed per tenant (`email_verification`, …).
4. Pass **complete context** for required template variables — or expect 400 + failed message record.

## Python client: `packages/skymailr_client`

Install editable:

```bash
pip install -e packages/skymailr_client
```

`SkyMailrClient` (`skymailr_client.py`):

- `send_template_email`, `send_verification_email`, `send_password_reset_email`, …
- `enroll_user_in_workflow(workflow_id, ...)`
- Uses `httpx`; raises on HTTP error.

Environment helper: `client_from_env()` (reads base URL + key from env — see file for variable names).

**Not exhaustive:** For rare endpoints, call `httpx` or `curl` directly against `config/urls.py`.
