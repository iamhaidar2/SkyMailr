# Operator UI guide

**Audience:** Staff users with `is_staff` (and typically superuser). **Auth:** Django session login at `/login/`.

## Global behavior

- **Tenant switcher (header):** Many actions use the **active tenant** (templates, sends, new workflows). Wrong tenant → wrong templates or confusing errors.
- **Tenant banner:** Shown on tenant-sensitive pages (e.g. template studio, new template, workflows) — reminds you which tenant is active.
- **CSRF:** Forms require a valid session; production needs `CSRF_TRUSTED_ORIGINS` for HTTPS domains.

---

## Dashboard (`/`)

- **Purpose:** Overview, setup/delivery hints, quick links.
- **Actions:** Navigate to messages, send, templates, etc.
- **Notes:** “Adapter health” vs “outbound delivery” distinguishes **provider responding** from **real email** (dummy/console do not deliver to inboxes).

## Messages (`/messages/`, `/messages/<uuid>/`)

- **Purpose:** List and inspect **outbound messages** for monitoring.
- **Actions:** Open detail, retry/cancel where status allows (same rules as API).
- **Traps:** Status comes from pipeline + webhooks; dummy provider will show **sent** without real internet mail.

## Send email (`/send/`)

- **Purpose:** Manual **raw HTML** or **templated** sends for testing operators.
- **Actions:** POST to `/send/raw/` or `/send/template/`; optional HTMX previews (`/send/preview/raw/`, `/send/preview/template/`).
- **Traps:** Must select **active tenant**. Failed template render shows form error; idempotent replays redirect to existing message.

## Templates (`/templates/`, `/templates/<uuid>/`, `/templates/new/`)

- **Purpose:** Browse templates, **approve** versions, preview with JSON context, LLM revise.
- **Actions:** Filter by tenant slug/id; open detail; approve; preview.
- **Traps:** Sending via API uses **approved** version only — unapproved content is not used for production sends.

## Template studio (`/template-studio/`)

- **Purpose:** LLM-assisted **draft** generation from a brief (creates/updates template + draft version).
- **Actions:** Submit brief; redirects toward template detail for review.
- **Traps:** Requires active tenant; LLM must be configured if not `dummy`. **Review and approve** before relying on sends.

## Workflows (`/workflows/`, `/workflows/<uuid>/`)

- **Purpose:** Define multi-step flows; enroll recipients; add steps on detail page.
- **Actions:** Create workflow (POST `workflow_new`), add steps, enroll.
- **Traps:** Empty list shows onboarding panel. Workflow mail uses **enrollment metadata** (e.g. `template_context`) — must match template variables.

## Tenants (`/tenants/`)

- **Purpose:** View tenants; create API keys per tenant (UI flow).
- **Actions:** Inspect slug, limits; issue new keys.
- **Traps:** API key shown **once** — store securely.

## Provider health (`/providers/health/`)

- **Purpose:** Same idea as `/api/v1/providers/health/` — adapter check + delivery context.
- **Notes:** “Healthy” means the **adapter** responds; dummy/console still mean **no real inbox delivery**.

## Webhooks (`/webhooks/`)

- **Purpose:** Inspect **ingested** `ProviderWebhookEvent` rows (audit/debug).
- **Notes:** Does not replace Postal’s UI for delivery analytics.

## Suppressions / Unsubscribes (`/suppressions/`, `/unsubscribes/`)

- **Purpose:** Lists for compliance debugging (who is suppressed or unsubscribed).
- **Notes:** Marketing suppression logic is in pipeline + models — see architecture doc.

## Setup (`/setup/`)

- **Purpose:** Checklist-style view of environment/setup status (delivery vs adapter, etc.).
- **Notes:** Complements dashboard; not a substitute for reading env on Railway.

## What’s rough / incomplete

- **Mobile:** Sidebar/hamburger may be minimal — desktop-first operator experience.
- **Operator UI is not a full ESP** — analytics, A/B tests, and deep deliverability tooling are out of scope.
