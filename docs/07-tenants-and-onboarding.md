# Tenants and onboarding a new app

This doc is the **reference for adding a new product/tenant** to SkyMailr without rediscovering process from scratch.

## Accounts vs tenants

Every **`Tenant`** belongs to an **`Account`** (org / billing grouping). Mail, templates, workflows, and **tenant API keys** remain scoped to the tenant, not the account. For a single internal stack, operator-created tenants and seeds typically use the default internal account (`haidar-internal`).

## What a tenant needs

| Need | Why |
|------|-----|
| **`Account`** | Container for one or more tenants (use internal default or your org’s account) |
| **`Tenant` row** | Isolation root (templates, messages, keys, workflows) |
| **Sender identity** | `default_sender_email`, `default_sender_name` (and optionally compliance footer for marketing) |
| **At least one API key** | Source app authenticates with `Bearer` |
| **Templates** | `EmailTemplate` + **approved** `EmailTemplateVersion` for each key you send |
| **Provider/env** | Globally `EMAIL_PROVIDER`; per deploy, Postal URL/key when live |

Optional:

- **Sender profiles** — if you use per-brand `from` addresses (`SenderProfile` model).
- **Workflows** — if onboarding journeys are multi-step.
- **Rate limits** — `Tenant.rate_limit_per_minute` (tune before high traffic).

## Create a tenant

**Option A — Django admin:** Add `Tenant` with **account**, unique `slug`, active status, sender defaults.

**Option B — seed / migrations:** `seed_skymailr` may create demo tenants; adjust for your environment.

**Slug rules:** Lowercase, stable, used in unsubscribe and operator switching (`brainlist`, `projman`, `tomeo-prod`, …).

## Create an API key

```bash
python manage.py create_tenant_api_key <tenant_slug> --name <purpose>
```

Or **Admin API** (requires Django admin user): `POST /api/v1/tenants/api-keys/` with `tenant_slug` + `name`.

Or **Operator UI:** Tenants → tenant detail → create API key.

**Store the raw key once** in the app’s secret store (Railway env, Vault, …).

## Sender profiles (optional)

If multiple brands or from-addresses per tenant:

- Create `SenderProfile` rows linked to tenant (via admin or future UI).
- Reference from sends if your integration supports it (API/UI may use defaults when omitted).

## Seed or create templates

1. Define **`EmailTemplate`** per tenant: `key` (slug), `name`, `category`.
2. Create **`EmailTemplateVersion`** with subject/HTML/text; run **approve** (API or UI).
3. Declare **`TemplateVariable`** rows for validation (`name`, `required`, description).

**Template keys:** Use **namespaced, stable** keys: `email_verification`, `password_reset`, `collaborator_invite` — match `skymailr_client` helpers if you use them.

## Workflows (optional)

1. Create `Workflow` + `WorkflowStep` rows (send template, wait, end, …).
2. Enroll via API: `POST /api/v1/workflows/<id>/enroll/` with `metadata.template_context` for variables.

## Wire the client package

```bash
pip install -e packages/skymailr_client
```

```python
from skymailr_client import SkyMailrClient

client = SkyMailrClient(
    base_url=os.environ["SKYMAILR_BASE_URL"],
    api_key=os.environ["SKYMAILR_API_KEY"],
)
client.send_verification_email("user@example.com", {
    "user_name": "Ada",
    "verify_url": "https://...",
}, source_app="myapp")
```

Set env in the source app’s deployment:

- `SKYMAILR_BASE_URL` — production SkyMailr URL (no trailing slash issues if you follow client code)
- `SKYMAILR_API_KEY` — raw key

## Test integration (dummy / console)

1. Point app at **dev** SkyMailr with `EMAIL_PROVIDER=dummy` or `console`.
2. Send a real API request; confirm **201** and message row in admin or `/messages/`.
3. **Dummy** stores content in DB — inspect `DummyStoredEmail` via admin or provider behavior.

No inbox delivery happens — that’s expected.

## When Postal is live (later)

1. Set Railway (or Docker) env: `EMAIL_PROVIDER=postal`, `POSTAL_BASE_URL`, `POSTAL_SERVER_API_KEY`, TLS flags.
2. Configure **DNS** at your domain (SPF/DKIM/DMARC per Postal docs).
3. Register **webhook** URL in Postal → `https://<skymailr>/api/v1/webhooks/provider/postal/`.
4. Send a **test** to a mailbox you control; verify **delivered** path and `MessageEvent` rows.

Details: [10-hostinger-postal-setup-plan.md](10-hostinger-postal-setup-plan.md).

## Naming conventions (recommended)

| Concept | Pattern | Example |
|---------|---------|---------|
| `source_app` | Short product id | `brainlist`, `projman` |
| Template `key` | snake_case, stable | `email_verification` |
| Tenant `slug` | lowercase, unique | `brainlist-prod` |
| Idempotency key | Include app + logical op + id | `brainlist-verify-user-uuid-123` |
| Workflow `slug` | short, unique per tenant | `onboarding_v2` |

## Related

- Architecture: [01-architecture.md](01-architecture.md)
- API details: [06-api-and-auth.md](06-api-and-auth.md)
- Templates/workflows: [08-templates-and-workflows.md](08-templates-and-workflows.md)
