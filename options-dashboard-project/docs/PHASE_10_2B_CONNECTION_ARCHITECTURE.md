# Phase 10.2B — Connection Architecture Specification

_Created: 2026-08-28_
_Last updated: 2026-08-28_
_Status: SPECIFICATION — Pending Principal Architect approval_
_Based on: Phase 10.2B Architectural Audit, PR #22 (10.2A) merge, Upstox & FYERS API documentation, Spec Audit Report, Broker Credential Architecture Audit_

---

## Architecture Decisions — Frozen

The following decisions are **frozen** and MUST NOT be revisited during implementation. They are based on verified broker documentation, SEBI regulatory requirements, and the Phase 10.2B audit process.

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| **AD-1** | **StrikeNova account authentication is completely independent of broker authentication.** The StrikeNova `User.id` (UUID) is the canonical platform identity. Broker connections are relationships to that identity, not the identity itself. | Clean separation of concerns; platform auth (Google/Email OTP) and broker auth (OAuth) serve different purposes. | §3.1 |
| **AD-2** | **StrikeNova uses BYOB (Bring Your Own Broker): every user supplies their own broker Developer App/credentials.** No platform-level broker API keys are shared across users. | Upstox enforces "one access token per API key" — a shared key means User B's login invalidates User A's token. SEBI requires per-user static IPs. | Upstox V2 Announcement; FYERS SEBI compliance (March 2026) |
| **AD-3** | **No shared Upstox API credentials across StrikeNova users.** Each user's `broker_connections` row stores their own encrypted API Key + API Secret. | One-token-per-key constraint makes shared credentials impossible for multi-user. | Upstox V2 Announcement |
| **AD-4** | **`broker_connections` belongs to a StrikeNova User.** The `user_id` FK is non-nullable. A connection cannot exist without a platform identity. | Broker connections are platform-scoped relationships, not standalone entities. | §3.1 |
| **AD-5** | **Multiple broker connections are supported per user.** A user may have Upstox + FYERS, or multiple Upstox accounts. | Users may trade through multiple brokers or have personal + family accounts. | §3.3 |
| **AD-6** | **Provider-specific credential/token models are allowed.** Each adapter encapsulates its own OAuth flow, auth header format, and token lifecycle. The platform never contains `if broker == "UPSTOX"` logic. | Broker APIs are fundamentally different; forcing a common model creates leaks. | §7 |
| **AD-7** | **Upstox Analytics Token and OAuth `extended_token` MUST be treated as different credential types.** The Analytics Token is generated from the Developer Apps page (1-year, read-only). The OAuth `extended_token` is returned in the token exchange response — its lifetime and API permissions are UNVERIFIED. | Official docs describe them as separate mechanisms. The Analytics Token docs say "Generated directly from the Developer Apps page. No OAuth flow required." The OAuth `extended_token` docs only say "prolonged usage" without specifying lifetime. | Spec Audit Report §C1 |
| **AD-8** | **Do NOT design any fallback based on the OAuth `extended_token` until its capabilities are empirically verified.** The 1-year lifetime documented for the Analytics Token does NOT apply to the OAuth `extended_token`. | The spec audit found the original spec conflated these two credentials. Implementation must not build on unverified assumptions. | Spec Audit Report §C1-C2 |
| **AD-9** | **FYERS REST and WebSocket authentication MUST be represented independently.** REST uses `Authorization: <app_id>:<access_token>`. WebSocket uses `Authorization: Bearer <access_token>`. These are different formats for the same token. | FYERS uses non-Bearer for REST and Bearer for WebSocket. Forcing a single auth model would break one transport. | FYERS auth.md; community posts (Dec 2024) |
| **AD-10** | **Google and Email OTP authentication belong to StrikeNova identity, not broker connections.** Platform auth (Google OAuth, Email OTP) is orthogonal to broker auth (Upstox/FYERS OAuth). A user authenticates to StrikeNova first, then connects broker accounts separately. | Platform identity must survive broker disconnection. A user should be able to remove all broker connections and still have a StrikeNova account. | §3.1 |
| **AD-11** | **FYERS refresh token flow is best-effort, not a primary session persistence strategy.** Multiple community reports indicate intermittent failures. The refresh token may be discontinued. Daily re-login is the reliable path. | TradesViz discontinued Fyers auto-sync due to refresh failures. Official docs caveat: "may be discontinued." SEBI requires daily 2FA. | Spec Audit Report §C4; FYERS SEBI compliance |
| **AD-12** | **SEBI April 2026 algo regulations apply.** Each user needs their own static IP for order placement. Shared IPs are explicitly prohibited. Third-party platforms must be empanelled. | Regulatory compliance is mandatory, not optional. | FYERS community (March 2026, official response) |

---

## 1. Context

### 1.1 What Exists Today

After the Phase 10.2A merge (PR #22), the identity and session infrastructure is:

| Component | State | Notes |
|-----------|-------|-------|
| `User` model | ✅ Durable | `users.id` (UUID) is the canonical identity |
| `UserSession` model | ✅ Durable | Links `session_hash` → `user_id`, owns `expires_at`/`revoked_at` |
| `token_store` | ⚠️ In-memory only | `_sessions: dict` — all tokens lost on restart |
| `AuthenticatedUser` | ✅ Canonical | `deps.py` resolves session → `(user_id, access_token)` |
| `BrokerAdapter` protocol | ✅ Established | `exchange_authorization_code()`, `get_profile()`, `get_authorization_url()` |
| `BrokerGateway` | ✅ Established | Single entry point, supports `create()`, `for_connection()`, `default()` |
| `BrokerRegistry` | ✅ Established | Maps `BrokerId` → adapter factory |
| `BrokerConnectionContext` | ✅ Defined | `user_id`, `broker`, `account_id` — but unused by any router |
| Upstox adapter | ✅ Wired | `exchange_authorization_code()` returns `str` (access_token only) |
| FYERS adapter | ❌ Does not exist | `BrokerId.FYERS` enum declared, no adapter implementation |
| `broker_connections` table | ❌ Does not exist | No DB model for persistent broker connection records |
| Token encryption | ❌ Does not exist | No Fernet/encryption layer |
| Token DB persistence | ❌ Does not exist | `UserSession` has no `broker_token_encrypted` column |
| **Platform API key** | ⚠️ **Single shared key** | `settings.UPSTOX_API_KEY` — **BROKEN for multi-user** (AD-2) |

### 1.2 What Phase 10.2B Must Deliver

1. **BYOB credential management** — each user stores their own broker API Key + Secret (encrypted)
2. **Persistent broker connection records** — a `broker_connections` table with per-user credentials
3. **Token persistence with encryption** — broker tokens stored encrypted in PostgreSQL
4. **Provider-specific connection mechanisms** — each broker's OAuth flow maps to a shared connection lifecycle
5. **StrikeNova account independence** — broker auth is separate from platform auth (AD-1, AD-10)
6. **Restart recovery** — sessions survive server restarts without re-login
7. **Multi-broker readiness** — architecture supports FYERS alongside Upstox from day one
8. **SEBI compliance** — static IP per user for order placement (AD-12)

### 1.3 Design Principles

- **StrikeNova account is the identity layer.** A user authenticates to StrikeNova (Google/Email OTP), then connects broker accounts. Broker connections are relationships to the platform identity, not the identity itself. (AD-1, AD-10)
- **BYOB: every user supplies their own broker credentials.** No shared API keys across users. (AD-2, AD-3)
- **Provider-specific auth flows are adapter concerns.** The platform never contains `if broker == "UPSTOX"` logic. (AD-6)
- **Tokens and credentials are encrypted at rest.** No plaintext broker tokens or API keys in PostgreSQL.
- **In-memory cache is an optimization, not the source of truth.** PostgreSQL is authoritative.
- **Connection lifecycle is provider-aware.** Upstox tokens expire at 3:30 AM IST daily; FYERS tokens expire at end of trading day.

---

## 2. Broker Authentication Models

### 2.1 Upstox — OAuth + Analytics Token

**OAuth flow (single-step):**
```
1. GET  /auth/login → Redirect to Upstox OAuth dialog (client_id = USER's API key)
2. User logs in → Upstox redirects to /auth/callback?code=...
3. POST /v2/login/authorization/token (code exchange, using USER's API key + secret)
   → Returns: access_token + extended_token + profile (all in one response)
4. Profile → create/get User in DB
5. access_token → token_store (in-memory) + broker_tokens row (DB, encrypted)
```

**Token characteristics:**
| Property | Value | Source |
|----------|-------|--------|
| `access_token` lifetime | Expires at **3:30 AM IST daily** (fixed wall-clock, not TTL) | Official Upstox docs |
| Refresh token support | **None** — Upstox does not support `grant_type=refresh_token` | No refresh endpoint in docs |
| Token format | Opaque string, `Bearer <token>` auth header | Official |
| Re-login required | **Daily** — must re-authorize via OAuth each trading day | Official |
| One token per API key | **Yes** — "Only one access token will be allowed at a time per API key" | Upstox V2 Announcement |

**OAuth `extended_token` (UNVERIFIED — AD-7, AD-8):**
| Property | Value | Source |
|----------|-------|--------|
| Lifetime | **UNVERIFIED** — docs say "prolonged usage" but do not specify duration | Official Get Token docs |
| API permissions | **UNVERIFIED** — "primarily for read-only access to various API endpoints" | Official Get Token docs |
| Relationship to Analytics Token | **DIFFERENT CREDENTIAL** — Analytics Token is generated from Developer Apps page, not via OAuth | Official Analytics Token docs |

**⚠️ DO NOT build fallback logic on OAuth `extended_token` until its lifetime and API permissions are empirically verified.** (AD-8)

**Upstox Analytics Token (separate credential — AD-7):**
| Property | Value | Source |
|----------|-------|--------|
| Lifetime | **1 year** from generation | Official Analytics Token docs |
| Scope | **Read-only** (GET APIs only) — no order placement | Official |
| Who generates it | **User**, from their own Developer Apps page (Analytics tab) | Official |
| Per-account limit | One active Analytics Token per account | Official |
| Static IP required | Only for account-specific APIs (Portfolio, Orders, P&L) | Official (June 2026 update) |
| **WebSocket** | **Supported** — no static IP needed | Official |

**Analytics Token permitted APIs (no static IP):**
- Option Chain, Historical Data, Market Quote, Market Information
- Fundamentals, News, IPO, Charges, Margins
- **WebSocket** (real-time market data)

**Analytics Token permitted APIs (static IP required):**
- User (profile, funds, margin), Portfolio (positions, holdings)
- Orders (order book, history, trades), Trade P&L, Payments

**Session expiry handling (restored in PR #22):**
```python
# gex.py — trigger_capture
except BrokerError as e:
    if e.code in BrokerErrorCode.SESSION_CODES:  # AUTH_REQUIRED, TOKEN_EXPIRED
        token_store.clear_token(session_id)
        raise HTTPException(status_code=401, detail="Upstox session expired.") from e
    raise HTTPException(status_code=502, detail=f"Upstox API error: {e.message}") from e
```

### 2.2 FYERS — OAuth (Two-Step) + Data-Only Mode

**OAuth flow (two-step):**
```
1. GET  /api/v3/generate-authcode
   ?client_id=<USER's APP_ID>&redirect_uri=<REDIRECT_URI>&response_type=code&state=<random>
   → User logs in → redirected to redirect_uri?auth_code=<CODE>&state=<...>

2. POST /api/v3/validate-authcode  (or /api/v3/token — verify which is current)
   Body: { "grant_type": "authorization_code", "appIdHash": "<sha256(app_id:secret_id)>", "code": "<auth_code>" }
   → Returns: { "s": "ok", "access_token": "...", "refresh_token": "..." }
```

**⚠️ FYERS may have migrated from `/validate-authcode` to `/token`. Verify against live docs before implementing.** (Spec Audit §C3)

**Token characteristics:**
| Property | Value | Source |
|----------|-------|--------|
| `access_token` lifetime | Expires **end of trading day** (daily) | Official FYERS auth.md |
| `refresh_token` lifetime | **15 days** (may be discontinued) | Official FYERS support |
| Refresh token requires | **PIN** (`"pin": "<user_pin>"`) | Official FYERS auth.md |
| Refresh token reliability | **Questionable** — intermittent failures reported | Community reports; TradesViz discontinued sync |
| App types | `-100` = legacy (data-only after April 2026), `-200` = new trading-capable | FYERS SEBI compliance |
| Static IP | Required for order placement; **NOT required for market data** | Official FYERS community (March 2026) |
| Shared IPs | **NOT allowed** — "Each IP address must be unique across all users" | Official FYERS community (March 2026) |
| One app per user | **Yes** — "Only one app is allowed per user for trading" | Official FYERS community (March 2026) |

**FYERS authentication headers (AD-9):**
| Transport | Format | Example |
|-----------|--------|---------|
| REST API | `Authorization: <app_id>:<access_token>` | `Authorization: SPXXXXE7-100:eyJ0eXAi...` |
| WebSocket | `Authorization: Bearer <access_token>` | `Authorization: Bearer eyJ0eXAi...` |

These are **different formats for the same token**. The FYERS adapter must handle both.

**FYERS refresh token (AD-11):**
```
POST /api/v3/validate-refresh-token
{
    "grant_type": "refresh_token",
    "appIdHash": "<sha256(app_id:secret_id)>",
    "refresh_token": "<refresh_token>",
    "pin": "<user_pin>"
}
→ Returns: new access_token only (no new refresh_token)
```

**⚠️ Treat refresh as best-effort. Daily re-login is the reliable path.** (AD-11)

### 2.3 Provider Comparison Matrix

| Dimension | Upstox | FYERS | Future Broker |
|-----------|--------|-------|---------------|
| OAuth steps | 1 (code → token) | 2 (authcode → validate) | Provider-specific |
| REST auth header | `Bearer <token>` | `<app_id>:<token>` | Provider-specific |
| WebSocket auth header | `Bearer <token>` | `Bearer <token>` | Provider-specific |
| Access token lifetime | Until 3:30 AM IST | End of trading day | Provider-specific |
| Refresh token | No | Yes (15 days, unreliable, requires PIN) | Provider-specific |
| Long-lived read-only token | Analytics Token (1 year, user-generated) | No equivalent | Provider-specific |
| OAuth `extended_token` | **UNVERIFIED** (AD-8) | N/A | Provider-specific |
| `appIdHash` required | No | Yes (SHA256 of app_id:secret_id) | Provider-specific |
| Non-trading app mode | No (all-or-nothing) | Yes (app type `-100` = data-only) | Provider-specific |
| Static IP for orders | Required (SEBI) | Required (SEBI) | Provider-specific |
| Static IP for market data | Not required | Not required | Provider-specific |
| One token per API key | **Yes** (Upstox V2) | Unclear (one app per user) | Provider-specific |
| Profile endpoint | GET `/v2/user/profile` | GET `/v3/profile` | Provider-specific |

---

## 3. StrikeNova Account Model

### 3.1 Identity vs Connection Separation (AD-1, AD-10)

The architecture enforces a strict separation between **platform identity** and **broker connection**:

```
StrikeNova User (platform identity — independent of any broker)
  ├── id: UUID (canonical, immutable)
  ├── email, display_name, status
  ├── identity_source: "google" | "email_otp" | "upstox" (legacy)
  └── Platform auth: Google OAuth / Email OTP (NOT broker OAuth)

Broker Connection (platform ↔ broker relationship — AD-4)
  ├── id: UUID
  ├── user_id: FK → users.id (NOT NULL — AD-4)
  ├── broker: enum (UPSTOX, FYERS, ...)
  ├── broker_account_id: broker's user_id/UCC/client_id
  ├── display_label: user-facing name ("My Upstox Account")
  ├── is_default: bool (primary connection for this user+broker)
  ├── status: connected | expired | suspended | disconnected
  ├── capability_mode: trading | data_only
  ├── Per-user broker credentials (encrypted — AD-2, AD-3):
  │   ├── broker_api_key_encrypted: Fernet-encrypted API Key / App ID
  │   ├── broker_api_secret_encrypted: Fernet-encrypted API Secret / Secret ID
  │   ├── broker_analytics_token_encrypted: nullable (Upstox Analytics Token)
  │   ├── broker_redirect_uri: user's registered redirect URI
  │   └── broker_static_ip: nullable (for order placement — AD-12)
  ├── provider_metadata_json: provider-specific non-secret metadata
  └── timestamps: created_at, updated_at, connected_at, disconnected_at

Broker Token (session-scoped credential)
  ├── connection_id: FK → broker_connections.id
  ├── session_hash: links to user_sessions.session_hash
  ├── broker_token_encrypted: encrypted access_token
  ├── broker_token_expires_at: datetime
  ├── broker_refresh_token_encrypted: nullable (FYERS only)
  ├── broker_refresh_token_expires_at: nullable
  └── created_at: datetime
```

### 3.2 Platform Auth vs Broker Auth (AD-10)

| Layer | Purpose | Providers | Stored Where |
|-------|---------|-----------|-------------|
| **Platform identity** | "Who are you on StrikeNova?" | Google OAuth, Email OTP | `users` table |
| **Broker connection** | "Which broker account do you trade through?" | Upstox OAuth, FYERS OAuth | `broker_connections` table |
| **Broker token** | "What's your current broker session?" | Access token, refresh token | `broker_tokens` table |

A user authenticates to StrikeNova first (platform identity), then optionally connects broker accounts. Removing all broker connections does NOT delete the StrikeNova account.

### 3.3 Legacy `User.broker_provider` / `User.broker_user_id`

The current `users` table has `broker_provider` and `broker_user_id` columns with a unique constraint `uq_users_broker_identity`. This was the Phase 10.1 identity-foundation approach: one user row per broker identity.

**Problem:** This ties the StrikeNova user to a single broker identity. If a user has both an Upstox account AND a FYERS account, they'd need two `User` rows — violating the single-identity model.

**Phase 10.2B decision:** The `broker_connections` table replaces this pattern. Legacy columns remain for backward compatibility but are **deprecated**:
- `User.broker_provider` and `User.broker_user_id` remain nullable
- `get_or_create_user_from_upstox()` continues to populate them during login
- New connection records go to `broker_connections`
- A future Phase 10.2D migration can audit and remove the legacy columns

### 3.4 Multiple Connections per User (AD-5)

A single StrikeNova user may have:

| Scenario | Connections | Notes |
|----------|-------------|-------|
| Upstox only | 1 Upstox connection | Current default |
| FYERS data only | 1 FYERS connection (data_only) | Analytics + market data |
| Upstox + FYERS | 2 connections | Upstox for trading, FYERS for additional data |
| Multiple Upstox accounts | 2+ Upstox connections | Different UCCs (e.g., personal + family) |

**Uniqueness constraint:** `(user_id, broker, broker_account_id)` — one connection per user per broker account.

**Default connection:** `(user_id, broker, is_default=True)` — when only one connection exists per broker, it's automatically the default.

---

## 4. Connection Lifecycle

### 4.1 Connection States

```
                    ┌──────────────┐
                    │ DISCONNECTED │ ← Initial state / user manually disconnects
                    └──────┬───────┘
                           │ OAuth callback succeeds (with USER's credentials)
                           ▼
                    ┌──────────────┐
            ┌──────│   CONNECTED  │──────┐
            │      └──────┬───────┘      │
            │             │              │
            │  access_token expired     User revokes
            │             │              │
            │             ▼              ▼
            │      ┌──────────────┐  ┌──────────────┐
            │      │   EXPIRED    │  │ DISCONNECTED │
            │      └──────┬───────┘  └──────────────┘
            │             │
            │  refresh token available (FYERS, best-effort — AD-11)
            │             │
            │             ▼
            │      ┌──────────────┐
            └──────│  REFRESHED   │
                   └──────────────┘
```

### 4.2 Connection Lifecycle — Upstox

```
1. CONNECT: User provides their Upstox API Key + Secret
   → Credentials encrypted and stored in broker_connections
   → User clicks "Connect Upstox" → /auth/login → OAuth (using USER's API key)
   → /auth/callback → exchange_authorization_code(code) → access_token + profile
   → create broker_connection row (UPSTOX, status=CONNECTED)
   → create broker_token row (encrypted access_token, expires_at=3:30 AM IST next day)
   → create/update UserSession row

2. DAILY EXPIRY: access_token expires at 3:30 AM IST
   → broker_token_expires_at < now() → token is stale
   → Broker calls fail with TOKEN_EXPIRED
   → gex.py clears token, returns 401
   → User must re-login (no refresh token available — AD-8: do NOT use extended_token)

3. ANALYTICS TOKEN (optional, user-provided):
   → User generates Analytics Token from their Upstox Developer Apps page
   → Stores encrypted in broker_connections.broker_analytics_token_encrypted
   → Used for read-only operations (GEX, IV, Option Chain, WebSocket) — 1-year validity
   → Does NOT help with trading operations

4. DISCONNECT: User clicks "Disconnect"
   → set broker_connection.status = DISCONNECTED
   → revoke all UserSession rows for this connection
   → clear all token_store entries for this connection
   → set broker_token rows to NULL
```

### 4.3 Connection Lifecycle — FYERS

```
1. CONNECT: User provides their FYERS App ID + Secret (+ optional PIN)
   → Credentials encrypted and stored in broker_connections
   → User clicks "Connect FYERS" → /auth/fyers/login → OAuth step 1 → OAuth step 2
   → generate authcode → user logs in → validate authcode (with appIdHash)
   → access_token + refresh_token
   → create broker_connection row (FYERS, capability_mode=data_only)
   → create broker_token row (encrypted access_token + refresh_token, expires_at=end_of_trading_day)

2. DAILY EXPIRY: access_token expires end of trading day
   → broker_token_expires_at < now()
   → If refresh_token available (best-effort — AD-11): POST /api/v3/validate-refresh-token
   → Update broker_token row with new access_token
   → If refresh fails or refresh_token expired (15 days): user must re-login

3. DATA-ONLY MODE (FYERS `-100` apps post-April 2026):
   → No order placement — read-only (quotes, historical data, positions, holdings)
   → No static IP required for market data
   → Perfect for GEX analytics, IV research, portfolio tracking

4. DISCONNECT: Same pattern as Upstox
```

### 4.4 Token Lifecycle Diagram (Unified)

```
                        ┌─────────────────────────────┐
                        │      OAuth Callback           │
                        │  (using USER's credentials)   │
                        └──────────┬──────────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
                    ▼              ▼              ▼
             access_token   Analytics Token  refresh_token
             (Upstox/FYERS) (Upstox only,    (FYERS only,
                             user-generated,  best-effort —
                             1-year)          AD-11)
                    │              │              │
                    ▼              ▼              ▼
            ┌───────────────────────────────────────────┐
            │     broker_tokens (DB, encrypted)         │
            │  ┌─────────────────────────────────────┐  │
            │  │ broker_token_encrypted              │  │
            │  │ broker_token_expires_at             │  │
            │  │ broker_refresh_token_encrypted      │  │
            │  │ broker_refresh_token_expires_at     │  │
            │  └─────────────────────────────────────┘  │
            └──────────────────┬────────────────────────┘
                               │
                    ┌──────────┼──────────┐
                    ▼          ▼          ▼
              In-memory     DB fallback  Cleanup
              cache hit     (cache miss) (background)
```

---

## 5. Schema Design

### 5.1 New Table: `broker_connections`

```sql
CREATE TABLE broker_connections (
    id              TEXT PRIMARY KEY,           -- UUID
    user_id         TEXT NOT NULL REFERENCES users(id),
    broker          TEXT NOT NULL,              -- 'UPSTOX', 'FYERS', etc.
    broker_account_id TEXT NOT NULL,            -- broker's user_id/UCC/client_id
    display_label   TEXT,                       -- user-facing name
    is_default      BOOLEAN DEFAULT TRUE,       -- primary connection for this user+broker
    status          TEXT DEFAULT 'connected',   -- connected | expired | suspended | disconnected
    capability_mode TEXT DEFAULT 'trading',     -- trading | data_only

    -- Per-user broker credentials (encrypted — AD-2, AD-3)
    broker_api_key_encrypted       TEXT,        -- Fernet-encrypted API Key / App ID
    broker_api_secret_encrypted    TEXT,        -- Fernet-encrypted API Secret / Secret ID
    broker_analytics_token_encrypted TEXT,      -- Fernet-encrypted Analytics Token (Upstox only)
    broker_redirect_uri            TEXT,        -- user's registered redirect URI
    broker_static_ip               TEXT,        -- user's static IP (for order placement — AD-12)

    -- Provider-specific metadata (non-secret)
    app_type        TEXT,                       -- e.g. '100' or '200' for FYERS
    provider_metadata_json TEXT DEFAULT '{}',

    created_at      TIMESTAMP NOT NULL,
    updated_at      TIMESTAMP NOT NULL,
    connected_at    TIMESTAMP NOT NULL,         -- last successful OAuth completion
    disconnected_at TIMESTAMP                    -- NULL while active

    UNIQUE (user_id, broker, broker_account_id)
);
```

### 5.2 New Table: `broker_tokens`

```sql
CREATE TABLE broker_tokens (
    id              INTEGER PRIMARY KEY,
    connection_id   TEXT NOT NULL REFERENCES broker_connections(id) ON DELETE CASCADE,
    session_hash    TEXT NOT NULL,               -- links to user_sessions.session_hash
    broker_token_encrypted       TEXT,           -- Fernet-encrypted access_token
    broker_token_expires_at      TIMESTAMP,      -- provider-specific expiry
    broker_refresh_token_encrypted  TEXT,         -- Fernet-encrypted refresh_token (FYERS only)
    broker_refresh_token_expires_at TIMESTAMP,    -- 15 days for FYERS
    created_at      TIMESTAMP NOT NULL

    UNIQUE (connection_id, session_hash)
);
```

### 5.3 Modified Table: `user_sessions`

Add nullable foreign key to `broker_connections`:

```sql
ALTER TABLE user_sessions ADD COLUMN broker_connection_id TEXT
    REFERENCES broker_connections(id);
```

### 5.4 Why Two Tables

- `broker_connections` = persistent relationship + per-user credentials (I have an Upstox account with my own API key)
- `broker_tokens` = session-scoped credential (this browser session has an access token)

Separation rationale:
- A connection persists across sessions; tokens are session-scoped
- Multiple sessions can share one connection (same Upstox account, different browsers)
- Token rotation updates the token row, not the connection row
- Per-user API keys are stored on the connection, not the token

### 5.5 Alembic Migration Plan

```python
def upgrade():
    # 1. broker_connections (with per-user credential columns)
    op.create_table(
        'broker_connections',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('broker', sa.String(32), nullable=False),
        sa.Column('broker_account_id', sa.String(128), nullable=False),
        sa.Column('display_label', sa.String(160), nullable=True),
        sa.Column('is_default', sa.Boolean, default=True),
        sa.Column('status', sa.String(20), default='connected'),
        sa.Column('capability_mode', sa.String(20), default='trading'),
        sa.Column('broker_api_key_encrypted', sa.Text, nullable=True),
        sa.Column('broker_api_secret_encrypted', sa.Text, nullable=True),
        sa.Column('broker_analytics_token_encrypted', sa.Text, nullable=True),
        sa.Column('broker_redirect_uri', sa.Text, nullable=True),
        sa.Column('broker_static_ip', sa.String(45), nullable=True),
        sa.Column('app_type', sa.String(32), nullable=True),
        sa.Column('provider_metadata_json', sa.Text, default='{}'),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=False),
        sa.Column('connected_at', sa.DateTime, nullable=False),
        sa.Column('disconnected_at', sa.DateTime, nullable=True),
        sa.UniqueConstraint('user_id', 'broker', 'broker_account_id', name='uq_broker_connection'),
    )
    op.create_index('ix_broker_connections_user_id', 'broker_connections', ['user_id'])
    op.create_index('ix_broker_connections_broker', 'broker_connections', ['broker'])

    # 2. broker_tokens
    op.create_table(
        'broker_tokens',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('connection_id', sa.String(36), sa.ForeignKey('broker_connections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('session_hash', sa.String(64), nullable=False),
        sa.Column('broker_token_encrypted', sa.Text, nullable=True),
        sa.Column('broker_token_expires_at', sa.DateTime, nullable=True),
        sa.Column('broker_refresh_token_encrypted', sa.Text, nullable=True),
        sa.Column('broker_refresh_token_expires_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.UniqueConstraint('connection_id', 'session_hash', name='uq_broker_token_per_session'),
    )
    op.create_index('ix_broker_tokens_connection_id', 'broker_tokens', ['connection_id'])
    op.create_index('ix_broker_tokens_session_hash', 'broker_tokens', ['session_hash'])

    # 3. Link user_sessions to broker_connections
    op.add_column('user_sessions', sa.Column('broker_connection_id', sa.String(36), nullable=True))
    op.create_foreign_key('fk_user_sessions_connection', 'user_sessions', 'broker_connections', ['broker_connection_id'], ['id'])

def downgrade():
    op.drop_table('broker_tokens')
    op.drop_table('broker_connections')
    op.drop_column('user_sessions', 'broker_connection_id')
```

---

## 6. Token Persistence & Encryption

### 6.1 Encryption Architecture

```
Environment variables:
  TOKEN_ENCRYPTION_KEY   → new, master key for encrypting ALL broker credentials
  TOKEN_ENCRYPTION_SALT  → new, per-environment random salt
  UPSTOX_REDIRECT_URI    → platform's redirect URI (NOT a secret)
  FYERS_REDIRECT_URI     → platform's FYERS redirect URI (NOT a secret)

Key derivation:
  Fernet key = base64url(PBKDF2-HMAC-SHA256(
      password = TOKEN_ENCRYPTION_KEY,
      salt = TOKEN_ENCRYPTION_SALT,
      iterations = 480,000
  ))
```

**What gets encrypted:**
| Field | Stored In | Content |
|-------|-----------|---------|
| `broker_api_key_encrypted` | `broker_connections` | User's Upstox API Key or FYERS App ID |
| `broker_api_secret_encrypted` | `broker_connections` | User's Upstox API Secret or FYERS Secret ID |
| `broker_analytics_token_encrypted` | `broker_connections` | User's Upstox Analytics Token (if provided) |
| `broker_token_encrypted` | `broker_tokens` | User's current OAuth access_token |
| `broker_refresh_token_encrypted` | `broker_tokens` | User's FYERS refresh_token (if available) |

**What does NOT get encrypted (platform-level, not secrets):**
- `UPSTOX_REDIRECT_URI` — platform's redirect URI
- `FYERS_REDIRECT_URI` — platform's FYERS redirect URI
- `broker_static_ip` — user's static IP (not a secret, but sensitive)

### 6.2 Token Store — Dual-Layer Architecture

```
┌─────────────────────────────────────────────────┐
│                token_store.py                    │
│                                                  │
│  get_token(session_id, connection_id=None)       │
│    ├── Fast path: _sessions[session_id] (memory) │
│    ├── Slow path: broker_tokens table (DB)       │
│    └── Decrypt + populate cache                  │
│                                                  │
│  set_token(session_id, token, connection_id,     │
│            expires_at, ...)                       │
│    ├── Encrypt token                             │
│    ├── Write to broker_tokens table (DB)         │
│    └── Write to _sessions[session_id] (memory)   │
│                                                  │
│  clear_token(session_id)                         │
│    ├── Remove from _sessions (memory)            │
│    └── NULL broker_token_encrypted (DB)          │
│                                                  │
│  rehydrate_cache()                               │
│    ├── SELECT all active broker_tokens           │
│    ├── Decrypt + populate _sessions              │
│    └── Skip expired/revoked                      │
│                                                  │
│  resolve_user_credentials(user_id, broker, db)   │
│    ├── Query broker_connections for user+broker  │
│    ├── Decrypt API Key + Secret                  │
│    └── Return credentials for adapter creation   │
└─────────────────────────────────────────────────┘
```

### 6.3 Restart Recovery

```python
# In main.py lifespan handler:
async def lifespan(app: FastAPI):
    init_db()                    # Alembic migrations
    token_store.rehydrate_cache() # Load tokens from DB into memory
    # ... rest of startup
```

### 6.4 Token Expiry Handling Per Provider

```python
def get_token(session_id: str | None) -> str | None:
    """Return broker token for session, with provider-aware expiry logic."""
    token = _get_from_cache_or_db(session_id)
    if token is None:
        return None

    # Check if access token is expired
    expires_at = _get_token_expiry(session_id)
    if expires_at and expires_at < utcnow():
        # Access token expired
        # AD-8: Do NOT fall back to OAuth extended_token (unverified)
        # AD-11: FYERS refresh is best-effort, not primary
        return None

    return token
```

---

## 7. Adapter Protocol Extensions

### 7.1 Extended `BrokerAdapter` Protocol

The current `BrokerAdapter` protocol is sufficient for Phase 10.2B. Provider-specific auth flow differences are encapsulated within each adapter implementation. (AD-6)

**Key protocol methods (unchanged):**
- `get_authorization_url(state: str) -> str` — build OAuth URL
- `exchange_authorization_code(code: str) -> str` — exchange code for access_token
- `get_profile() -> dict` — fetch broker profile
- `disconnect()` — release adapter's token reference

### 7.2 Upstox Adapter — Per-User Credentials

The adapter must accept per-user credentials instead of platform-level settings:

```python
class UpstoxAdapter:
    def __init__(self, access_token=None, *, api_key=None, api_secret=None, ...):
        self._access_token = access_token
        self._api_key = api_key           # User's API Key (from broker_connections)
        self._api_secret = api_secret     # User's API Secret (from broker_connections)

    def get_authorization_url(self, state: str) -> str:
        params = urlencode({
            "client_id": self._api_key,    # ← USER's API key, not platform
            "redirect_uri": self._redirect_uri,
            "state": state,
        })
        return f"{BASE_URL}/login/authorization/dialog?{params}"

    async def exchange_authorization_code(self, code: str) -> str:
        data = await _request("POST", "/login/authorization/token", data={
            "code": code,
            "client_id": self._api_key,      # ← USER's API key
            "client_secret": self._api_secret, # ← USER's API secret
            ...
        })
        return data["access_token"]
```

### 7.3 FYERS Adapter (New)

```python
class FyersAdapter:
    broker_id: str = BrokerId.FYERS.value
    broker_name: str = "FYERS"

    def __init__(self, access_token=None, *, app_id=None, secret_id=None, ...):
        self._access_token = access_token
        self._app_id = app_id           # User's App ID (from broker_connections)
        self._secret_id = secret_id     # User's Secret ID (from broker_connections)

    def get_authorization_url(self, state: str) -> str:
        """FYERS step 1: generate authcode URL."""
        params = urlencode({
            "client_id": self._app_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "state": state,
        })
        return f"https://api-t1.fyers.in/api/v3/generate-authcode?{params}"

    async def exchange_authorization_code(self, code: str) -> str:
        """FYERS step 2: validate authcode → access_token."""
        app_id_hash = hashlib.sha256(
            f"{self._app_id}:{self._secret_id}".encode()
        ).hexdigest()
        resp = await _fyers_request("POST", "/api/v3/validate-authcode", json={
            "grant_type": "authorization_code",
            "appIdHash": app_id_hash,
            "code": code,
        })
        return resp["access_token"]
```

**FYERS auth headers (AD-9):**
```python
def _get_auth_header(self, transport: str = "rest") -> str:
    """Return the correct auth header for the transport."""
    if transport == "rest":
        return f"{self._app_id}:{self._access_token}"  # Non-Bearer for REST
    elif transport == "websocket":
        return f"Bearer {self._access_token}"           # Bearer for WebSocket
```

### 7.4 FYERS Adapter Registration

```python
# registry.py
def register_default_brokers() -> None:
    from app.brokers.adapters.upstox.adapter import UpstoxAdapter
    from app.brokers.adapters.fyers.adapter import FyersAdapter
    from app.brokers.domain.enums import BROKER_ID_UPSTOX, BrokerId

    BROKER_REGISTRY.register(BROKER_ID_UPSTOX, UpstoxAdapter)
    BROKER_REGISTRY.register(BrokerId.FYERS, FyersAdapter)
```

---

## 8. OAuth Callback — BYOB Flow

### 8.1 Current Callback (Phase 10.2A — BROKEN for multi-user)

```python
# auth.py — current (uses SHARED platform API key)
@router.get("/callback")
async def callback(code, error, state):
    adapter = gateway.create(BROKER_ID_UPSTOX)  # ← Uses shared settings.UPSTOX_API_KEY
    access_token = await adapter.exchange_authorization_code(code)
    ...
```

### 8.2 New Callback (Phase 10.2B — BYOB)

```python
# auth.py — new (uses USER's per-user credentials)
@router.get("/callback")
async def callback(code, error, state, broker: str = Query(default="UPSTOX")):
    # 1. Validate broker
    broker_id = BrokerId(broker.upper())

    # 2. Resolve USER's credentials from broker_connections
    #    (credentials were stored when user provided their API Key + Secret)
    user_credentials = resolve_user_credentials(current_user.id, broker_id, db)

    # 3. Create adapter with USER's credentials
    adapter = gateway.create(broker_id, **user_credentials)

    # 4. Exchange code via provider-specific adapter
    access_token = await adapter.exchange_authorization_code(code)

    # 5. Get profile (provider-specific)
    profile = await gateway.create(broker_id, access_token=access_token, **user_credentials).get_profile()

    # 6. Create/update broker connection
    connection = get_or_create_connection(db, current_user.id, broker_id, profile)

    # 7. Create session + persist token
    session_id = token_store.set_token(access_token, connection_id=connection.id)
    persist_token(db, session_id, connection.id, access_token, ...)

    # 8. Redirect
    response = RedirectResponse(f"{settings.FRONTEND_URL}/dashboard#session_id={session_id}")
    response.set_cookie(SESSION_COOKIE, session_id, ...)
    return response
```

### 8.3 Multi-Broker Login Endpoints

```
GET /auth/login                          → Upstox OAuth (default, backward compatible)
GET /auth/login?broker=UPSTOX            → Upstox OAuth (explicit)
GET /auth/login?broker=FYERS             → FYERS OAuth (step 1)
GET /auth/callback?code=...&state=...    → Upstox callback (backward compatible)
GET /auth/callback?code=...&state=...&broker=FYERS → FYERS callback
GET /auth/fyers/login                    → FYERS OAuth shortcut (step 1)
GET /auth/fyers/callback?auth_code=...   → FYERS callback (step 2)
```

---

## 9. Request Authentication — Enhanced Flow

### 9.1 New Flow (Phase 10.2B)

```python
def _resolve_user(db, sid):
    # 1. Get session from DB (authoritative)
    session = get_active_session(db, sid)
    if session is None:
        raise HTTPException(401, "Session invalid or expired")

    # 2. Get user
    user = db.query(User).filter(User.id == session.user_id).one_or_none()
    if user is None or user.status != "active":
        raise HTTPException(403, "Account not active")

    # 3. Get broker token (memory → DB fallback → provider-aware expiry)
    token = token_store.get_token(sid)
    if token is None:
        raise HTTPException(401, "Broker session expired — re-login required")

    # 4. Get connection metadata (for provider-specific logic)
    connection = None
    if session.broker_connection_id:
        connection = db.query(BrokerConnection).filter(
            BrokerConnection.id == session.broker_connection_id
        ).one_or_none()

    return AuthenticatedUser(
        user_id=user.id,
        access_token=token,
        connection=connection,
    )
```

### 9.2 `AuthenticatedUser` Extension

```python
@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    access_token: str
    connection: BrokerConnection | None = None  # nullable for backward compat
```

---

## 10. Token Selection Strategy

### 10.1 Strategy Matrix

| Operation | Required Capability | Token Source |
|-----------|-------------------|--------------|
| GEX snapshot capture | Market data (read-only) | User's Analytics Token (Upstox) or active token (FYERS) |
| Historical GEX query | Market data (read-only) | User's Analytics Token (Upstox) or active token (FYERS) |
| Option chain fetch | Market data (read-only) | Any active connection with market data permission |
| Paper trading execution | Paper (simulated) | No broker token needed |
| Live order placement | Order placement (write) | Trading-mode connection + daily OAuth (AD-12: needs static IP) |
| Profile / funds / margin | Account data | Active connection for the specific broker |

### 10.2 Default Connection Selection

```python
def select_connection(user_id, broker=None, capability="data", db=None):
    """Select the best broker connection for an operation."""
    query = db.query(BrokerConnection).filter(
        BrokerConnection.user_id == user_id,
        BrokerConnection.status == "connected",
    )
    if broker:
        query = query.filter(BrokerConnection.broker == broker.upper())
    if capability == "trading":
        query = query.filter(BrokerConnection.capability_mode == "trading")
    else:
        query = query.filter(BrokerConnection.capability_mode.in_(["trading", "data_only"]))

    conn = query.filter(BrokerConnection.is_default == True).first()
    return conn or query.first()
```

---

## 11. Background GEX Capture — Per-User Analytics Tokens

The current `_gex_capture_loop()` uses a shared token. With BYOB, it must iterate over users with Analytics Tokens:

```python
# For each user with an Upstox Analytics Token:
for conn in db.query(BrokerConnection).filter(
    BrokerConnection.status == "connected",
    BrokerConnection.broker == "UPSTOX",
    BrokerConnection.broker_analytics_token_encrypted.isnot(None),
):
    token = decrypt(conn.broker_analytics_token_encrypted)
    adapter = gateway.create(BrokerId.UPSTOX, access_token=token)
    # ... capture GEX using user's Analytics Token (1-year validity)
```

---

## 12. Security Considerations

### 12.1 Credential Encryption at Rest

| Property | Value |
|----------|-------|
| Algorithm | Fernet (AES-128-CBC + HMAC-SHA256) |
| Key derivation | PBKDF2-HMAC-SHA256, 480,000 iterations |
| Salt | `TOKEN_ENCRYPTION_SALT` env var (per-environment) |
| Key source | `TOKEN_ENCRYPTION_KEY` env var |
| What's encrypted | API Keys, API Secrets, Analytics Tokens, Access Tokens, Refresh Tokens |

### 12.2 Security Findings & Mitigations

| Finding | Severity | Mitigation |
|---------|----------|------------|
| Plaintext credentials in memory (adapter) | MEDIUM | Credentials decrypted only during request, not cached long-term |
| `TOKEN_ENCRYPTION_KEY` leaked → all credentials decryptable | HIGH | Key derivation with PBKDF2 + salt; rotate key re-encrypts |
| Users share API credentials (security risk) | MEDIUM | Platform warns against sharing; encrypted at rest |
| FYERS refresh token in DB (15-day validity) | LOW | Encrypted at rest; revoked on disconnect |
| `get_any_token()` still exists | LOW | Remove in this phase |
| `create_session_record()` commits directly | LOW | Fix in this phase |

### 12.3 Token/Credential Logging Prevention

**Hard rule:** Tokens, API Keys, API Secrets, and Analytics Tokens must NEVER appear in:
- Log messages
- HTTP responses
- Error messages
- Tracebacks
- Database plaintext columns

### 12.4 SEBI Compliance (AD-12)

| Requirement | Implementation |
|-------------|---------------|
| Static IP per user for order placement | `broker_connections.broker_static_ip` — user provides their own |
| Shared IPs prohibited | Each user's static IP stored separately; platform validates uniqueness |
| 2FA daily | Users must re-authenticate daily (no bypass via refresh tokens) |
| Third-party platform empanelment | StrikeNova may need broker empanelment for trading features |

---

## 13. Migration Strategy

### 13.1 Implementation Sequence

```
Slice 1: Schema & Encryption Foundation
  ├── Alembic migration: broker_connections + broker_tokens tables
  ├── Add broker_connection_id to user_sessions
  ├── Encryption layer (Fernet + PBKDF2)
  ├── TOKEN_ENCRYPTION_KEY / TOKEN_ENCRYPTION_SALT env vars
  └── Tests: encryption round-trip, migration verification

Slice 2: BYOB Credential Management
  ├── "Connect Your Broker" flow: user provides API Key + Secret
  ├── Credentials encrypted and stored in broker_connections
  ├── resolve_user_credentials() function
  ├── Update adapter constructors to accept per-user credentials
  └── Tests: credential storage, encryption, resolution

Slice 3: Token Persistence
  ├── Update token_store: DB write on set_token, DB fallback on get_token
  ├── Update auth.py callback: use USER's credentials for OAuth
  ├── Update deps.py: DB fallback on cache miss
  └── Tests: token persistence, restart recovery, DB fallback

Slice 4: Analytics Token Integration (Upstox)
  ├── User provides Analytics Token (from Developer Apps page)
  ├── Store encrypted in broker_connections
  ├── Background GEX capture uses per-user Analytics Tokens
  ├── DO NOT build OAuth extended_token fallback (AD-8)
  └── Tests: Analytics Token storage, background capture

Slice 5: FYERS Adapter (Foundation)
  ├── FyersAdapter class implementing BrokerAdapter
  ├── FYERS OAuth flow (2-step)
  ├── appIdHash computation
  ├── REST auth header: <app_id>:<token> (AD-9)
  ├── WebSocket auth header: Bearer <token> (AD-9)
  ├── Register in BrokerRegistry
  └── Tests: FYERS OAuth, auth headers, adapter registration

Slice 6: Cleanup & Hardening
  ├── Remove get_any_token()
  ├── Fix create_session_record() commit pattern
  ├── Rehydrate cache on startup
  ├── Remove/deprecate shared UPSTOX_API_KEY from config
  └── Tests: cleanup verification, rehydration
```

### 13.2 Backward Compatibility

| Current Behavior | Phase 10.2B Behavior | Migration |
|-----------------|---------------------|-----------|
| `settings.UPSTOX_API_KEY` used for all users | Per-user credentials from `broker_connections` | Existing users must provide their own API Key + Secret |
| `token_store.set_token(access_token)` → memory only | `memory + DB` | Transparent — same API |
| `User.broker_provider` populated | Still populated, plus `broker_connections` row | No data loss |

### 13.3 Deploy Sequence

1. Run Alembic migration (adds tables + nullable columns)
2. Set `TOKEN_ENCRYPTION_KEY` and `TOKEN_ENCRYPTION_SALT` env vars
3. Deploy new code
4. **Existing users must re-onboard:** provide their own Upstox API Key + Secret
5. New users: onboarding flow guides them through broker app creation
6. FYERS connection: available after env vars are set

---

## 14. Alternatives Considered

### 14.1 Platform-Level API Key (Current — REJECTED)

**How it works:** One `UPSTOX_API_KEY` for all users.

**Why it fails:** "One access token per API key." User B's login invalidates User A's token.

**Verdict:** ❌ REJECTED — does not work for multi-user. (AD-2)

### 14.2 Platform API Key + Analytics Token Hybrid

**How it works:** Platform has one API key for OAuth. Each user provides their own Analytics Token for market data.

**Why it partially works:** Analytics Token is per-user. OAuth still uses shared API key (one token at a time).

**Verdict:** ⚠️ PARTIAL — works for market data only, not for user-scoped account operations.

### 14.3 BYOB (Recommended)

**How it works:** Each user provides their own API Key + Secret. Platform stores encrypted. OAuth uses user's credentials.

**Why it works:** Each user has their own API key. One user's login doesn't affect others. Compliant with SEBI.

**Verdict:** ✅ RECOMMENDED — the only architecture that works for multi-user trading. (AD-2)

### 14.4 JWT-Based Session Tokens

**Verdict:** ❌ REJECTED — session revocation is a hard requirement.

### 14.5 Redis Token Store

**Verdict:** ❌ REJECTED — PostgreSQL is already available and sufficient.

---

## 15. Test Strategy

### 15.1 Unit Tests

| Test | What it proves |
|------|----------------|
| `test_fernet_encrypt_decrypt_round_trip` | Encryption/decryption with derived key |
| `test_credential_encryption_round_trip` | API Key + Secret encrypted/decrypted correctly |
| `test_set_token_persists_encrypted_to_db` | Token written encrypted to `broker_tokens` |
| `test_get_token_falls_back_to_db_on_cache_miss` | DB fallback works |
| `test_clear_token_clears_both_cache_and_db` | Both memory and DB cleared |
| `test_rehydrate_cache_populates_memory` | Startup rehydration works |
| `test_connection_creation_with_credentials` | Broker connection stores encrypted credentials |
| `test_multiple_connections_same_user` | Two connections (Upstox + FYERS) for same user |
| `test_default_connection_selection` | `is_default=True` used correctly |
| `test_upstox_adapter_uses_user_api_key` | Adapter uses user's API key, not platform |
| `test_fyers_adapter_uses_user_app_id` | Adapter uses user's App ID, not platform |
| `test_fyers_rest_auth_header_format` | `<app_id>:<token>` for REST |
| `test_fyers_websocket_auth_header_format` | `Bearer <token>` for WebSocket |
| `test_fyers_appidhash_computation` | `SHA256("<app_id>:<secret_id>")` is correct |
| `test_analytics_token_stored_per_user` | Analytics Token stored encrypted per user |

### 15.2 Integration Tests

| Test | What it proves |
|------|----------------|
| `test_full_oauth_flow_with_user_credentials` | OAuth using user's own API key works |
| `test_restart_recovery` | Server restart → rehydration → session survives |
| `test_logout_clears_db_token` | Token removed from DB |
| `test_broker_session_expiry_clears_token` | 401 → token cleared |
| `test_analytics_token_background_capture` | Background GEX uses per-user Analytics Token |
| `test_multi_user_independent_sessions` | User A login doesn't invalidate User B |

### 15.3 Regression Gate

- All Phase 10.2A tests (41 focused + 742 regression) must continue to pass
- No new failures in the representative regression gate

---

## 16. Risks & Blockers

| Risk | Severity | Mitigation |
|------|----------|------------|
| Users don't have Upstox Developer App | HIGH | Onboarding wizard guides users through app creation |
| Users lose API Key/Secret | MEDIUM | Platform stores encrypted; user can re-provide |
| Analytics Token generation is manual | MEDIUM | User copies from Developer Apps page |
| Static IP per user is expensive | MEDIUM | Only needed for order placement; market data doesn't need it |
| FYERS refresh token discontinued (AD-11) | MEDIUM | Daily re-login is primary path; refresh is best-effort |
| SEBI empanelment required | HIGH | StrikeNova may need broker empanelment for trading |
| `TOKEN_ENCRYPTION_KEY` not set | HIGH | Deployment checklist; startup validation |
| OAuth `extended_token` unverified (AD-8) | MEDIUM | Do not build fallback until empirically verified |
| FYERS endpoint migration (`/validate-authcode` → `/token`) | LOW | Verify against live docs before implementing |
| Users share credentials | MEDIUM | Platform warns; encrypted at rest |

---

## 17. Acceptance Criteria

- [ ] Each StrikeNova user stores their own broker API Key + Secret (encrypted)
- [ ] OAuth flow uses user's stored credentials, not platform-level credentials (AD-2, AD-3)
- [ ] One user's login does NOT invalidate another user's token
- [ ] Analytics Token stored per-user for 1-year read-only access (AD-7)
- [ ] OAuth `extended_token` NOT used as fallback until verified (AD-8)
- [ ] FYERS REST auth uses `<app_id>:<token>`, WebSocket uses `Bearer <token>` (AD-9)
- [ ] Platform auth (Google/Email OTP) independent of broker auth (AD-1, AD-10)
- [ ] All credentials encrypted at rest with Fernet + PBKDF2
- [ ] Background GEX capture uses per-user Analytics Tokens
- [ ] SEBI compliance: static IP per user for order placement (AD-12)
- [ ] `get_any_token()` removed
- [ ] `create_session_record()` commit pattern fixed
- [ ] All Phase 10.2A tests pass
- [ ] New tests cover all Phase 10.2B changes

---

## 18. Files Likely to Change

### Modified Files

| File | Change |
|------|--------|
| `app/config.py` | Remove/deprecate `UPSTOX_API_KEY`/`UPSTOX_API_SECRET`; add `TOKEN_ENCRYPTION_KEY`/`TOKEN_ENCRYPTION_SALT` |
| `app/identity.py` | Add credential columns to `BrokerConnection` model; generalize `get_or_create_user()` |
| `app/services/token_store.py` | DB persistence, encryption, rehydration, `resolve_user_credentials()` |
| `app/services/upstox.py` | Accept per-user credentials instead of `settings.UPSTOX_API_KEY` |
| `app/brokers/adapters/upstox/adapter.py` | Accept per-user credentials in constructor |
| `app/routers/auth.py` | BYOB OAuth flow using user's stored credentials |
| `app/routers/deps.py` | Resolve user's broker credentials for adapter creation |
| `app/main.py` | Background GEX capture uses per-user Analytics Tokens |

### New Files

| File | Purpose |
|------|---------|
| `app/brokers/adapters/fyers/__init__.py` | FYERS adapter package |
| `app/brokers/adapters/fyers/adapter.py` | FYERS adapter with per-user credentials |
| `alembic/versions/<hash>_add_broker_credentials.py` | Migration for credential columns |
| `tests/test_byob_auth.py` | BYOB OAuth flow tests |
| `tests/test_fyers_adapter.py` | FYERS adapter tests |

---

_This document is a specification. Implementation requires Principal Architect approval._
