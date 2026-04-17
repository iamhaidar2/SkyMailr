# Postal provisioning bridge for SkyMailr

SkyMailr calls this service when `POSTAL_PROVISIONING_URL` is set. This bridge runs **Rails inside your Postal deployment** to create the domain (same as the Postal UI “Add domain”). SkyMailr may also call the bridge when Postal’s HTTP API already returned SPF/DKIM, so it can merge extra `dns` fields (such as Postal ownership verification TXT) that the API does not expose.

## 1. Postal: copy the runner script

Copy `runner/create_domain.rb` and `runner/delete_domain.rb` to paths **inside** the Postal web container (or mount them), e.g. `/opt/postal/bridge/create_domain.rb` and `/opt/postal/bridge/delete_domain.rb`.

## 2. Postal: environment variables

Set on the **Postal** app (same values you see in the browser URL: `/org/<org>/servers/<server>/...`):

- `POSTAL_ORG_PERMALINK` — organization permalink  
- `POSTAL_SERVER_PERMALINK` — mail server permalink  

Optional:

- `POSTAL_AUTO_VERIFY=true` — auto-mark domain verified (only if you trust SkyMailr-created domains)

## 3. Bridge service: environment

| Variable | Description |
|----------|-------------|
| `PROVISIONING_SECRET` | Must match SkyMailr `POSTAL_PROVISIONING_SECRET` |
| `POSTAL_RAILS_RUNNER_CMD` | Shell command to create domains; must include literal `{domain}` |
| `POSTAL_RAILS_DELETE_CMD` | Shell command to delete domains; must include literal `{domain}` (same pattern as create, but pointing at `delete_domain.rb`) |

Example (Docker on same host as Postal):

```text
POSTAL_RAILS_RUNNER_CMD=docker exec -i postal-web bundle exec rails runner /opt/postal/bridge/create_domain.rb {domain}
POSTAL_RAILS_DELETE_CMD=docker exec -i postal-web bundle exec rails runner /opt/postal/bridge/delete_domain.rb {domain}
```

Adjust container name and script path to your install.

## 4. SkyMailr (Railway / env)

```text
POSTAL_PROVISIONING_URL=https://<your-bridge-host>/
POSTAL_PROVISIONING_SECRET=<same as PROVISIONING_SECRET>
```

## 5. Run the bridge

**Docker:** build this directory (`docker build -t postal-bridge .`) and run with `-e PROVISIONING_SECRET=... -e POSTAL_RAILS_RUNNER_CMD=...`.  
Publish HTTPS in front (Railway, Caddy, etc.).

**Local:** `pip install -r requirements.txt` then `gunicorn --bind 0.0.0.0:8080 app:app`.

Health check: `GET /health`

## Contract

**Create:** `POST /` or `POST /provision` with JSON `{"domain":"sub.example.com"}` and header `Authorization: Bearer <secret>`.

Success: HTTP 200, JSON body with `ok`, `outcome`, `provider_domain_id`, `dns` (see SkyMailr `postal_provisioning.py`).

**Delete (used when a tenant removes a domain in SkyMailr):** `POST /delete` with the same auth and JSON `{"domain":"sub.example.com"}`. Requires `POSTAL_RAILS_DELETE_CMD`. Success JSON includes `ok: true` and `outcome` of `deleted` or `not_found` (idempotent).

### `dns` object keys

In addition to SPF/DKIM/return-path fields, the bridge may include **`postal_verification_txt_expected`**: the full TXT value Postal expects at the domain apex for domain-control verification (e.g. `postal-verification <token>`). Omitted when the domain is already verified (e.g. `POSTAL_AUTO_VERIFY=true`).

### Troubleshooting (SkyMailr UI missing verification row)

- Ensure **`POSTAL_PROVISIONING_URL`** and **`POSTAL_PROVISIONING_SECRET`** are set in SkyMailr and match the bridge.
- SkyMailr calls the bridge on each domain page load until it stores a verification string or records a successful bridge response (`postal_verification_bridge_at`). If the UI still shows only three DNS rows, check SkyMailr logs for `webhook merge after HTTP fetch` / `postal webhook merge after HTTP fetch skipped`.
- If `postal_verification_bridge_at` was set but `postal_verification_txt_expected` is still empty and Postal still shows unverified, clear the marker so SkyMailr retries:  
  `UPDATE tenants_tenantdomain SET postal_verification_bridge_at = NULL WHERE domain = 'your.domain.com';`
