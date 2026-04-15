# Known limitations

Honest boundaries — for planning, not excuses.

## Not production-proven in all dimensions

- **Postal on Hostinger** is a **planned** integration path — not battle-tested in this repo’s CI.
- **Deliverability** (reputation, throttling, ISP quirks) depends on DNS, IP, and content — SkyMailr does not replace ESP deliverability tooling.

## Depends on Postal not yet connected

- Real inbox delivery, bounce/complaint streams from real providers, and **full** webhook field alignment are validated **lightly** in automated tests (mocked/dummy paths).
- **HMAC webhook verification** exists in code but end-to-end **tenant-specific** secrets in production are **your** wiring task.

## Operator UI maturity

- **Desktop-first**; mobile sidebar/navigation may be minimal.
- Analytics are **operational** (messages, events, webhooks), not marketing campaign analytics.

## Testing gaps (as of current suite)

- No automated **load** or **concurrency** tests.
- **Postal HTTP** not exercised against a live server in CI.
- **UI tests** are smoke-level; prefer **Python 3.11** (see [03-testing.md](03-testing.md)).

## Intentionally deferred (post-MVP)

- Full **multi-region** or **multi-provider routing** beyond the single `get_email_provider()` selection.
- Rich **email editor** in browser — templates are HTML/text + Jinja.
- **End-user** subscription management UI beyond API + operator lists.

## What *is* in good shape for the next phase

- Core **message pipeline**, **tenant isolation** on API, **idempotency** behavior, **workflow** dispatch path, and **webhook ingestion** storage/update logic are covered by tests on **Python 3.11** — see [03-testing.md](03-testing.md).

For Postal work, start with [10-hostinger-postal-setup-plan.md](10-hostinger-postal-setup-plan.md).
