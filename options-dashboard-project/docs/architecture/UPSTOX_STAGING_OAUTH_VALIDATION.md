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

---

## 18. Credential intake status (2026-09-13, staging app created)

The user created the dedicated staging Developer App:

```text
App:          StrikeNova Staging
Redirect URI: https://strikenova-api-staging.onrender.com/auth/callback  (matches derivation)
```

Configuration re-verified after app creation: Render staging env is exactly
`[ADDITIONAL_CORS_ORIGINS, BACKEND_URL, DATABASE_URL, GOOGLE_CLIENT_ID,
TOKEN_ENCRYPTION_KEY]`, `BACKEND_URL` correct, health/readiness 200.
`UPSTOX_*` service vars intentionally not set yet.

**Credential channel (no chat paste, per the task rules):** a local-only
intake file `~/.strikenova_upstox_staging.txt` has been created with two
placeholder lines (`UPSTOX_API_KEY=`, `UPSTOX_API_SECRET=`). The user fills
the two values from the "StrikeNova Staging" app page; the agent then, in a
single in-process step, writes them to Render staging's secret store
(`UPSTOX_API_KEY` / `UPSTOX_API_SECRET`) and **deletes the file**. The secret
never appears in chat, Git, logs, or test output.

**Important discovery:** the repo-local `backend/.env` (mtime 2026-08-23)
contains Upstox credentials whose registered redirect URI is
`http://localhost:8000/auth/callback` — a **dev-app** registration, not the
new staging app. Upstox enforces redirect-URI matching on live apps, so those
credentials **cannot** be used for the staging flow and were NOT copied
anywhere. The staging app's own credentials must come through the intake
file.

Once the intake file is filled, the remaining execution order is: (1) write
both values to Render staging + verify by name, (2) exactly one manual deploy,
(3) health/readiness + smoke suites (`STAGING_SMOKE=1`, broker suite with
`STAGING_BROKER_SMOKE=1`), (4) generate the real authorization URL from the
app and hand it to the user for browser consent, (5) verify callback →
server-side exchange → encrypted storage → connection state → profile →
funds → disconnect semantics, then (6) update §7–§13 of this report with
results.

## §19 — Live staging OAuth attempt and identity-merge blocker (2026-09-13, late evening)

### 19.1 App identification (read-only)

The Upstox developer portal contains exactly **ONE** app:

* name: `My Options Dashboard`
* registered redirect: `https://strikenova-api-staging.onrender.com/auth/callback`

Classification: **STAGING (Case C)** — the redirect is exactly the intended
staging URL. Its API key is the pair already deployed on Render staging and
verified byte-identical to the secured intake file. The earlier assumption of
a separate "StrikeNova Staging" app was wrong: the single existing app **is**
the staging app. The old `backend/.env` dev credentials were never reused.

### 19.2 UDAPI100068 incident

The first consent attempt failed at Upstox's dialog with
`UDAPI100068 — Check your 'client_id' and 'redirect_uri'` even though the
deployed pair was correct — because the redirect-URI registration change had
not yet taken effect on Upstox's side at that moment. Later attempts passed
the dialog, confirming the registration had propagated. No client-side change
was ever needed.

### 19.3 Authorization URL verification

Fresh URL generated from the application (`GET /auth/login?broker=UPSTOX`,
307): `response_type=code`, staging client ID, exact registered redirect,
145-char HMAC-signed state. Documented constraint: the signed OAuth state is
in-memory with a **10-minute TTL** — consent must complete within that window
and before any service restart/redeploy.

### 19.4 Consent → callback → exchange → profile (all verified live)

The user completed Upstox authorization (2026-09-13T17:39:07Z, from deployed
app logs): `GET /auth/callback` fired, the single-use authorization code was
exchanged **server-side** (secret never left the backend, no token values in
logs), and the Upstox user profile was fetched successfully (broker user id
`3CCJPA`).

### 19.5 Identity provisioning FAILED — recorded defect, not fixed here

The callback's final provisioning step raised
`sqlalchemy.exc.IntegrityError: UniqueViolation ix_users_email`:
`get_or_create_user_from_upstox` (`backend/app/identity.py`, "Map the
authenticated Upstox identity to one durable StrikeNova user") matches users
only by `(broker_provider, broker_user_id)`; a first-time Upstox login INSERTs
a new user with the Upstox profile email, which collides with the
pre-existing platform account of the same email. The callback's catch-all
rolled back (the freshly exchanged Upstox token was discarded — nothing was
persisted) and redirected to `?login_error=account_setup_failed`.

**Owner decision required (not implemented in this session):** identity-merge
policy when a first-time broker login presents an email that already belongs
to a platform account — link identities, require re-verification, or reject.
Until decided, the staging OAuth chain stops at this step by design.

### 19.6 Session hygiene

No Render writes were needed this session (credential parity pre-verified);
no new deployment was triggered; the intake file was deleted after
verification and confirmed absent; the protected five env vars were never
modified; production Upstox app, Vercel production, Railway, production DB
and DNS untouched; no orders placed; no secrets printed, logged, or committed.
(Render's log query backend was intermittently unavailable — Loki 502 —
during the evidence window; the quoted log lines come from the app-log stream.)
