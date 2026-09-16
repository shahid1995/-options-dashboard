# StrikeNova Auth & Account Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement StrikeNova-owned account authentication and security flows: account login, email verification, password recovery, password/email changes, session revocation, rate limiting, security events, and recent authentication.

**Architecture:** Keep the existing broker OAuth route `GET /auth/login` unchanged. Add clearly named StrikeNova account endpoints under `/auth/account/*`, using `User` and durable `UserSession` as the identity/session foundation. Add dedicated token/security-event records and a provider-neutral `EmailSender`; only email delivery is external.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL/CockroachDB-compatible schema, Pydantic Settings, existing PBKDF2 password implementation, Next.js 14, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-16-strikenova-auth-account-security-design.md`

## Global Constraints

- Account identity and broker OAuth/authorization remain separate.
- Existing broker OAuth signed-state and BYOB credential behavior must remain unchanged.
- Store only hashes of verification/reset tokens.
- Verification/reset tokens are single-use and expiry-bound.
- Recovery endpoints return account-enumeration-resistant responses.
- No passwords, raw tokens, reset URLs, broker credentials, access tokens, refresh tokens, or OAuth codes may enter logs/security events/API responses.
- New production schema is created through Alembic.
- Email provider credentials exist only in backend environment configuration.
- This phase must not alter public marketing-page design behavior.

## File Map

- Modify: `backend/app/identity.py` — security persistence models.
- Modify: `backend/app/routers/auth.py` — account endpoints.
- Create: `backend/app/services/account_security.py` — token, recent-auth, rate-limit and security-event services.
- Create: `backend/app/services/email.py` — `EmailSender` abstraction and test sender.
- Modify: `backend/app/config.py` — security/email configuration.
- Create: `backend/alembic/versions/c1d2e3f4a5b6_add_account_security.py` — schema migration.
- Create: `backend/tests/test_account_security.py` — service/persistence tests.
- Create: `backend/tests/test_auth_account_flows.py` — API integration tests.
- Modify: `frontend/lib/api.js` — account API helpers.
- Modify: `frontend/lib/useAuth.js` — account-session behavior.
- Modify: `frontend/components/public/AuthModal.js` — account login/registration/recovery UX.
- Modify: `frontend/app/(app)/settings/page.js` — password/email/security controls.

---

## Task 1: Establish the account-auth boundary

**Files:** `backend/app/routers/auth.py`, `frontend/lib/api.js`, `frontend/lib/useAuth.js`, `backend/tests/test_auth_account_flows.py`

- [ ] Write a failing test for `POST /auth/account/login` proving it authenticates a StrikeNova `User` with `verify_password()` and never invokes the broker gateway.
- [ ] Write a regression test proving `GET /auth/login?broker=UPSTOX` remains the broker OAuth initiation route.
- [ ] Run `pytest tests/test_auth_account_flows.py -k "account_login or broker_oauth" -v` and confirm the new account-login test fails before implementation.
- [ ] Implement `POST /auth/account/login` using the durable `UserSession` flow and the existing secure cookie policy.
- [ ] Implement `POST /auth/account/logout`, `POST /auth/account/logout-all`, and `GET /auth/account/session` using `UserSession.revoked_at` and `expires_at` as the authority.
- [ ] Add explicit frontend helpers `loginAccount`, `logoutAccount`, `logoutAll`, and `getAccountSession`; retain `loginUrl()` for broker OAuth.
- [ ] Run the focused backend tests plus `npm test -- --run` in `frontend`.
- [ ] Commit: `feat(auth): separate account login from broker oauth`.

## Task 2: Add durable security records and token services

**Files:** `backend/app/identity.py`, `backend/alembic/versions/c1d2e3f4a5b6_add_account_security.py`, `backend/app/services/account_security.py`, `backend/tests/test_account_security.py`, `backend/app/config.py`

- [ ] Write failing persistence tests for `EmailVerificationToken`, `PasswordResetToken`, `PendingEmailChange`, and `SecurityEvent`.
- [ ] Test replay prevention: the first consumption succeeds and the second consumption of the same token fails.
- [ ] Test expiry: a token past its configured TTL fails.
- [ ] Test that the database never contains raw verification/reset tokens.
- [ ] Add the four SQLAlchemy models with indexed ownership/expiry fields and immutable security-event records.
- [ ] Add Alembic revision `c1d2e3f4a5b6_add_account_security.py` with the correct `down_revision` for the branch at implementation time; create only the four security tables/required indexes.
- [ ] Implement `create_opaque_token()` using `secrets` and store only a SHA-256 digest.
- [ ] Implement atomic token consumption so a token cannot be replayed under concurrent requests.
- [ ] Add configurable verification TTL, reset TTL, recent-auth TTL, email sender address, and email base URL.
- [ ] Run `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head`, then `pytest tests/test_account_security.py -v`.
- [ ] Commit: `feat(auth): add durable account security records`.

## Task 3: Add email transport and email verification

**Files:** `backend/app/services/email.py`, `backend/app/routers/auth.py`, `frontend/components/public/AuthModal.js`, `frontend/lib/api.js`, `backend/tests/test_auth_account_flows.py`

- [ ] Define `EmailSender.send(to, subject, html, text)` and a deterministic in-memory test sender; do not couple account logic to a provider SDK.
- [ ] Write failing tests for `POST /auth/account/register`, `POST /auth/account/verify-email`, and `POST /auth/account/resend-verification`.
- [ ] Test normalized email storage, unverified-account state, verification email delivery, invalid token, expired token, replay, and resend invalidation.
- [ ] Implement registration with normalized email, password hashing, unverified status, verification-token creation, and email delivery.
- [ ] Do not auto-login immediately after local registration; require verification first.
- [ ] Implement verification-token consumption and account verification.
- [ ] Implement resend by invalidating prior active verification tokens before creating a new one.
- [ ] Update `AuthModal` so successful registration shows a verification-required state and a resend action instead of auto-login.
- [ ] Run `pytest tests/test_auth_account_flows.py -k "register or verify" -v` and frontend tests.
- [ ] Commit: `feat(auth): add email verification flow`.

## Task 4: Add password recovery and sensitive account changes

**Files:** `backend/app/services/account_security.py`, `backend/app/routers/auth.py`, `frontend/components/public/AuthModal.js`, `frontend/app/(app)/settings/page.js`, `frontend/lib/api.js`, `backend/tests/test_auth_account_flows.py`

- [ ] Write a failing enumeration test proving `POST /auth/account/forgot-password` returns the same status/body for known and unknown email addresses.
- [ ] Write tests for invalid, expired and replayed reset tokens; valid reset; session revocation after reset; and no authenticated session returned by reset.
- [ ] Implement `POST /auth/account/forgot-password` with a generic response and a short-lived reset email for eligible local-password accounts.
- [ ] Implement `POST /auth/account/reset-password` with atomic token consumption, password update, session revocation, security event, and notification email.
- [ ] Add recent-authentication storage tied to `(user_id, session_id)` and enforce its TTL server-side.
- [ ] Implement `POST /auth/account/change-password` requiring authenticated session plus recent authentication; revoke other active sessions after a successful change.
- [ ] Implement `POST /auth/account/change-email` requiring recent authentication; keep the current email unchanged until the new address is verified.
- [ ] Add the corresponding AuthModal recovery states and Settings controls. Passwords/tokens remain only in transient component state.
- [ ] Run focused backend and frontend tests.
- [ ] Commit: `feat(auth): add recovery and sensitive account changes`.

## Task 5: Add abuse controls and security audit events

**Files:** `backend/app/services/account_security.py`, `backend/app/routers/auth.py`, `backend/app/config.py`, `backend/tests/test_account_security.py`, `backend/tests/test_auth_account_flows.py`

- [ ] Write failing rate-limit tests for login, registration, verification resend, password recovery, reset, and sensitive account changes.
- [ ] Use deterministic time in tests; do not use sleep-based tests.
- [ ] Implement bounded rate limiting with keys scoped to the operation, such as `email + IP` for login/recovery and `user + IP` for account changes.
- [ ] Keep the limiter behind a small interface so a future Redis implementation can replace the current store without changing endpoint contracts.
- [ ] Emit safe `SecurityEvent` rows for registration, login success/failure, verification, recovery request/completion, password/email changes, logout, logout-all, session revocation, and recent authentication.
- [ ] Write tests proving raw passwords, raw tokens, reset URLs, broker credentials, access tokens, refresh tokens and OAuth codes never appear in security events or application logs.
- [ ] Run `pytest tests/test_account_security.py tests/test_auth_account_flows.py -v`.
- [ ] Commit: `feat(auth): add abuse controls and security events`.

## Task 6: Full regression, migration, and frontend verification

**Files:** existing tests plus any narrowly scoped regression tests required by verification.

- [ ] Run `pytest -q` in `backend`.
- [ ] Run `npm test -- --run` and `npm run build` in `frontend`.
- [ ] Run the repository-standard fresh-database migration verification and confirm the existing `users`, `user_sessions`, broker connection/authorization records and the four new security tables coexist.
- [ ] Exercise the existing broker OAuth kickoff/callback flow and confirm signed-state binding, popup behavior and BYOB credential resolution remain unchanged.
- [ ] Search captured logs/API responses/security-event payloads for forbidden secret material and treat any unexpected occurrence as a blocking defect.
- [ ] Verify no public-page design tokens, CTA behavior, spacing system, or the removed anatomical hover behavior changed as a side effect.
- [ ] Run the final complete test/build suite again after any verification fix.
- [ ] Commit only verified regression fixes with message `test(auth): verify account security regression coverage`.

## Completion Criteria

- [ ] StrikeNova account login is independent from broker OAuth.
- [ ] Registration requires verified email for local password accounts.
- [ ] Email verification and password-reset tokens are hashed, expiry-bound, single-use and replay-safe.
- [ ] Password recovery is enumeration-resistant.
- [ ] Password reset revokes existing sessions.
- [ ] Password/email changes require recent authentication.
- [ ] Logout and logout-all operate on durable sessions.
- [ ] Rate limiting protects account-sensitive endpoints.
- [ ] Security events are durable and contain no secret material.
- [ ] Email delivery is provider-abstracted and provider credentials remain server-side.
- [ ] Existing broker OAuth/BYOB flows pass regression tests.
- [ ] Backend tests, frontend tests, and production build pass.
- [ ] Public marketing-page behavior remains unchanged.
