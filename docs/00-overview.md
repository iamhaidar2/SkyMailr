# SkyMailr — project overview

## What it is

**SkyMailr** is a **Django** service that centralizes **outbound email** for multiple products: one place for templates, sending, retries, webhooks, suppressions, and (optionally) multi-step **workflows**. Source apps call an HTTP API with **tenant API keys**; operators use a **staff-only web UI** for day-to-day operations.

Email is sent through a **pluggable provider** (dummy / console / Postal). **LLMs are used only for drafting/revising template content**, never for choosing recipients or sending mail.

## Problem it solves

- Avoid each app (TOMEO, BrainList, ProjMan, future apps) implementing its own mail queue, templates, and provider wiring.
- Enforce **tenant isolation**, **idempotent sends**, and a clear **message lifecycle** (queued → sent → delivered/bounced/etc.).
- Provide a single place to align with **Postal** (or another provider) once DNS and infrastructure are ready.

## Who it is for

- **Source applications** that need transactional or lifecycle email (via API + optional Python client).
- **Operators** (staff) who manage templates, sends, tenants, and troubleshooting.
- **You** when deploying on Railway and later attaching a real mail server (Postal on a VPS).

## Apps / products

The codebase names these intentionally:

| Product    | Role |
|-----------|------|
| **TOMEO** | Consumer of SkyMailr alongside others |
| **BrainList** | Patterns for LLM env vars and client usage were aligned from this codebase |
| **ProjMan** | Same |

No hard-coded “only these three” limit exists in code—**new tenants** represent new apps or environments.

## What “tenant” means

A **tenant** is an **isolation boundary** in the database:

- Own **email templates** (keys are unique per tenant).
- Own **API keys**, **outbound messages**, **workflows**, **suppressions**, etc.
- Default **sender** identity (`default_sender_email`, `default_sender_name`, etc.).

Operators can **switch active tenant** in the UI header; the API always uses the tenant implied by the **API key**.

## Main subsystems (short)

| Subsystem | Purpose |
|-----------|---------|
| **API** (`apps/api`) | REST API, Bearer tenant keys |
| **Operator UI** (`apps/ui`) | Staff session auth, HTMX/Tailwind |
| **Messages** (`apps/messages`) | Outbound queue, events, idempotency records |
| **Email templates** (`apps/email_templates`) | Versioned templates, Jinja2 render, approval |
| **Providers** (`apps/providers`) | dummy / console / Postal adapters |
| **Workflows** (`apps/workflows`) | Steps + enrollments + Celery-driven execution |
| **LLM** (`apps/llm`) | Draft/revise template JSON (optional; `LLM_PROVIDER` can be `dummy`) |
| **Celery** | Dispatch, sweep queue, retries, workflow ticks |

## Maturity (honest)

**Done enough for:**

- Local and Railway deployment with **dummy** or **console** provider.
- API + UI operations; automated tests on **Python 3.11** for core paths (sends, isolation, webhooks, workflows).

**Still ahead (not claimed as “done” in code):**

- **Production Postal** on your VPS: DNS, PTR, TLS, webhook signing in anger, deliverability tuning.
- Polish of some operator UI areas (mobile sidebar, etc.)—functional, not marketing-grade.

**Docs stance:** “Current state” vs “after Postal” is called out in [12-known-limitations.md](12-known-limitations.md) and [10-hostinger-postal-setup-plan.md](10-hostinger-postal-setup-plan.md).

## Where to go next

| Goal | Doc |
|------|-----|
| Run locally | [02-local-development.md](02-local-development.md) |
| Understand flows | [01-architecture.md](01-architecture.md) |
| Tests | [03-testing.md](03-testing.md) |
| Railway | [04-railway-deployment.md](04-railway-deployment.md) |
| New app / tenant | [07-tenants-and-onboarding.md](07-tenants-and-onboarding.md) |
| Postal phase | [10-hostinger-postal-setup-plan.md](10-hostinger-postal-setup-plan.md) |
