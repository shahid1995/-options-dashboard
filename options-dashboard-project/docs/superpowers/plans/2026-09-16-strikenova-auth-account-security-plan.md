# StrikeNova Auth & Account Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable StrikeNova-owned account-security subsystem for email verification, password recovery, password/email changes, session security, abuse controls, security events, recent authentication, and transactional email delivery abstraction without coupling account identity to broker OAuth.

**Architecture:** Extend the existing `User`/`UserSession` identity foundation and add dedicated token/security-event persistence plus a small email transport interface. StrikeNova owns all authentication semantics; a third-party service is used only as an email delivery transport. Existing broker OAuth routes remain broker-specific and are not repurposed as StrikeNova account login.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL/CockroachDB-compatible schema patterns, Pydantic Settings, existing PBKDF2 password implementation, Next.js 14 App Router, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-16-strikenova-auth-account-security-design.md`

## Global Constraints

- Do not expose passwords, raw verification/reset tokens, reset URLs, OAuth codes, broker API credentials, access tokens, refresh tokens, or client secrets in logs, API responses, diagnostics, or security-event payloads.
- Do not use third-party authentication SaaS for the core StrikeNova identity model.
- Use a third-party transactional email provider only behind a StrikeNova-owned `EmailSender` interface.
- Keep StrikeNova account identity separate from broker identity/OAuth/authorization.
- Preserve the existing BYOB broker architecture and encrypted broker authorization records.
- Use Alembic for all production schema changes; do not rely on `create_all()` for new production schema.
- Maintain generic responses for account-recovery requests so callers cannot infer whether an email is registered.
- All verification/recovery/change tokens are opaque, high-entropy, hashed at rest, expiry-bound, and single-use.
- Every security-sensitive flow must have backend tests before implementation is considered complete.

---

## File Map

### Backend

- Modify: `backend/app/identity.py` — add account-security persistence models and reusable identity/security helpers; keep broker models separate.
- Modify: `backend/app/routers/auth.py` — add StrikeNova account-auth endpoints without changing existing broker OAuth semantics.
- Create: `backend/app/services/email.py` — provider-independent email transport protocol and development/test sender.
- Create: `backend/app/services/account_security.py` — token generation/consumption, verification/reset workflows, recent-auth state, and security-event helpers.
- Modify: `backend/app/services/token_store.py` only where necessary to remove duplicated account-session semantics; broker OAuth state behavior must remain unchanged.
- Modify: `backend/app/config.py` — add email/security settings with safe defaults and no provider credentials in frontend configuration.
- Create: `backend/alembic/versions/<new_revision>_account_security.py` — schema migration for security tokens/events/pending email changes.
- Create: `backend/tests/test_account_security.py` — unit/service-level security tests.
- Create: `backend/tests/test_auth_account_flows.py` — API integration tests for registration, verification, recovery, password/email changes, sessions, and enumeration resistance.
- Modify/create as needed: existing auth fixture/helpers under `backend/tests/` — reuse the existing DB/session setup instead of inventing a parallel harness.

### Frontend

- Create/modify: existing auth route/components discovered during implementation — account login/register/verify/reset/change forms.
- Create: focused Vitest coverage adjacent to those auth components or in the repository's existing frontend test location.
- Do not modify public-page design tokens or public marketing interactions as part of this phase.

### Documentation

- Existing approved spec: `docs/superpowers/specs/2026-09-16-strikenova-auth-account-security-design.md`
- This plan: `docs/superpowers/plans/2026-09-16-strikenova-auth-account-security-plan.md`

---

## Task 1: Freeze the account-vs-broker auth boundary

**Files:**
- Modify: `backend/app/routers/auth.py`
- Test: `backend/tests/test_auth_account_flows.py`

**Interfaces:**
- Existing broker OAuth routes keep their current semantics and state-binding behavior.
- New StrikeNova account-login endpoint must not call the broker gateway or initiate broker OAuth.

- [ ] **Step 1: Write failing boundary tests**

Add tests proving:

```python
def test_account_login_does_not_initiate_broker_oauth(client, db):
    response = client.post("/auth/account/login", json={"email": "u@example.com", "password": "correct"})
    assert response.status_code in {200, 401}
    assert "authorization_url" not in response.json()


def test_broker_oauth_login_remains_broker_flow(client):
    response = client.get("/auth/login?broker=UPSTOX")
    assert response.status_code in {302, 400, 401}
```

The first test should be completed with real fixture setup in the implementation task; the essential assertion is that account login never routes through `gateway.create()` or broker OAuth.

- [ ] **Step 2: Run the focused tests and verify the new account-login test fails before implementation**

Run:

```bash
cd options-dashboard-project/backend
pytest tests/test_auth_account_flows.py -k "account_login" -v
```

Expected: the new account-login test fails because the endpoint does not yet exist.

- [ ] **Step 3: Add a dedicated StrikeNova account-login route**

Use a route such as `POST /auth/account/login` so the existing `GET /auth/login` broker-OAuth contract is preserved. Reuse `resolve_user_credentials` only for broker routes; account login reads the StrikeNova `User` record and uses `verify_password()`.

- [ ] **Step 4: Run focused tests**

Run the same command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/auth.py backend/tests/test_auth_account_flows.py
git commit -m "feat(auth): separate account login from broker oauth"
```

---

## Task 2: Add durable security data models and migration

**Files:**
- Modify: `backend/app/identity.py`
- Create: `backend/alembic/versions/<new_revision>_account_security.py`
- Test: `backend/tests/test_account_security.py`

**Interfaces:**
- `EmailVerificationToken`, `PasswordResetToken`, `PendingEmailChange`, `SecurityEvent` SQLAlchemy models.
- Each token model exposes `token_hash`, `expires_at`, `used_at`, and ownership fields required by the spec.
- `SecurityEvent` stores structured metadata without secret-bearing values.

- [ ] **Step 1: Write failing persistence tests**

Tests must prove:

```python
def test_verification_token_is_single_use(db):
    # create token -> consume once -> second consume returns None
    ...


def test_expired_reset_token_is_rejected(db):
    ...


def test_security_event_metadata_does_not_store_raw_token(db):
    ...
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```bash
cd options-dashboard-project/backend
pytest tests/test_account_security.py -v
```

Expected: FAIL because the models/helpers do not yet exist.

- [ ] **Step 3: Implement the SQLAlchemy models and Alembic revision**

Use `String`/`Text`/`DateTime` types already used by the identity module. Add indexes for user ownership and expiry lookup. Add appropriate uniqueness where it prevents active-token duplication without preventing historical audit rows. Do not add raw token columns.

- [ ] **Step 4: Verify migration upgrade/downgrade against the existing test database**

Run the repository's standard Alembic test command or, if none exists:

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Expected: all three operations succeed and schema returns to the intended head state.

- [ ] **Step 5: Run focused persistence tests**

Run:

```bash
pytest tests/test_account_security.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/identity.py backend/alembic/versions backend/tests/test_account_security.py
git commit -m "feat(auth): add durable account security records"
```

---

## Task 3: Implement token service and email transport abstraction

**Files:**
- Create: `backend/app/services/account_security.py`
- Create: `backend/app/services/email.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_account_security.py`

**Interfaces:**

```python
class EmailSender(Protocol):
    async def send(*, to: str, subject: str, html: str, text: str) -> None: ...


def create_opaque_token() -> tuple[str, str]: ...

def consume_token(db: Session, *, token: str, kind: str, now: datetime) -> TokenRecord | None: ...

def record_security_event(...): ...

def mark_recent_authentication(...): ...
def has_recent_authentication(...): ...
```

- [ ] **Step 1: Write failing token lifecycle tests**

Cover:

```python

def test_token_is_hashed_before_persistence(...): ...
def test_token_expires(...): ...
def test_token_cannot_be_replayed(...): ...
def test_old_verification_token_is_invalidated_when_new_one_is_created(...): ...
def test_recent_authentication_expires(...): ...
```

- [ ] **Step 2: Run focused tests**

Expected: FAIL before implementation.

- [ ] **Step 3: Implement high-entropy opaque tokens**

Use Python's cryptographically secure random token generator. Store only a SHA-256 or equivalent one-way digest. Compare hashes using constant-time comparison where applicable. Make token type and expiry explicit.

- [ ] **Step 4: Implement `EmailSender` and deterministic test sender**

The production implementation should be injectable and vendor-neutral. The test sender captures outgoing messages in memory so the test suite can assert links/subjects without a real provider.

- [ ] **Step 5: Add config values**

Add provider-neutral settings such as sender address, verification TTL, password-reset TTL, recent-auth TTL, and enable/disable flags. Provider API keys remain backend-only environment variables and are never surfaced through Next.js runtime configuration.

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_account_security.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/account_security.py backend/app/services/email.py backend/app/config.py backend/tests/test_account_security.py
git commit -m "feat(auth): add token and email security services"
```

---

## Task 4: Implement registration and email verification

**Files:**
- Modify: `backend/app/routers/auth.py`
- Test: `backend/tests/test_auth_account_flows.py`

**Interfaces:**

```text
POST /auth/register
POST /auth/verify-email
POST /auth/resend-verification
```

- [ ] **Step 1: Write failing API tests**

Cover successful registration, duplicate/normalized email behavior, verification email capture, invalid token, expired token, replay, resend invalidation, and verification state transition.

Example:

```python
def test_register_creates_unverified_user_and_sends_verification(client, test_email_sender):
    response = client.post("/auth/register", json={"email": "User@Example.com", "password": "..."})
    assert response.status_code == 200
    assert test_email_sender.last_message is not None


def test_verification_token_is_single_use(client, test_email_sender):
    ...
```

- [ ] **Step 2: Run focused tests and verify they fail**

```bash
pytest tests/test_auth_account_flows.py -k "register or verify" -v
```

- [ ] **Step 3: Implement registration**

Normalize email consistently, create the account, create the verification record, and send the email. Do not send password contents anywhere. Keep account-existence responses deliberately generic where the existing UX allows it.

- [ ] **Step 4: Implement verification/resend**

Consume the opaque token atomically. Mark the account verified only after successful token validation. Resend invalidates prior active verification tokens.

- [ ] **Step 5: Run focused tests**

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/auth.py backend/tests/test_auth_account_flows.py
git commit -m "feat(auth): add email verification flow"
```

---

## Task 5: Implement forgot-password and reset-password

**Files:**
- Modify: `backend/app/routers/auth.py`
- Test: `backend/tests/test_auth_account_flows.py`

**Interfaces:**

```text
POST /auth/forgot-password
POST /auth/reset-password
```

- [ ] **Step 1: Write failing API tests**

Cover registered and unknown emails returning the same response shape, captured reset email, invalid token, expired token, replay, password update, and session revocation.

Example:

```python
def test_forgot_password_does_not_reveal_account_existence(client):
    known = client.post("/auth/forgot-password", json={"email": "known@example.com"})
    unknown = client.post("/auth/forgot-password", json={"email": "missing@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
```

- [ ] **Step 2: Run focused tests and verify failure**

```bash
pytest tests/test_auth_account_flows.py -k "forgot_password or reset_password" -v
```

- [ ] **Step 3: Implement recovery request**

Always emit a generic response. Only generate/send a reset message when an eligible local-password account exists. Do not reveal that branch in response timing or content beyond what is operationally necessary; use the repository's existing rate-limit/backoff approach once Task 7 is present.

- [ ] **Step 4: Implement reset atomically**

Consume the token, update the password hash, mark the token used, revoke existing user sessions, write a security event, and issue no session until the normal account-login route is used. Send a security notification through the same email abstraction.

- [ ] **Step 5: Run focused tests**

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/auth.py backend/tests/test_auth_account_flows.py
git commit -m "feat(auth): add password recovery flow"
```

---

## Task 6: Harden sessions, password/email changes, and recent authentication

**Files:**
- Modify: `backend/app/identity.py`
- Modify: `backend/app/routers/auth.py`
- Modify: `backend/app/services/account_security.py`
- Test: `backend/tests/test_auth_account_flows.py`
- Test: `backend/tests/test_account_security.py`

**Interfaces:**

```text
POST /auth/logout
POST /auth/logout-all
POST /auth/change-password
POST /auth/change-email
GET  /auth/session
GET  /auth/security-events
```

- [ ] **Step 1: Write failing recent-auth tests**

Prove that change-password and change-email fail after the recent-auth window expires and succeed after an authenticated recent-auth action.

- [ ] **Step 2: Write failing session-revocation tests**

Create multiple sessions for one user; verify logout-all revokes each; verify password reset/change revokes the expected session set; verify revoked sessions are rejected immediately.

- [ ] **Step 3: Write failing email-change tests**

Prove the current email remains unchanged until the new address is verified and that a pending change is expired/replayed safely.

- [ ] **Step 4: Implement recent-auth state server-side**

Use a timestamp tied to the user/session rather than a client-controlled flag. Provide a reusable dependency/helper for sensitive account operations.

- [ ] **Step 5: Implement password change**

Require current authenticated session plus recent authentication; validate the new password; update the hash; revoke other sessions according to the defined policy; emit event; send notification.

- [ ] **Step 6: Implement email change**

Require recent authentication; store the pending new address and verification token; do not mutate the canonical email until verification succeeds; invalidate older pending changes for the same user.

- [ ] **Step 7: Implement session endpoints**

Use the durable `UserSession` table as the authoritative source. Remove only expired/revoked sessions where safe; do not introduce a second authoritative in-memory session registry for account auth.

- [ ] **Step 8: Run focused tests**

```bash
pytest tests/test_account_security.py tests/test_auth_account_flows.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/identity.py backend/app/routers/auth.py backend/app/services/account_security.py backend/tests/test_account_security.py backend/tests/test_auth_account_flows.py
git commit -m "feat(auth): harden sessions and sensitive account changes"
```

---

## Task 7: Add abuse controls and security-event verification

**Files:**
- Modify: `backend/app/routers/auth.py`
- Modify: `backend/app/services/account_security.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_account_security.py`
- Test: `backend/tests/test_auth_account_flows.py`

**Interfaces:**

Rate-limit keys must cover at least:

```text
login: email + IP
register: IP
verify-resend: account/email + IP
forgot-password: email + IP
reset-password: token + IP
email-change: user + IP
```

- [ ] **Step 1: Write failing rate-limit tests**

Use a deterministic clock or test configuration so the suite can prove the configured threshold is enforced and recovers after the window.

- [ ] **Step 2: Write failing secret-leakage tests**

Capture application logs/security events during verification and reset flows and assert that the raw token, password, reset URL, and email credentials are absent.

- [ ] **Step 3: Implement bounded rate limiting**

Prefer an implementation compatible with the current modular-monolith deployment. Avoid adding Redis merely for this phase unless the existing runtime already requires it. The design should allow a future Redis-backed implementation without changing endpoint contracts.

- [ ] **Step 4: Implement security-event emission**

Emit only safe structured metadata. Store success/failure events where they provide actionable audit value; avoid high-volume sensitive data that would turn the audit table into an uncontrolled log sink.

- [ ] **Step 5: Run focused tests**

```bash
pytest tests/test_account_security.py tests/test_auth_account_flows.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/auth.py backend/app/services/account_security.py backend/app/config.py backend/tests
git commit -m "feat(auth): add abuse controls and security audit events"
```

---

## Task 8: Build the frontend account-security flows

**Files:**
- Create/modify: Next.js auth routes/components identified from the current frontend structure.
- Test: existing Vitest auth test locations.

**Interfaces:**

The frontend consumes only the StrikeNova account API. It never receives email-provider credentials, raw tokens outside verification/reset URL handling, or broker secrets.

- [ ] **Step 1: Inventory existing auth screens/components**

Use the current App Router tree to identify login/register/account settings routes before creating duplicates. Preserve the existing visual system and do not alter public-page typography/CTA behavior.

- [ ] **Step 2: Add failing UI tests**

Cover registration success/error, verification success/expired/replayed states, forgot-password generic confirmation, reset-password success/invalid-token states, change-password validation, and change-email verification-pending state.

- [ ] **Step 3: Implement the forms and API calls**

Use the project's current HTTP client and form conventions. Keep token values out of analytics/logging and never store passwords in persistent browser storage.

- [ ] **Step 4: Run frontend tests**

```bash
cd options-dashboard-project/frontend
npm test -- --run
```

Expected: PASS.

- [ ] **Step 5: Run production build**

```bash
npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat(frontend): add account security flows"
```

---

## Task 9: End-to-end verification and regression audit

**Files:**
- Modify: tests only where a verified regression is found.
- Create/modify: documentation only where verification findings require explicit operational notes.

- [ ] **Step 1: Run the complete backend test suite**

```bash
cd options-dashboard-project/backend
pytest -q
```

Expected: all previously passing tests plus the new auth/security suites pass.

- [ ] **Step 2: Run the complete frontend test suite and production build**

```bash
cd options-dashboard-project/frontend
npm test -- --run
npm run build
```

Expected: PASS/PASS.

- [ ] **Step 3: Verify the database migration from a clean schema**

Run the repository-standard fresh-db migration test. Confirm the new tables/indexes are present and existing identity/broker tables remain intact.

- [ ] **Step 4: Perform a secret-leak audit**

Search logs, response bodies, and tests for forbidden strings/fields such as `password`, raw token values, `reset_token`, `verification_token`, broker access tokens, refresh tokens, and OAuth authorization codes. Confirm only intended masked/boolean/status values are exposed.

- [ ] **Step 5: Verify broker OAuth regression**

Exercise the existing broker login/callback path using its current signed-state mechanics. Confirm account registration/login/recovery work without changing broker authorization behavior.

- [ ] **Step 6: Verify production configuration boundaries**

Confirm email-provider credentials exist only in backend environment configuration; no `NEXT_PUBLIC_*` or other browser-exposed variables contain provider secrets.

- [ ] **Step 7: Create a final verification commit if tests/docs changed**

```bash
git add backend frontend docs
 git commit -m "test(auth): verify account security end to end"
```

---

## Completion Checklist

- [ ] Registration creates a properly governed StrikeNova account.
- [ ] Email verification is durable, expiring, single-use, and replay-safe.
- [ ] Verification resend invalidates prior active tokens.
- [ ] Forgot-password response does not reveal account existence.
- [ ] Password reset token is durable, hashed, expiring, and single-use.
- [ ] Successful password reset revokes active sessions.
- [ ] Password change requires appropriate authentication freshness.
- [ ] Email change waits for verification before changing canonical email.
- [ ] Sessions can be revoked individually and through logout-all.
- [ ] Rate limits cover login/recovery/verification-sensitive flows.
- [ ] Security events contain safe metadata only.
- [ ] Email delivery is provider-abstracted and provider credentials stay server-side.
- [ ] Broker OAuth remains separate from StrikeNova account login.
- [ ] Full backend and frontend suites pass.
- [ ] Production build passes.
- [ ] No public-page design behavior was modified by this phase.
