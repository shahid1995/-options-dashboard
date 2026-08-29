# StrikeNova Identity & Broker Login Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a clean authentication foundation in which StrikeNova identity (email/password and Google) is independent from broker authentication, while adding broker-login adapters without coupling login to market-data or order-execution authorization.

**Architecture:** StrikeNova owns the user identity and session. Broker OAuth/login is an optional, separately persisted connection owned by that StrikeNova user. Each broker adapter exposes authentication only; market-data credentials and trading credentials are separate capabilities and are not activated merely because a broker login succeeds.

**Tech Stack:** Next.js/React frontend, FastAPI backend, SQLAlchemy, existing `users`, `broker_connections`, `broker_tokens`, `user_sessions`, broker gateway/adapter architecture, encrypted credential storage, signed OAuth state.

**Spec:** `docs/superpowers/specs/2026-08-29-identity-broker-connection-architecture-design.md` (approved architecture; if the exact file is absent in the repository, use the approved architecture document from the project control-center conversation as the authoritative source).

## Global Constraints

- StrikeNova identity MUST remain independent from broker identity.
- Google/email authentication MUST NOT automatically grant broker data or trading authorization.
- Broker login, live market data, and order execution MUST remain three separate capabilities.
- Upstox Analytics Token MUST remain a data-only credential and MUST NOT be treated as broker login or trading authorization.
- User broker credentials MUST NOT be stored as shared Railway environment variables.
- Per-user broker credentials MUST remain encrypted at rest.
- OAuth state MUST remain signed and bound to the initiating StrikeNova session/user.
- Multiple broker connections per StrikeNova user MUST remain supported.
- Do not implement order placement in this plan.
- Do not make market-data access a prerequisite for broker login.
- Do not make broker login a prerequisite for StrikeNova account creation/login.
- Preserve existing adapter/gateway boundaries and frozen AD-1 through AD-12 decisions.
- Every implementation task ends with focused tests before moving to the next task.

---

## File Map

### Identity subsystem
- Modify: `frontend/components/public/AuthModal.js` — add Google sign-in entry point while preserving email/password behavior and broker-login separation.
- Modify: `frontend/lib/api.js` — identity endpoints and Google initiation/callback handling.
- Modify: `frontend/lib/session.js` — maintain the existing session contract; do not mix broker tokens into the StrikeNova identity session.
- Modify: `backend/app/routers/auth.py` — StrikeNova identity endpoints and Google OAuth callback; broker OAuth remains a separate flow.
- Modify: `backend/app/identity.py` — identity/session persistence and provider metadata where required.
- Modify: `backend/app/config.py` — optional Google application configuration; no broker user secrets.
- Test: existing frontend auth tests plus backend auth/identity tests.

### Broker authentication subsystem
- Modify: `backend/app/brokers/gateway.py` and existing broker domain interfaces only where needed to expose authentication independently.
- Modify: existing broker auth adapter(s), starting with Upstox, so broker OAuth is an explicit connection operation for an already authenticated StrikeNova user.
- Create/modify: broker-specific auth adapter tests for each broker enabled in this phase.
- Modify: `backend/app/routers/auth.py` only through clearly separated broker-login endpoints/callbacks; do not reuse Google/email identity endpoints.

### Documentation and configuration
- Create/modify: broker capability documentation to state exactly what broker login enables and what it does not enable.
- Do not add `UPSTOX_API_KEY`, `UPSTOX_API_SECRET`, or user broker credentials to frontend environment variables.

---

### Task 1: Freeze the Identity-vs-Broker Contract in Tests

**Files:**
- Test: backend identity/auth tests and frontend `AuthModal` tests.
- Modify: only the smallest existing files needed to expose the test seams.

**Interfaces:**
- Consumes: existing `users`, `user_sessions`, broker connection models, current auth routes.
- Produces: executable tests proving StrikeNova authentication and broker authentication are independent.

- [ ] **Step 1: Write failing backend tests for identity independence.**

Test cases MUST cover:

```python
def test_email_login_creates_strikenova_session_without_broker_connection():
    ...

def test_google_login_creates_strikenova_session_without_broker_connection():
    ...

def test_broker_connection_requires_existing_strikenova_session():
    ...

def test_broker_connection_does_not_change_identity_source():
    ...
```

The assertions must verify that successful identity login creates/uses `user_sessions`, while `broker_connections` remains absent unless the user explicitly starts broker login.

- [ ] **Step 2: Run the focused backend auth tests and confirm the new tests fail for the intended architectural reason.**

Run:

```bash
cd options-dashboard-project/backend
pytest -q tests --disable-warnings --maxfail=1
```

Expected: the newly added contract tests fail because the current implementation does not yet expose the complete independent identity/broker contract.

- [ ] **Step 3: Add frontend contract tests.**

The tests must assert that:

```text
Sign in with Google -> identity flow only
Email sign in -> identity flow only
Connect broker -> separate action
No identity-login action calls a broker OAuth endpoint
```

- [ ] **Step 4: Run the focused frontend auth test file.**

Run the repository's existing frontend test command targeting `AuthModal.test.js` and related public-auth tests. Expected: new tests fail until the UI wiring is implemented.

- [ ] **Step 5: Commit the contract tests.**

```bash
git add frontend/components/public/AuthModal.test.js frontend/lib backend/app
 git commit -m "test: define independent identity and broker auth contract"
```

---

### Task 2: Implement Google as a StrikeNova Identity Provider

**Files:**
- Modify: `backend/app/routers/auth.py`
- Modify: `backend/app/identity.py`
- Modify: `backend/app/config.py`
- Modify: `frontend/lib/api.js`
- Modify: `frontend/components/public/AuthModal.js`
- Test: backend Google auth tests and frontend auth-modal tests.

**Interfaces:**
- Consumes: existing StrikeNova session creation and user model.
- Produces: `GET /auth/google` initiation and `GET /auth/google/callback` callback, returning a StrikeNova session only.

- [ ] **Step 1: Add failing tests for Google initiation.**

The backend test must assert that the endpoint redirects to Google's authorization endpoint and includes state that is cryptographically bound to the current StrikeNova session. It MUST NOT contain broker credentials.

- [ ] **Step 2: Add failing callback tests.**

Cover:

```python
def test_google_callback_creates_new_strikenova_user():
    ...

def test_google_callback_reuses_existing_user_by_verified_provider_subject():
    ...

def test_google_callback_rejects_invalid_state():
    ...

def test_google_callback_does_not_create_broker_connection():
    ...
```

Use mocked Google token/userinfo responses; never call Google during tests.

- [ ] **Step 3: Implement Google configuration as optional platform configuration.**

Use explicit settings such as:

```python
GOOGLE_CLIENT_ID: str = ""
GOOGLE_CLIENT_SECRET: str = ""
GOOGLE_REDIRECT_URI: str = ""
```

Missing Google configuration must produce a controlled `503`/configuration error from the Google login endpoint, not a backend startup crash.

- [ ] **Step 4: Implement Google authorization-code exchange.**

The callback MUST:

1. validate signed state;
2. exchange the code with Google;
3. validate the returned identity data, including a stable provider subject and verified email where supplied;
4. find or create the StrikeNova user;
5. create a StrikeNova session;
6. redirect to the frontend/dashboard using the existing secure session mechanism;
7. never create or mutate `broker_connections`.

- [ ] **Step 5: Wire the AuthModal Google button.**

The Google button must initiate `/auth/google` and must not call `/auth/login` or any broker adapter endpoint.

- [ ] **Step 6: Run backend and frontend focused tests.**

Expected: all identity contract tests pass.

- [ ] **Step 7: Commit.**

```bash
git add backend/app/routers/auth.py backend/app/identity.py backend/app/config.py frontend/lib/api.js frontend/components/public/AuthModal.js
 git commit -m "feat: add Google StrikeNova identity login"
```

---

### Task 3: Separate Broker Login from StrikeNova Identity

**Files:**
- Modify: `backend/app/routers/auth.py`
- Modify: `backend/app/brokers/gateway.py`
- Modify: existing broker auth adapter base/interface.
- Test: broker-auth route and adapter tests.

**Interfaces:**
- Consumes: authenticated StrikeNova session from Task 2 or existing email/password session.
- Produces: broker connection lifecycle endpoints that explicitly require `CurrentUser`/`AuthenticatedUser` and bind OAuth state to that user.

- [ ] **Step 1: Add failing tests for broker-login authorization.**

Required cases:

```python
def test_broker_login_requires_strikenova_session():
    ...

def test_broker_oauth_state_contains_user_session_binding():
    ...

def test_broker_callback_binds_connection_to_initiating_user():
    ...

def test_broker_callback_cannot_switch_user_by_changing_query_parameters():
    ...
```

- [ ] **Step 2: Implement explicit broker-login route semantics.**

Use a route namespace/contract such as:

```text
GET /auth/broker/{broker}/login
GET /auth/broker/{broker}/callback
```

The exact existing route can be preserved if compatibility requires it, but the internal operation MUST be explicitly classified as broker authentication rather than StrikeNova identity authentication.

- [ ] **Step 3: Ensure OAuth callback obtains broker credentials from the connection owned by the initiating user.**

Do not accept an arbitrary user ID, broker account ID, or credential identifier from the browser callback.

- [ ] **Step 4: Keep broker login capability-neutral.**

Successful broker OAuth may create/update a `broker_connection` and store its access/refresh token, but MUST NOT automatically set market-data or trading authorization to active unless that capability has its own explicit rules.

- [ ] **Step 5: Run broker auth tests.**

Expected: authenticated-first broker OAuth tests pass and unauthenticated broker-login attempts fail safely.

- [ ] **Step 6: Commit.**

```bash
git add backend/app/routers/auth.py backend/app/brokers/gateway.py backend/app/brokers
 git commit -m "refactor: separate broker authentication from platform identity"
```

---

### Task 4: Complete Upstox Broker Login Adapter

**Files:**
- Modify: existing Upstox auth adapter/service only where required.
- Modify: broker auth tests.
- Test: Upstox OAuth initiation, callback, profile/account extraction, and failure cases.

**Interfaces:**
- Consumes: authenticated StrikeNova user and that user's Upstox BYOB credentials when configured.
- Produces: an Upstox broker connection and broker access token, without activating data-only or trading capability implicitly.

- [ ] **Step 1: Add failing tests for BYOB Upstox login.**

Test both cases:

```text
Authenticated user + stored BYOB key/secret -> OAuth URL uses user's credentials.
Authenticated user + no BYOB credentials -> controlled configuration error; no silent shared-user credential behavior.
```

- [ ] **Step 2: Add callback tests.**

Verify authorization-code exchange, profile retrieval, account ID extraction, encrypted token persistence, session/connection binding, and invalid-state rejection.

- [ ] **Step 3: Remove any dependency on platform Upstox credentials for user-owned BYOB flow.**

Platform credentials may remain temporarily for explicitly documented backwards compatibility, but they MUST NOT become the hidden credential source for a user who has no explicit authorization path.

- [ ] **Step 4: Preserve Analytics Token as a separate credential.**

No Upstox OAuth login test may assume that an Analytics Token exists. No Analytics Token operation may require OAuth login as part of this task.

- [ ] **Step 5: Run all Upstox auth tests.**

Expected: existing tests plus new separation tests pass.

- [ ] **Step 6: Commit.**

```bash
git add backend/app/brokers/adapters/upstox backend/app/services/upstox.py backend/app/routers/auth.py
 git commit -m "feat: harden Upstox broker login boundary"
```

---

### Task 5: Add FYERS Broker Login Adapter

**Files:**
- Create/modify: FYERS broker adapter/auth implementation following existing adapter conventions.
- Modify: broker gateway registration.
- Test: FYERS auth adapter tests.

**Interfaces:**
- Consumes: authenticated StrikeNova user and user-owned FYERS credentials where required.
- Produces: FYERS broker connection plus access/refresh-token state according to current official FYERS API behavior.

- [ ] **Step 1: Add failing tests for FYERS authorization URL and state binding.**

- [ ] **Step 2: Add failing tests for code exchange and token persistence.**

- [ ] **Step 3: Implement the FYERS auth adapter using the existing broker authentication interface.**

The adapter MUST NOT expose market-data or trading methods through the authentication contract.

- [ ] **Step 4: Register FYERS in the broker gateway.**

- [ ] **Step 5: Add explicit refresh-token behavior only where the current official FYERS API supports it.**

Do not assume a refresh token means data/trading capabilities are the same; token renewal remains authentication/session management.

- [ ] **Step 6: Run FYERS tests and the complete backend test suite.**

- [ ] **Step 7: Commit.**

```bash
git add backend/app/brokers
 git commit -m "feat: add FYERS broker authentication adapter"
```

---

### Task 6: Add the Remaining Broker Authentication Adapters Incrementally

**Files:**
- Create/modify: broker adapters for Dhan, Angel One, 5paisa, Alice Blue, ICICI Direct, Kotak Neo, and Groww only after verifying each broker's current official authentication documentation.
- Modify: broker gateway registration.
- Test: one focused auth test module per broker.

**Interfaces:**
- Consumes: the common `BrokerAuth` interface and authenticated StrikeNova user context.
- Produces: broker-specific connection/session state without automatically activating market data or trading.

- [ ] **Step 1: For each broker, verify the current official authentication flow before coding.**

For each adapter record:

```text
authorization method
credential requirements
access-token lifetime
refresh mechanism
redirect requirements
account-ID extraction
rate/security constraints
BYOB support
```

- [ ] **Step 2: Add failing adapter tests before implementation.**

- [ ] **Step 3: Implement one broker at a time.**

- [ ] **Step 4: Register the broker in the gateway.**

- [ ] **Step 5: Run that broker's tests plus the complete backend suite.**

- [ ] **Step 6: Commit each broker independently.**

This keeps a broker-specific failure from contaminating the entire authentication rollout.

---

### Task 7: Build the Frontend Broker Connection UX

**Files:**
- Modify: `frontend/components/public/AuthModal.js` only for identity actions; do not add broker connection logic there beyond a clear post-login navigation affordance.
- Modify/create: authenticated Settings/broker connection components following existing project conventions.
- Modify: `frontend/lib/api.js` for broker connection endpoints.
- Test: Settings/broker connection UI tests.

**Interfaces:**
- Consumes: authenticated StrikeNova session and broker-auth endpoints.
- Produces: explicit UI actions: `Connect Google`/identity login, `Connect Broker`, and later `Connect Market Data`/`Enable Trading` as separate flows.

- [ ] **Step 1: Add failing UI tests showing broker connection is not part of account creation.**

- [ ] **Step 2: Add a broker connection section to authenticated Settings.**

The UI must communicate:

```text
StrikeNova Account: Connected
Broker Account: Not Connected
Market Data: Not Connected
Trading: Not Enabled
```

- [ ] **Step 3: Add broker selection and OAuth initiation.**

- [ ] **Step 4: Add broker connection status and disconnect action.**

- [ ] **Step 5: Keep market-data and trading controls visually and behaviorally separate.**

- [ ] **Step 6: Run frontend auth/settings tests.**

- [ ] **Step 7: Commit.**

```bash
git add frontend
 git commit -m "feat: add independent broker connection UX"
```

---

### Task 8: Remove Shared User Broker Credentials from Runtime Configuration

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/services/upstox.py`
- Modify: any remaining platform-credential fallback paths discovered by tests/search.
- Test: configuration and OAuth credential-selection tests.

**Interfaces:**
- Consumes: encrypted per-user broker credentials.
- Produces: no user-facing authentication flow that silently depends on shared Railway broker credentials.

- [ ] **Step 1: Add failing tests proving user-owned credentials are selected explicitly.**

- [ ] **Step 2: Make `UPSTOX_REDIRECT_URI` optional with a safe backend-URL derivation mechanism or explicit documented configuration fallback.**

- [ ] **Step 3: Make platform Upstox API key/secret fallback disabled by default.**

- [ ] **Step 4: Ensure missing optional broker configuration produces controlled endpoint errors rather than startup failure.**

- [ ] **Step 5: Run configuration and auth tests.**

- [ ] **Step 6: Document which Railway variables are platform configuration versus user credentials.**

- [ ] **Step 7: Commit.**

```bash
git add backend/app/config.py backend/app/services/upstox.py docs
 git commit -m "security: remove shared broker credential dependency"
```

---

### Task 9: End-to-End Verification and Security Audit

**Files:**
- Test: complete backend and frontend suites.
- Test: new auth integration/security tests.
- Modify: documentation only if verification finds an inaccurate contract.

**Interfaces:**
- Consumes: completed identity and broker-login implementation.
- Produces: verified authentication boundary suitable for later independent data/trading capabilities.

- [ ] **Step 1: Run backend test suite.**

```bash
cd options-dashboard-project/backend
pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Run frontend test suite.**

Use the repository's existing frontend test command. Expected: zero failures.

- [ ] **Step 3: Run frontend production build.**

Expected: successful build with no new warnings/errors that affect authentication.

- [ ] **Step 4: Run a credential-boundary audit.**

Verify that:

```text
Google identity login -> no broker credential access
Email identity login -> no broker credential access
Broker OAuth -> requires StrikeNova session
Broker OAuth -> binds callback to initiating user
Analytics Token -> remains independent
Trading -> remains unavailable/not activated by login
User broker secrets -> encrypted and never exposed to frontend
Railway env -> contains only application-level configuration/secrets
```

- [ ] **Step 5: Verify negative cases.**

Test invalid OAuth state, expired state, missing session, wrong-user callback, revoked broker token, expired token, and missing optional configuration.

- [ ] **Step 6: Review the final diff for scope leakage.**

Reject any change that introduces order placement, market-data authorization, or broker credentials into StrikeNova identity authentication.

- [ ] **Step 7: Commit verification documentation.**

```bash
git add docs
 git commit -m "docs: record identity and broker login verification"
```

---

## Explicit Non-Goals

This plan intentionally does **not** implement:

1. Upstox Analytics Token data-only connection UX.
2. GEX data capture changes.
3. `data_status` / `data_source` migration.
4. Trading enablement.
5. Static-IP registration for trading.
6. Order placement, modification, cancellation, or portfolio trading APIs.
7. Broker market-data adapters.

Those are separate capabilities and must receive their own implementation plans after this identity/broker-login foundation is verified.

## Verification Gate Before Market Data / Trading Work

The next phase may begin only when all of the following are true:

- StrikeNova account login works with email/password and Google.
- Broker login works independently for the enabled brokers.
- A user can exist without any broker connection.
- A broker connection can exist without automatically enabling trading.
- Upstox Analytics Token remains independent of OAuth login.
- No user broker credential is required in Railway environment variables.
- All backend/frontend tests pass.
- Production build passes.
- OAuth state and user-binding security tests pass.
