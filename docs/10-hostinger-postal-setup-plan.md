# Hostinger VPS + Postal — execution plan (next phase)

**Status:** This is a **forward-looking plan**. Postal is **not** pre-installed in this repo; you will install and operate it on infrastructure you control.

**Goal:** Run **Postal** (open-source mail platform) on a VPS, then point SkyMailr at Postal for real SMTP/API delivery and webhooks.

---

## Why a VPS

- Postal (typical install) expects a **long-running Linux host** with Docker (or similar), public HTTPS, and control over **port 25** if you send directly (many cloud PaaS block port 25 — **verify Hostinger policy** for your plan).
- Railway hosts **SkyMailr**, not necessarily your MTA — separation is normal.

## Prerequisites (before you buy)

- [ ] Domain(s) you can manage **DNS** for (SPF, DKIM, MX if receiving).
- [ ] SkyMailr deployed and **healthy** on Railway (`/api/v1/health/`).
- [ ] Decision: **one** Postal server for multiple domains vs split (start with one).
- [ ] Read Postal’s **current** official install docs (version changes) — this doc does not replace them.

## 1. Buy and size the VPS

- Choose a plan with enough **RAM** for Postal’s stack (check Postal docs for minimums; err upward).
- **Region:** Close to users or to Postal’s expectations — less critical than **stable IP** for reputation.
- Note the **public IP** for DNS A records and PTR discussions with Hostinger support.

## 2. Secure the server

- SSH key auth, disable password login, firewall (**22**, **80**, **443**; **25** only if you truly need inbound SMTP for Postal’s role — follow Postal docs).
- Non-root deploy user where possible.
- **Automatic security updates** (unattended-upgrades on Debian/Ubuntu) or equivalent.

## 3. Install Docker (if using Postal’s Docker path)

Most Postal guides assume **Docker** + **docker-compose**. Install per your OS; verify `docker run hello-world`.

## 4. Email infrastructure realities (non-expert primer)

| Term | Why it matters |
|------|----------------|
| **SPF** | DNS TXT: which IPs/domains may send mail for your domain |
| **DKIM** | Cryptographic signature on messages — DNS TXT records from Postal |
| **DMARC** | Policy for SPF/DKIM failures (start with `p=none` monitoring, tighten later) |
| **PTR / reverse DNS** | Some receivers require matching forward/reverse for the **sending IP** — ask Hostinger about **rDNS** for your VPS IP |
| **Port 25** | Many providers block **outbound** 25 by default — confirm Hostinger allows **outbound SMTP** for your use case |

SkyMailr does not configure DNS for you — **Postal’s UI/docs** generate the records you paste into your DNS host.

## 5. Hostname planning

- Choose a **stable FQDN** for Postal’s web UI and API, e.g. `postal.yourdomain.com`.
- Point **A/AAAA** records to the VPS IP.
- Obtain **TLS certificates** (Let’s Encrypt via Caddy/Traefik/nginx or Postal’s bundled approach — follow Postal docs).

## 6. Install Postal

- Follow **official Postal installation** for your chosen version.
- Store **server API key** and **base URL** securely — SkyMailr will need them as `POSTAL_SERVER_API_KEY` and `POSTAL_BASE_URL`.

## 7. DNS work (sending domain)

- Add Postal-provided **SPF**, **DKIM**, and optionally **MX** if receiving.
- **Warm up** sending: low volume first; monitor bounces and reputation.

## 8. Connect SkyMailr (Railway env)

When Postal is ready:

```env
EMAIL_PROVIDER=postal
POSTAL_BASE_URL=https://postal.yourdomain.com
POSTAL_SERVER_API_KEY=<from Postal>
POSTAL_USE_TLS_VERIFY=true
```

Redeploy SkyMailr; verify `/api/v1/providers/health/` with `EMAIL_PROVIDER=postal`.

## 9. Webhooks

- In Postal, configure HTTP webhook URL:

  `https://<your-skymailr-host>/api/v1/webhooks/provider/postal/`

- Payload must include identifiers SkyMailr can match to **`OutboundMessage.provider_message_id`** after send (see `ProviderWebhookService._apply_normalized`).
- Optional: HMAC using `X-SkyMailr-Signature` — code path exists; **wire secrets per environment** when you need it.

## 10. First real email test

1. Send via `POST /api/v1/messages/send-template/` with a **small** test template.
2. Confirm in SkyMailr: status **`sent`**, then webhook-driven **`delivered`** (or bounce path).
3. Check recipient inbox + **Postal** message log.

## 11. Rollout advice

- Keep **`dummy`/`console`** on staging; use **Postal** only on production (or dedicated Postal org).
- **Rate limits:** tune `Tenant.rate_limit_per_minute` before marketing bursts.
- **Monitor:** Railway logs + Postal + recipient bounce rates.

## Risks and gotchas

- **Port 25 / reputation:** new IP + new domain = cautious ramp.
- **PTR:** without rDNS, some providers defer or reject mail — escalate with Hostinger if mail is rejected for IP reputation reasons.
- **SkyMailr webhook schema** vs Postal’s event JSON — if events don’t update messages, compare `normalized` in `ProviderWebhookEvent` to `apps/providers/webhook_service.py`.

## Related

- [11-production-checklists.md](11-production-checklists.md) — post-Postal checklist
- [09-debugging-and-runbook.md](09-debugging-and-runbook.md) — when something fails
