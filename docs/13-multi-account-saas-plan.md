# Multi-account SaaS plan

This doc turns SkyMailr from an internal multi-tenant email orchestration tool into a customer-facing application email automation service.

## Why this exists

SkyMailr already has:

- tenant-isolated message pipeline
- tenant API keys for source apps
- templates, workflows, suppressions, webhooks
- staff/operator UI
- Postal-backed outbound delivery

What it does **not** have yet is a proper **account layer** above tenants so one customer can own one or more tenants/apps without using staff-only surfaces.

---

## Target product shape

One SkyMailr deployment should support:

- many **accounts** (customer organizations)
- each account with many **users**
- each account with one or more **tenants/apps**
- each tenant with its own:
  - API keys
  - sender defaults and sender profiles
  - sending domains
  - templates
  - workflows
  - messages/events/webhooks/suppressions

### Example

- Account: `Acme Inc`
  - Users: owner, engineer, marketer
  - Tenants:
    - `acme-app`
    - `acme-admin`

- Account: `Haidar Internal`
  - Tenants:
    - `skymailr`
    - `brainlist`
    - `tomeo`
    - `kanassist`

---

## Design principles

1. **Keep tenants as the isolation root for mail data**
   - Messages, templates, workflows, API keys, suppressions, sender profiles remain tenant-scoped.
2. **Add accounts above tenants**
   - Accounts group tenants for ownership, billing, and portal permissions.
3. **Reuse Django auth**
   - Prefer extending around `django.contrib.auth.User` rather than inventing a second auth system.
4. **Keep staff/operator UI separate from customer portal**
   - Staff can see everything.
   - Customers can only see their account and its tenants.
5. **Do not break existing source-app integrations**
   - Tenant API key auth stays the same.
6. **Migrate internal tenants safely**
   - Existing tenants must be assigned to a default internal account.

---

## New domain model

### 1. Account

Add a new model, e.g. `Account`.

Suggested fields:

- `id`
- `name`
- `slug`
- `status` (`active`, `suspended`, `cancelled`)
- `owner_user` (optional convenience FK)
- `billing_email`
- `plan_code`
- `metadata` (JSON)
- `created_at`
- `updated_at`

Purpose:

- ownership root for customer org
- billing/usage grouping
- tenant grouping for UI/permissions

### 2. AccountMembership

Suggested fields:

- `id`
- `account`
- `user`
- `role` (`owner`, `admin`, `editor`, `viewer`, `billing`)
- `is_active`
- `created_at`
- `updated_at`

Purpose:

- grants a user access to one account
- supports multiple users per account
- supports one user belonging to multiple accounts later if needed

### 3. Tenant changes

Add to `Tenant`:

- `account = ForeignKey(Account, related_name="tenants", on_delete=PROTECT or CASCADE per product choice)`

Recommendation:

- use `PROTECT` so deleting an account requires an explicit cleanup path

Tenant still remains the operational mail isolation root.

---

## Permissions model

### Staff

- full platform access
- existing operator UI remains staff-only
- can impersonate/switch across all tenants/accounts

### Customer roles

#### owner
- full access to account
- manage members
- manage tenants
- manage billing (later)
- manage API keys, domains, sender profiles, templates, workflows

#### admin
- same as owner except destructive account/billing actions

#### editor
- manage templates, workflows, test sends, view messages
- no billing, no membership management

#### viewer
- read-only analytics/logs/config

#### billing
- billing-only later

---

## Portal split

### 1. Operator UI (existing)
Keep as internal/staff UI.

Paths stay roughly as they are:
- `/login/`
- `/tenants/`
- `/messages/`
- `/templates/`
- `/providers/health/`

### 2. Customer Portal (new)
Add a customer-facing area, e.g.:
- `/app/`
- `/app/accounts/<slug>/...`

Suggested sections:
- dashboard
- tenants/apps
- API keys
- sender profiles
- sending domains
- templates
- workflows
- messages
- events/webhooks
- suppressions
- members
- usage/billing (later)

Important:
- do not expose staff-only diagnostics or global provider controls
- do not expose other customers' tenants

---

## Minimum viable account-aware features

### Phase A — data model + safe migration
1. Add `Account` model
2. Add `AccountMembership` model
3. Add `Tenant.account`
4. Data migration:
   - create internal account, e.g. `Haidar Internal`
   - attach all existing tenants to that account
5. Add admin registration for new models
6. Add tests for account/tenant relationships

### Phase B — customer auth + portal guardrails
1. Reuse Django `User`
2. Add customer login flow (session-based)
3. Add account membership checks
4. Add decorators / permission helpers:
   - `account_member_required`
   - `account_role_required`
5. Add account switcher if user belongs to multiple accounts
6. Add tests for account access isolation

### Phase C — customer-facing tenant management
1. Customer can create/edit tenants in their account
2. Customer can manage:
   - sender defaults
   - sender profiles
   - sending domain metadata
   - API keys
3. Restrict all lists/details by account membership
4. Add activity logs around key changes

### Phase D — customer template/workflow self-serve
1. Template CRUD in portal
2. Approve/revise/preview template versions
3. Workflow CRUD and enrollment tools
4. Message logs and event timelines per tenant

### Phase E — onboarding + billing hooks
1. self-serve signup
2. create first account
3. create first tenant/app
4. generate first API key
5. billing placeholders / plan limits
6. usage metering hooks

---

## Migration strategy

### Existing production data

Current state:
- tenants already exist
- internal apps already use tenant API keys
- operator UI is staff-only

Migration plan:
1. deploy models with `Tenant.account` nullable initially
2. create a data migration that:
   - creates `Account(name="Haidar Internal", slug="haidar-internal")`
   - assigns all existing tenants to it
3. follow-up migration makes `Tenant.account` non-nullable
4. add membership rows for your Django staff user(s)

This avoids breaking existing tenant-key integrations.

---

## API implications

### Keep tenant-key auth for source apps
Source apps should continue to authenticate by tenant API key.

That means:
- no change required for BrainList/Tomeo/KanAssist integration pattern
- account layer mostly affects portal UX, ownership, billing, and admin permissions

### Add account-aware customer session APIs
Potential new portal endpoints:
- `GET /api/v1/account/me/`
- `GET /api/v1/account/tenants/`
- `POST /api/v1/account/tenants/`
- `GET /api/v1/account/members/`
- `POST /api/v1/account/api-keys/rotate/`

Do **not** expose cross-tenant data outside the owning account.

---

## DNS / sending domain model

Long term, customers should be able to attach one or more sending domains/subdomains.

For each tenant/app, support:
- desired sending domain
- verification state
- DNS instructions/status
- sender profiles constrained to verified sending domains

Recommended product shape:
- one Postal server
- many customer sending subdomains
- per-domain warmup guidance

---

## Operational requirements before public launch

SkyMailr should not be marketed as fully Mailgun-like until these are in place:

1. account layer + memberships
2. customer portal
3. plan/usage limits
4. abuse controls / account suspension path
5. domain verification UX
6. webhook verification hardening
7. billing integration
8. audit logs
9. support workflows
10. documented warmup / deliverability guidance

---

## MVP definition for public beta

SkyMailr can reasonably be offered as a limited public beta when all of the following are true:

- customer account can sign in
- customer can own multiple tenants/apps
- customer can create/rotate tenant API keys
- customer can manage sender defaults and sender profiles
- customer can create and approve templates
- customer can send test emails and inspect message events
- Postal-backed sending is live with SPF/DKIM/DMARC guidance
- account isolation tests pass
- internal staff can suspend or disable abusive accounts

---

## Recommended implementation order

### Sprint 1
- add `Account`
- add `AccountMembership`
- add `Tenant.account`
- migration for existing tenants
- tests

### Sprint 2
- account membership permissions
- customer login/session scaffold
- basic customer portal shell

### Sprint 3
- tenant management in customer portal
- API key management in customer portal
- sender defaults / sender profile management

### Sprint 4
- templates + workflows in customer portal
- account-scoped dashboards and logs

### Sprint 5
- onboarding flow
- soft billing/limits
- abuse/suspension controls

---

## KanAssist / internal apps now

Until the account layer lands, internal apps should continue to integrate tenant-first:

- one tenant per app/brand/environment as needed
- tenant API key in source app env
- templates/workflows per tenant
- sender profiles constrained to verified sending domains

This remains compatible with the future account model because tenants will simply be grouped under an owning account.

---

## Open questions

1. Can one account own tenants across multiple brands/domains? (probably yes)
2. Should tenant deletion be soft-delete only once customers exist? (probably yes)
3. Should account users see one merged message view across all owned tenants, or switch per tenant by default? (recommend both: default account dashboard + tenant drill-down)
4. Will billing be account-level only, or also tenant-level quotas? (recommend account-level billing, tenant-level operational limits)
5. Do we need invite-only customer onboarding for first beta? (recommend yes)

---

## Immediate next implementation task

Start with the data model and migration:

- create `Account`
- create `AccountMembership`
- attach `Tenant` to `Account`
- migrate existing tenants into one internal account
- add permission helpers and tests

This is the foundation everything else depends on.
