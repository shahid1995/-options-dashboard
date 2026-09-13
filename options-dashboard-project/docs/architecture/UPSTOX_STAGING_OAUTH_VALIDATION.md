# StrikeNova — Upstox REAL OAuth: STAGING Validation

Date: 2026-09-13
Scope: preparation + validation state for the real (non-sandbox) Upstox
OAuth broker-connection flow on staging

```text
Vercel staging  →  https://strikenova-frontend-staging.vercel.app
Render staging  →  https://strikenova-api-staging.onrender.com
CockroachDB     →  strikenova-staging / strikenova_staging
```

Predecessor documents:

* `UPSTOX_SANDBOX_STAGING_VALIDATION.md` — sandbox audit; concluded the sandbox
  is a portal-token order simulator with **no OAuth flow**, so a dedicated
  **live** Upstox Developer App for staging is the correct vehicle for
  broker-connect validation
* `STAGING_SMOKE_TEST.md`, `STAGING_BROWSER_ACCEPTANCE.md` — staging baseline

---

## 1. Staging Developer App configuration (required user action — PENDING)

If no dedicated staging Developer App exists yet, create one in the Upstox
developer portal with **exactly**:

```text
App name:      StrikeNova Staging (any name that identifies staging clearly)
Type:          Live developer app (NOT a sandbox app)
Redirect URI:  https://strikenova-api-staging.onrender.com/auth/callback
```

* Do **not** modify the production Upstox application.
* Do **not** reuse any existing production app credentials.
* The API **key** (client id) is public by design; the API **secret** must go
  only into Render staging's secret store (see §3).

## 2. Exact redirect URI (verified from code, not invented)

* Callback route: `GET /auth/callback` on the auth router (mounted at `/auth`)
  → `https://strikenova-api-staging.onrender.com/auth/callback`.
* The Vercel **frontend** URL is never used as the Upstox redirect URI.

### Derivation proof

`app/config.py` derives `UPSTOX_REDIRECT_URI` (priority: explicit env var →
`BACKEND_URL` → `RAILWAY_PUBLIC_DOMAIN`) and appends `/auth/callback`. With
`BACKEND_URL` set and `UPSTOX_REDIRECT_URI` unset, the committed code
produces exactly:

```text
UPSTOX_REDIRECT_URI = https://strikenova-api-staging.onrender.com/auth/callback
```

This was verified by executing the committed `config.py` against the staging
`BACKEND_URL` value in a clean environment (PASS), not by assumption.

## 3. Render configuration (variable NAMES only; values never printed)

Render staging env vars after this task:

```text
ADDITIONAL_CORS_ORIGINS   (pre-existing, preserved)
BACKEND_URL               (NEW — https://strikenova-api-staging.onrender.com)
DATABASE_URL              (pre-existing, preserved)
GOOGLE_CLIENT_ID          (pre-existing, preserved)
TOKEN_ENCRYPTION_KEY      (pre-existing, preserved)
```

* `UPSTOX_REDIRECT_URI` is deliberately **not** set — the app derives it from
  `BACKEND_URL` (verified above).
* `UPSTOX_API_KEY` / `UPSTOX_API_SECRET`: **PENDING the user's staging app**.
  When provided, they go into Render staging secret storage only (never Git,
  logs, test output, or the frontend). Note the BYOB architecture prefers
  per-user credentials stored encrypted per connection
  (`POST /auth/connect`); service-level `UPSTOX_*` vars are the documented
  fallback and are not required for the per-user flow.

**Deployment:** manual deploy `dep-dajco2fqj5pc73d3uhe0` → **live** at commit
`f1dea0a` (auto-deploy remains OFF; exactly one deployment triggered).

## 4. OAuth flow (from committed code)

```text
authenticated StrikeNova user (platform session required — Day-3 gate)
  → POST /auth/connect        (per-user API key/secret, Fernet-encrypted →
                               BrokerConnection status="pending")
  → GET /auth/login?broker=UPSTOX
      · 401 without session; 400 if no BYOB credentials
      · state = HMAC-signed create_oauth_state(session_id, broker) (single-use)
      · 302 → https://api.upstox.com/v2/login/authorization/dialog
              ?response_type=code&client_id=<user key>
              &redirect_uri=<derived>&state=<signed>
  → Upstox login + consent (user, normal browser; no OTP captured by anyone)
  → 302 → /auth/callback?code=…&state=…
      · consume_oauth_state: HMAC verify + session binding + single use
      · exchange: POST /v2/login/authorization/token
        {code, client_id, client_secret, redirect_uri, grant_type} — server-side
      · get_profile → get_or_create_user_from_upstox
      · get_or_create_connection → status="connected" + real broker_account_id
      · set_token → Fernet ciphertext in broker_tokens (hashed session key)
      · 302 → dashboard#session_id=… + HttpOnly Secure cookie
```

## 5–6. Token exchange, encryption/storage

* Exchange happens **server-side only**; the secret is read from the user's
  encrypted `broker_connections` row (or service env fallback) and is never
  sent to any client.
* Access token: encrypted at rest (Fernet AES-128-CBC + HMAC-SHA256; key
  derived PBKDF2-HMAC-SHA256/480k from `TOKEN_ENCRYPTION_KEY`); session id
  stored only as a hash; **no endpoint returns token material** (proven live
  by the staging smoke suite's echo/paranoia checks).
* Disconnect semantics (current app contract): logout clears the session and
  NULLs the encrypted broker token for that session;
  `DELETE /auth/analytics-token` deactivates data-only connections. A
  dedicated "disconnect broker" endpoint does **not** exist yet (recorded as
  a follow-up, not fixed in this task).

## 7–9. Connection state, profile, funds — PENDING the staging app + consent

All three require the user's Developer App (§1) and the interactive Upstox
consent (§10 of the task). The API surfaces to be exercised are already
mapped and partially verified:

* connection state transitions verified in code (pending → connected);
  brokerless graceful states verified live (`BROKER_AUTH_REQUIRED` etc.)
* `GET /paper/broker/profile` — the endpoint to validate post-consent
* `GET /paper/capital` — StrikeNova-side CRDB path verified live; the broker
  funds leg requires the connected token

## 10–11. Positions / orders, market data

* `BROKER ORDER EXECUTION NOT IMPLEMENTED — NOT PART OF THIS TASK` — the
  application is paper-trading-only by design; no Upstox order endpoints are
  called.
* `MARKET DATA VALIDATION DEFERRED — PROVIDER/MARKET CONDITIONS` (plus API
  permissions on the staging app).

## 12. WebSocket

Previously validated at the connection layer (101 + accept-key proof,
automated). Post-consent streaming validation (subscription → first data
frame → reconnect) becomes possible only after §7–9; it additionally depends
on the market feed being available for the staging app's permissions and
market hours. **PENDING.**

## 13. Disconnect

Current contract: logout (token cleared for the session) and analytics-token
removal (connection deactivated). No dedicated broker-disconnect endpoint
exists — documented follow-up.

## 14. Negative paths (already verified live)

`GET /auth/login` unauthenticated → 401 (no Upstox URL leaked); authenticated
without BYOB credentials → 400 with no redirect; `POST /auth/connect`
unauthenticated → 401; `GET /paper/broker/profile` without broker → 200
`unavailable/BROKER_AUTH_REQUIRED`; `DELETE /auth/analytics-token` without
token → 404. Two-user isolation PASS (B cannot see or remove A's token).

## 15. Automation

`backend/tests/staging_smoke/test_staging_broker_smoke.py` (opt-in
`STAGING_SMOKE=1 STAGING_BROKER_SMOKE=1`, 8 tests, all passing live) covers
the deterministic broker-path surface. Live OAuth/consent legs are inherently
non-automatable (human consent, real credentials in the provider's UI); post-
connection checks (profile shape, isolation, disconnect effects) can be added
after §7–9 succeed.

## 16. Limitations

1. OAuth authorization + consent + token exchange + profile + funds + WS
   streaming are **PENDING** the staging Developer App and user consent.
2. A dedicated broker-disconnect endpoint does not exist (logout covers
   session-scoped token removal).
3. Market data depends on live market conditions and app permissions.
4. `UPSTOX_API_KEY`/`UPSTOX_API_SECRET` are not yet configured anywhere
   (nothing to expose); when provided they must go only into Render staging's
   secret store.

## 17. Production safety

```text
Production Upstox app touched:   NO (no Upstox console accessed)
Production broker used:          NO
Real order submitted:            NO
Vercel production touched:       NO
Railway touched:                 NO
Production DB touched:           NO
Production Google OAuth touched: NO
Production DNS changed:          NO
API secret exposed:              NO (none exists yet; never printed)
Access token exposed:            NO (none exists yet; never printed)
Secrets committed:               NO
```
