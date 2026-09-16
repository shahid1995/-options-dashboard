# StrikeNova Auth & Account Security — Design Specification

**Date:** 2026-09-16
**Status:** APPROVED DESIGN
**Repository:** `shahid1995/-options-dashboard`
**Branch:** `feat/strikenova-day35-portfolio-intelligence`

## 1. Purpose

Establish a durable StrikeNova-owned identity and account-security subsystem covering email verification, password recovery, password changes, email changes, session security, rate limiting, security events, and recent-authentication. Third-party services are limited to infrastructure that is inherently external, principally transactional email delivery and broker/payment providers.

## 2. Existing foundation

The current branch already contains a `User` identity model, password hashing/verification, `UserSession`, broker connection/authorization separation, and encrypted broker credential/token handling. The existing broker OAuth flow remains outside the account-security subsystem.

## 3. Architectural boundary

```text
StrikeNova Identity
├── Registration
├── Login / Logout
├── Email verification
├── Password recovery
├── Password change
├── Email change
├── Sessions / revocation
├── Recent authentication
├── Security events
└── Account lifecycle

Broker Authorization
├── Broker connections
├── OAuth
├── Broker tokens
├── Data capability
└── Trading capability
```

Identity does not own broker credentials, broker OAuth state, market data, or trading execution. Broker authorization remains attached to `BrokerConnection` and is not a substitute for StrikeNova account identity.

## 4. First-party vs third-party ownership

### StrikeNova-owned

- User records and account status.
- Password hashing and verification using the existing proven library/implementation boundary.
- Verification and password-reset token generation, hashing, expiry, single-use consumption, and revocation.
- Session creation, expiry, revocation, and logout-all.
- Enumeration-resistant responses.
- Login/recovery/change-action rate limits.
- Security-event persistence.
- Recent-authentication state.
- TOTP MFA and recovery codes in a later phase.
- Account deletion/data export policy and workflow in a later phase.

### External

- Transactional email transport/delivery only; StrikeNova owns all verification/reset semantics and token handling.
- Broker OAuth/API/data/order execution through the selected brokers.
- Payment processing when subscriptions are introduced.
- Optional social identity providers such as Google in a later phase.

Running a general-purpose mail server is explicitly out of scope.

## 5. Security data model

Add dedicated durable records for:

### EmailVerificationToken

- `id`
- `user_id`
- `token_hash`
- `expires_at`
- `used_at`
- `created_at`

Properties: random high-entropy token; only the hash is stored; single-use; bounded TTL; old active tokens invalidated when a new verification is requested.

### PasswordResetToken

Same storage rules as verification tokens. Successful consumption must invalidate the token and revoke all existing user sessions before issuing a new authenticated session.

### PendingEmailChange

- `id`
- `user_id`
- `new_email`
- `token_hash`
- `expires_at`
- `used_at`
- `created_at`

The current email remains authoritative until the new address is successfully verified.

### SecurityEvent

- `id`
- `user_id` nullable for anonymous events
- `event_type`
- `occurred_at`
- `ip_hash` or privacy-preserving source identifier where retention is justified
- `user_agent_hash` or bounded metadata
- `session_id` nullable
- structured metadata JSON without passwords, tokens, broker secrets, authorization codes, or reset links

Initial event types include registration, login success/failure, logout, logout-all, email verification requested/completed, password reset requested/completed/failed, password changed, email change requested/completed, session revoked, and recent-authentication completed.

## 6. Account flows

### Registration

1. Normalize and validate email.
2. Enforce password requirements.
3. Create account in an unverified state unless the existing product identity flow requires another explicit status.
4. Create a verification token.
5. Send verification email through the configured email transport.
6. Do not create a privileged authenticated session until policy allows it.

Registration responses must not expose unnecessary account-existence information.

### Email verification

- Link contains a one-time opaque token.
- Backend hashes the presented token and looks up the active record.
- Expired/used tokens fail closed.
- Successful verification marks the account verified and emits a security event.
- Resend invalidates prior active verification tokens.

### Forgot password

`POST /auth/forgot-password` always returns a generic response regardless of whether the email exists. Existing tokens are replaced by a new token. The email contains a short-lived HTTPS reset link.

### Reset password

The reset endpoint accepts only the opaque reset token and a valid new password. Successful reset atomically marks the token consumed, updates the password hash, revokes all existing sessions, emits a security event, and sends a security notification.

### Change password

Requires an authenticated session and recent authentication. On success, the current session may be retained or rotated according to the session policy, while other active sessions are revoked. The user receives a security notification.

### Change email

Requires recent authentication. The new email is not committed until verification succeeds. The user receives a security notification after successful change.

### Sessions

Use the durable `UserSession` table as the authoritative session record. Session cookies must be Secure, HttpOnly, appropriately SameSite-configured, and bounded by the existing session TTL policy. Support individual revocation and revoke-all.

### Recent authentication

Provide a reusable server-side mechanism for sensitive actions. It must be tied to the authenticated user/session, have a short configurable freshness window, and never be represented as a client-controlled boolean.

## 7. Abuse controls

Apply rate limits independently to:

- login attempts
- registration attempts
- verification resend
- forgot-password requests
- password reset attempts
- email-change requests

Limits should be enforced without creating account-enumeration side channels. A temporary lock or backoff must not permanently disable a user account merely because an attacker targets the address.

## 8. Email transport boundary

Create a small email-service interface, for example:

```python
class EmailSender(Protocol):
    async def send(self, *, to: str, subject: str, html: str, text: str) -> None: ...
```

Authentication flows depend on this interface, not on a vendor SDK. Local/test configuration uses a deterministic test sender or capture sink. Production configuration points the interface at the selected transactional email provider.

No provider credentials belong in the frontend.

## 9. API surface

Initial account-security endpoints:

```text
POST /auth/register
POST /auth/login
POST /auth/logout
POST /auth/logout-all
POST /auth/verify-email
POST /auth/resend-verification
POST /auth/forgot-password
POST /auth/reset-password
POST /auth/change-password
POST /auth/change-email
GET  /auth/session
GET  /auth/security-events
```

Exact naming may follow current router conventions, but the semantic contracts must remain stable. Broker OAuth routes such as `/auth/login` used for broker navigation must be reconciled carefully so StrikeNova account login and broker OAuth initiation do not become ambiguous.

## 10. Frontend requirements

Add dedicated account/security screens for the implemented API flows. Error copy must be generic where enumeration protection is required. Password and recovery forms must never log or persist secrets client-side.

Frontend tests cover:

- registration and verification states
- forgot/reset password states
- change-password and change-email UX
- generic recovery responses
- expired/invalid token handling
- authenticated vs unauthenticated boundaries

## 11. Testing requirements

Backend tests must cover every token lifecycle transition, expiry, replay prevention, concurrent consumption, enumeration protection, rate limits, session revocation, password hashing/verification, and recent-authentication freshness.

Integration tests must cover real DB migrations and end-to-end auth flow behavior.

Frontend tests must cover all account-security states and API error handling.

A security verification pass must confirm that passwords, raw tokens, reset URLs, verification URLs, OAuth codes, and broker secrets never appear in application logs, API responses, diagnostics, or security-event payloads.

## 12. Explicit non-goals for this phase

- Social login.
- Passkeys/WebAuthn.
- SMS OTP.
- Push notifications.
- Self-hosted mail server.
- Subscription billing implementation.
- Live trading activation.
- Broad identity-provider migration.

These can consume the same identity/recent-auth/security-event foundation later.

## 13. Completion criteria

The phase is complete when a new user can register, verify email, log in, request and complete password recovery, change password/email through protected flows, revoke sessions, and receive security notifications; when all token lifecycles are single-use and expiry-bound; when account enumeration is protected; when security events are durable and secret-free; and when broker OAuth remains isolated from StrikeNova account identity.
