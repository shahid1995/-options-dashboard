# StrikeNova — Upstox Sandbox Broker Connection: STAGING Validation

Date: 2026-09-13
Scope: Upstox sandbox broker-connection path in staging
Baseline: staging stack fully verified (auth, OAuth, CRDB, WS connection layer,
automated smoke suite)

```text
Vercel staging  →  https://strikenova-frontend-staging.vercel.app
Render staging  →  https://strikenova-api-staging.onrender.com
CockroachDB     →  strikenova-staging / strikenova_staging
```

Companion documents: `STAGING_BROWSER_ACCEPTANCE.md`, `RENDER_STAGING_DEPLOYMENT.md`,
`STAGING_SMOKE_TEST.md`.

---

## 1. Official Upstox documentation references (checked 2026-09-13)

* **Sandbox** — `https://upstox.com/developer/api-documentation/sandbox/`
* **Building with Sandbox Mode** — `https://upstox.com/developer/api-documentation/build-using-sandbox/`
* **Announcement: Sandbox Mode for API Integration** — `https://upstox.com/developer/api-documentation/announcements/sandbox-mode-for-apis/`
* **API Overview** — `https://upstox.com/developer/api-documentation/api-overview`

Key statements from the current official pages (verbatim or near-verbatim):

* *"Only one sandbox app is permitted per user."*
* Sandbox access tokens are **generated in the developer portal** ("Generate"
  button on the sandbox app) and are *"valid for 30 days"*.
* *"Sandbox access tokens are exclusively for sandbox orders and cannot be
  used for live transactions."*
* Sandbox app *"redirect URL and postback URL fields are included to collect
  data and currently do not serve any functional purpose for the sandbox app"*
  (functional redirect enforcement is documented for **live** apps).
* *"If an API is not yet available in Sandbox, please switch to live mode for
  full functionality."*
* Sandbox-enabled APIs (full list on the sandbox page): **Place Order,
  Place Order V3, Place Multi Order, Modify Order, Modify Order V3,
  Cancel Order, Cancel Order V3**.

**Architectural consequence (drives everything below):** the Upstox sandbox is a
**portal-token order simulator, not an OAuth environment**. There is no sandbox
authorization dialog, no sandbox authorization code, and no sandbox token
exchange. StrikeNova's broker connection is a **BYOB OAuth flow**. The two
models do not intersect, so the OAuth/token-exchange legs of the StrikeNova
path **cannot be exercised against the sandbox by design**.

---

## 2. Sandbox capabilities (official)

| Capability | Sandbox status |
| --- | --- |
| App creation (developer portal, "New Sandbox App") | YES (1 per user) |
| Access token generation | YES (portal-generated, 30-day validity) |
| Place / modify / cancel order (v2 + v3, multi-order) | YES (sandbox-enabled) |
| Profile / user authentication APIs | NO — live mode only |
| Funds & margin | NO — live mode only |
| Positions / holdings / order book / trade book | NO — live mode only |
| Market data / option chain / historical data | NO — live mode only |
| Market WebSocket feed | NO — live mode only |
| OAuth authorization dialog + code exchange | NO — sandbox tokens bypass OAuth entirely |

---

## 3. StrikeNova broker flow (from current committed source)

```text
FRONTEND
  authenticated user connects broker app credentials (BYOB)
    → POST /auth/connect            {broker, api_key, api_secret, redirect_uri?}
        · stores Fernet-encrypted key/secret on BrokerConnection
          (status="pending", broker_account_id="pending")        [identity.py store_credentials]
    → user clicks "Connect with Upstox"
    → GET /auth/login?broker=UPSTOX
        · 401 unless an active platform session exists (Day-3 gate)
        · resolves user's own key/secret (ValueError → 400, no platform fallback)
        · state = token_store.create_oauth_state(session_id, broker)  [HMAC-signed]
        · 302 → adapter.get_authorization_url(state)
            = https://api.upstox.com/v2/login/authorization/dialog
              ?response_type=code&client_id=<user key>
              &redirect_uri=<UPSTOX_REDIRECT_URI>&state=<signed>

UPSTOX (LIVE app only)
  user consents → 302 → <redirect_uri>?code=...&state=...

BACKEND
  GET /auth/callback?code&state
    · consume_oauth_state(state) — single-use, HMAC-verified, carries
      session_id + broker (broker from state, never the query param)
    · re-resolves the BOUND session's user credentials
    · adapter.exchange_authorization_code(code)
      → POST /login/authorization/token {code, client_id, client_secret,
        redirect_uri, grant_type=authorization_code} → access_token
    · adapter.get_profile() → get_or_create_user_from_upstox()
    · get_or_create_connection(user, broker, broker_account_id)
      → pending row upgraded to status="connected" with real account id
    · token_store.set_token(access_token, connection_id, expires_at=+24h)
      → Fernet-encrypted into broker_tokens.broker_token_encrypted
      (session id hashed in DB — never stored plaintext)
    · create_session_record(...) + commit (rollback + token clear on failure)
    · 302 → FRONTEND/dashboard#session_id=... + HttpOnly Secure cookie

STATE
  BrokerConnection (user_id, broker, broker_account_id, status,
    api key/secret/analytics token — all Fernet-encrypted at rest)
  BrokerToken (session_id_hash, broker_token_encrypted, expires_at)
```

Token retrieval / consumption: `token_store.get_token(session_id)` decrypts on
demand; platform session tokens (`email:…`, `google:…`) are explicitly
identified and never usable as broker credentials (WS and broker paths return
401/403/BROKER_AUTH_REQUIRED instead).

## 4. Environment / configuration requirements (staging)

Render staging env var **names** (values never read): `ADDITIONAL_CORS_ORIGINS`,
`DATABASE_URL`, `GOOGLE_CLIENT_ID`, `TOKEN_ENCRYPTION_KEY`.

* **No `UPSTOX_*` vars and no `BACKEND_URL` are configured on staging** —
  consistent with BYOB design (user-level credentials live encrypted in the
  DB, not in service env).
* `UPSTOX_REDIRECT_URI` is optional (Phase 10.2B-6) and auto-derived only from
  `BACKEND_URL` or `RAILWAY_PUBLIC_DOMAIN`; with neither set on staging the
  derived value is currently **empty**. For a live broker connection on
  staging the owner must set `BACKEND_URL=https://strikenova-api-staging.onrender.com`
  (or an explicit `UPSTOX_REDIRECT_URI`).
* `TOKEN_ENCRYPTION_KEY` is already configured (Google-OAuth remediation) and
  is the same key that encrypts broker credentials/tokens. Not read, printed,
  or rotated in this audit.

## 5. OAuth redirect configuration (exact, from code)

* Route: **`GET /auth/callback`** (auth router mounted at `/auth`) →
  `https://strikenova-api-staging.onrender.com/auth/callback` is the exact
  staging redirect URI for a live app.
* Derivation: explicit `UPSTOX_REDIRECT_URI` > `BACKEND_URL` >
  `RAILWAY_PUBLIC_DOMAIN`, then `{base}/auth/callback` (config.py).
* A live Upstox Developer App must be registered with **exactly** that URI
  (Upstox enforces redirect-URI match on live apps; the user's per-connection
  `redirect_uri` field is honored by the adapter when provided).
* **Sandbox apps cannot serve this role**: their redirect URL field is
  documented as non-functional, and sandbox never issues authorization codes.

## 6. Token encryption / storage (verified)

* Encryption at rest: Fernet (AES-128-CBC + HMAC-SHA256), key derived from
  `TOKEN_ENCRYPTION_KEY` via PBKDF2-HMAC-SHA256 (480k iterations, fixed salt)
  — `app/crypto.py`. Empty key raises; tokens never logged/repr'd.
* Storage: `broker_connections.broker_api_key_encrypted/_secret_encrypted/
  _analytics_token_encrypted`; `broker_tokens.broker_token_encrypted` keyed by
  `hash_session_id` (session id itself never persisted).
* Retrieval decrypts server-side only; **no endpoint returns token material**
  (proven live below).

## 7. User isolation (verified live)

* Code: every broker query filters on `user_id` (+ broker, status); OAuth
  state binds session→user at initiation; credentials resolve only for the
  bound session's user.
* Live proof: automated two-user test (see §13, `test_b08_two_user_isolation`)
  — user B sees `has_analytics_token:false`, cannot delete A's token (404),
  and A's state is untouched.

## 8–12. Capability-by-capability outcome

| StrikeNova feature | Upstox API | Sandbox support | Testable in staging now |
| --- | --- | --- | --- |
| BYOB OAuth connect (`/auth/login`→dialog→callback) | authorization dialog + token exchange | NO (no sandbox OAuth) | NO — needs a LIVE Developer App (user action) |
| Profile / connection diagnostics | `GET /user/profile` | NO | Graceful path verified live (`BROKER_AUTH_REQUIRED`) |
| Funds / capital (`/paper/capital`) | `get-funds-and-margin` | NO | Broker leg NO; StrikeNova CRDB leg verified live |
| Positions | portfolio positions | NO | Graceful empty states verified (browser acceptance) |
| Orders — StrikeNova paper engine | n/a (internal simulation) | n/a | Already validated (paper flows, `MARKET CLOSED`) |
| Orders — broker placement/modify/cancel | v2/v3 order APIs | **YES** (sandbox) | NO StrikeNova surface — app has no order-API integration path to sandbox (see §11) |
| Market data / option chain / GEX capture | option-chain & market-quote APIs | NO | `MARKET DATA NOT SANDBOX-CAPABLE — NOT EXERCISED` |
| WebSocket streaming | Upstox market feed token | NO | UNAVAILABLE — requires live feed token (see §10) |

### §10 WebSocket (why streaming is not exercisable)

The app's chain WS (`/chains/ws/{symbol}`) upgrades any authenticated session
and then requires a **broker access token** (`token_store.get_token`) to open
the Upstox market feed; platform-only sessions close with 4401. A sandbox
token cannot provide this feed: sandbox tokens are orders-only and the market
feed is not sandbox-enabled. Recorded as
`MARKET DATA / WEBSOCKET STREAMING NOT SANDBOX-CAPABLE — NOT EXERCISED`.
(The WS connection layer itself — 101 + accept-key proof — is already
automated in `test_staging_websocket_smoke.py`.)

### §11 Order lifecycle (two different layers — kept separate)

* **StrikeNova paper trading** (internal engine, CRDB-backed): already
  validated in staging acceptance; unrelated to Upstox.
* **Upstox sandbox order APIs** (place/modify/cancel are sandbox-enabled):
  StrikeNova has **no code path** that places broker orders — the application
  design is paper-only, and `require_token`/WS paths explicitly refuse to use
  platform tokens as broker credentials. Exercising sandbox order APIs would
  mean building a new integration surface, which is out of scope for an audit
  (and was not authorized). Recorded as PENDING-BY-DESIGN, not a defect.

## 13. Live validation executed (staging API, synthetic identity only)

All checks below ran against the deployed Render staging service with a
runtime-generated synthetic account (2026-09-13):

| # | Check | Expected | Result |
| --- | --- | --- | --- |
| 1 | `GET /auth/analytics-token/status` (no connection) | `has_analytics_token:false` | PASS |
| 2 | `DELETE /auth/analytics-token` (none stored) | 404, no leakage | PASS |
| 3 | `GET /paper/broker/profile` (platform session) | `unavailable`, `profile:null`, `BROKER_AUTH_REQUIRED` | PASS |
| 4 | `GET /auth/login` unauthenticated | 401, no Upstox URL | PASS |
| 5 | `GET /auth/login` authenticated, no BYOB creds | 400 "No UPSTOX credentials found…", no redirect | PASS |
| 6 | `POST /auth/connect` unauthenticated | 401 | PASS |
| 7 | Analytics-token lifecycle (store→status→remove→status) | ok→true→removed→false; value never echoed | PASS |
| 8 | Two-user isolation (B vs A) | B sees nothing, cannot delete, A intact | PASS |
| 9 | Token-value echo paranoia (status/profile/me) | marker absent everywhere | PASS |

Automated as `backend/tests/staging_smoke/test_staging_broker_smoke.py`
(8 tests), opt-in via **`STAGING_BROKER_SMOKE=1`** in addition to
`STAGING_SMOKE=1`:

```bash
STAGING_SMOKE=1 STAGING_BROKER_SMOKE=1 \
  python -m pytest tests/staging_smoke/test_staging_broker_smoke.py -v
```

Live run: **8 passed**. The suite is deterministic, uses synthetic identities
and obviously-fake opaque token values (never printed, never sent to Upstox),
exercises only the app-sanctioned direct-token mechanism (no OAuth bypass, no
hidden platform credentials), and leaves each synthetic user's data-only
connection deactivated after cleanup.

## 14. Failures

None in the executable scope. Blocked items (all external prerequisites, not
application defects):

1. **OAuth legs** — require a LIVE Upstox Developer App owned by the user +
   `BACKEND_URL` set on Render staging + per-user credentials stored via
   `POST /auth/connect`. Sandbox cannot substitute (§1, §5).
2. **Sandbox order APIs** — sandbox-capable upstream, but StrikeNova has no
   broker-order integration surface by design (paper-only).
3. **Market data / WS streaming** — not sandbox-capable upstream.

## 15. Unsupported sandbox capabilities (summary)

`PROFILE NOT SANDBOX-CAPABLE` · `FUNDS/CAPITAL NOT SANDBOX-CAPABLE` ·
`POSITIONS NOT SANDBOX-CAPABLE` · `ORDER BOOK/STATUS NOT SANDBOX-CAPABLE` ·
`MARKET DATA NOT SANDBOX-CAPABLE — NOT EXERCISED` ·
`OPTION CHAIN NOT SANDBOX-CAPABLE` · `WEBSOCKET FEED NOT SANDBOX-CAPABLE` ·
`OAUTH NOT SANDBOX-CAPABLE (portal-token model)`.

## 16. Production-safety verification

```text
Production Upstox account/app used:  NO (no Upstox console accessed at all)
Production broker connected:         NO
Real order submitted:                NO
Vercel production touched:           NO
Railway touched:                     NO
Production DB touched:               NO
Production Google OAuth touched:     NO
Production DNS changed:              NO
TOKEN_ENCRYPTION_KEY rotated:        NO (never read or printed)
Secrets committed:                   NO (no tokens/keys/DSNs anywhere)
```

---

## Bottom line

The broker-connection path's **security architecture is verified live** (auth
gates, state binding, encryption-at-rest design, isolation, graceful
brokerless states, zero token leakage) and is now **regression-protected** by
the opt-in broker smoke suite. The **upstream-integration legs** (OAuth token
exchange, profile/funds/positions, market data, WS streaming, broker orders)
cannot be validated through the Upstox sandbox because the sandbox is a
portal-token order simulator with no OAuth and no market-data APIs; they
require either a live Upstox Developer app (OAuth legs) or are out of the
application's scope by design (broker orders).
