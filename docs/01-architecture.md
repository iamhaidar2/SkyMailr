# Architecture

## Layer map

| Layer | Django app(s) | Responsibility |
|--------|----------------|------------------|
| **HTTP API** | `apps/api` | DRF views, `Bearer` tenant API key auth |
| **Operator UI** | `apps/ui` | Session-auth staff UI; calls same services as API where possible |
| **Messages** | `apps/messages` | `OutboundMessage`, events, idempotency, Celery dispatch |
| **Templates** | `apps/email_templates` | `EmailTemplate`, versions, variables, render + validation |
| **Providers** | `apps/providers` | `BaseEmailProvider` + dummy / console / Postal |
| **Workflows** | `apps/workflows` | `Workflow`, steps, enrollments, executions |
| **LLM** | `apps/llm` | Clients for structured JSON (draft/revise flows only) |
| **Accounts** | `apps/accounts` | `Account`, `AccountMembership` — org layer above tenants (mail data still isolated per tenant) |
| **Tenants** | `apps/tenants` | `Tenant` (required `account` FK), `TenantAPIKey`, crypto for keys |
| **Subscriptions** | `apps/subscriptions` | Unsubscribe + suppression checks used by pipeline |

**Orchestration:** `config/celery.py` + `apps/messages/tasks.py`, `apps/workflows/tasks.py`, plus **django-celery-beat** schedules in `config/settings/base.py` (sweep dispatch, workflow ticks, retry deferred).

## Provider modes

| Mode | `EMAIL_PROVIDER` | Behavior |
|------|------------------|----------|
| **dummy** | `dummy` (default) | Stores payload in DB (`DummyStoredEmail`); no network; good for dev/tests |
| **console** | `console` | Logs email; no real delivery |
| **Postal** | `postal` | HTTP API to Postal server (`POSTAL_BASE_URL`, `POSTAL_SERVER_API_KEY`, etc.) |

Adapter health: `get_email_provider().health_check()` — used by `/api/v1/providers/health/` and operator **Provider health** page. For **postal**, this probes host reachability plus a no-op API POST (see [09-debugging-and-runbook.md](09-debugging-and-runbook.md)); it does not prove inbox delivery.

## How source apps interact

1. Obtain a **tenant API key** (management command or admin).
2. `POST /api/v1/messages/send-template/` or `/api/v1/messages/send/` with `Authorization: Bearer <key>`.
3. Optionally use **`packages/skymailr_client`** (`SkyMailrClient`) wrapping the same paths.
4. Poll `GET /api/v1/messages/<uuid>/` and `GET /api/v1/messages/<uuid>/events/` for status.
5. Provider webhooks (e.g. Postal) `POST` to `/api/v1/webhooks/provider/<provider>/` to update delivery-related state when `provider_message_id` matches.

## Important models (where truth lives)

| Model | Role |
|-------|------|
| `Account` | Org / plan container; owns many `Tenant`s |
| `AccountMembership` | Django `User` ↔ `Account` with role |
| `Tenant` | Isolation root for mail data; sender defaults, rate limits, API keys; **belongs to an `Account`** |
| `TenantAPIKey` | Hashed keys; `Bearer` resolves to one tenant |
| `EmailTemplate` / `EmailTemplateVersion` | Versioned content; **approved** version drives sends |
| `TemplateVariable` | Declared variables + required flags for validation |
| `OutboundMessage` | One send attempt pipeline: subject/html/text rendered, status, `provider_message_id` |
| `MessageEvent` | Append-only-ish log (queued, sent, failed, delivered, …) |
| `IdempotencyKeyRecord` | Dedupes sends per tenant + idempotency key string |
| `ProviderWebhookEvent` | Raw + normalized webhook payload for audit |
| `Workflow` / `WorkflowStep` / `WorkflowEnrollment` / `WorkflowExecution` | Multi-step journeys |

## Business logic placement

- **Send pipeline:** `apps/messages/services/send_pipeline.py` — suppression, render, schedule, enqueue Celery dispatch.
- **Dispatch:** `apps/messages/services/dispatch.py` — sets provider, calls `send_message`, updates status/events.
- **Message actions:** `apps/messages/services/message_actions.py` — retry/cancel rules.
- **Webhooks:** `apps/providers/webhook_service.py` — ingest JSON, persist event, map events to messages by `provider_message_id`.
- **Template validation/render:** `apps/email_templates/services/validation_service.py`, `render_service.py`.
- **Workflow engine:** `apps/workflows/services/workflow_engine.py` — `enroll_workflow`, `process_due_executions`.

## Message lifecycle (high level)

1. **Request** — API or UI calls `create_raw_message` or `create_templated_message`.
2. **Suppression** — If suppressed → `OutboundMessage` status **suppressed** + event; no provider call.
3. **Render** — Templated: validate context, render **current approved version**; on failure → **failed** (persisted) + event.
4. **Schedule** — `apply_send_schedule`: **rendered** → **queued** with `send_after` when applicable.
5. **Dispatch** — Celery `dispatch_message_task` → provider `send_message` → **sending** → **sent** or **failed** (with retries/defer).
6. **Webhook** — Optional: normalized payload updates **delivered** / **bounced** / **complained** when `provider_message_id` matches.

Statuses include: `queued`, `rendered` (transient in DB during pipeline), `sending`, `sent`, `deferred`, `failed`, `delivered`, `bounced`, `complained`, `suppressed`, `cancelled`, etc. (see `OutboundStatus` in `apps/messages/models.py`).

---

## Flow 1: Templated API send

```text
Client → POST /api/v1/messages/send-template/ (Bearer key)
  → SendTemplateView → create_templated_message()
      → Idempotency check (optional, by key)
      → OutboundMessage row, render from approved version
      → Celery dispatch_message_task (if queued)
  → EmailDispatchService.dispatch() → provider.send_message()
  → MessageEvent(s)
```

**Idempotency:** Same tenant + same `idempotency_key` returns the **same** `OutboundMessage` (HTTP 200 on replay after first 201).

---

## Flow 2: Workflow-triggered send

```text
Enrollment + enroll_workflow() → WorkflowExecution
Celery beat: process_workflow_due_steps → process_due_executions()
  → Step SEND_TEMPLATE → create_templated_message(..., workflow_execution=...)
      → same pipeline as above (dispatch queued from send_pipeline)
  → Step runs recorded; execution advances or completes
```

Workflow mail uses the **same** pipeline as API sends; ensure templates are **approved** and context is in enrollment `metadata` (e.g. `template_context`).

---

## Flow 3: Webhook update

```text
Postal (or test client) → POST /api/v1/webhooks/provider/postal/
  → ProviderWebhookService.ingest()
      → ProviderWebhookEvent saved
      → _apply_normalized(): find OutboundMessage by provider_message_id
      → Update status + MessageEvent (delivered / bounced / complained)
```

If no message matches `message_id` / `id` in payload, the event is still stored; no message update.

## LLM boundaries

- **LLM:** `TemplateLLMService` — generate/revise **template versions** (draft content). Config: `LLM_PROVIDER`, provider API keys (see `config/settings/base.py`).
- **Not LLM:** recipient selection, suppression, sending, idempotency, webhooks — all **deterministic code**.
