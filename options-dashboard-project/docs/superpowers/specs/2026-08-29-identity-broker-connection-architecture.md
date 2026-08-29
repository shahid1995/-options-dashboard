# StrikeNova Identity + Broker Connection Architecture

**Date:** 2026-08-29  
**Status:** Approved architecture — implementation follows in separate plans  
**Scope:** Platform identity and broker-connection boundaries only

## Goal

Establish a durable architecture in which a user's StrikeNova account is independent from broker authentication, market-data authorization, and trading authorization.

## Core Rule

These are three independent broker capabilities and MUST NOT be coupled:

1. Broker Login / Authentication — establishes broker identity/session.
2. Live Market Data — authorizes quotes, option-chain/OI/Greeks, historical data, and WebSocket data.
3. Order Execution / Trading — authorizes place/modify/cancel orders and trading account operations.

A fourth concept exists above them: **StrikeNova Platform Identity**. Google/email authentication belongs to StrikeNova, not to any broker.

## Identity Model

```text
StrikeNova User
├── Platform identities
│   ├── email/password
│   └── Google OAuth (future providers may be added)
│
└── Broker connections[]
    ├── broker identity/auth capability
    ├── market-data capability
    └── trading capability
```

A user MUST be able to create and use a StrikeNova account without connecting a broker.

A broker connection MUST belong to a StrikeNova user and MUST NOT become the user's primary platform identity merely because OAuth was used.

## Platform Authentication

### Email/password

Registration and login authenticate the StrikeNova account only. They do not create broker authorization.

### Google

Google OAuth authenticates the StrikeNova account only:

```text
Browser → Google OAuth → verified Google identity → StrikeNova user → StrikeNova session
```

The Google flow MUST NOT receive, store, or require broker API credentials.

The implementation should use an established OAuth/OIDC library or well-tested protocol implementation rather than hand-rolling token validation.

## Broker Connection Model

A broker connection represents a user's relationship with one broker account/provider. Multiple connections are allowed per StrikeNova user.

Conceptually:

```text
BrokerConnection
├── provider
├── broker_account_id (nullable until known)
├── authentication status
├── market-data status
├── trading status
├── encrypted user credentials/tokens
└── broker-specific metadata
```

Do not use a single `capability_mode` as the source of truth for all three capabilities.

## Capability Independence

### Authentication capability

Represents broker identity/session. Typical credential: broker OAuth access token or broker-specific session credential.

### Market-data capability

Represents authorization to consume market data. Upstox Analytics Token is a special data-only credential and MUST be supported without requiring broker OAuth login.

For Upstox, preferred data-token resolution is:

1. user Analytics Token
2. valid user OAuth access token, if available and permitted
3. no data authorization

The system MUST NOT infer trading authorization from possession of an Analytics Token.

### Trading capability

Represents authorization to submit trading operations. It MUST have its own explicit status and broker-specific prerequisites such as static-IP requirements.

Market-data authorization MUST NOT automatically enable trading.

## Upstox Data-Only Flow

```text
StrikeNova account
      ↓
Settings → Connect Live Market Data
      ↓
Select Upstox
      ↓
User supplies Analytics Token
      ↓
Encrypt + store against that user's broker connection
      ↓
Market-data services use that token
```

This flow MUST NOT initiate Upstox OAuth and MUST NOT require `UPSTOX_API_KEY`, `UPSTOX_API_SECRET`, or trading authorization merely to consume market data.

## Broker Login Flow

```text
StrikeNova account
      ↓
Settings → Connect Broker
      ↓
Select broker
      ↓
broker OAuth/session flow
      ↓
broker account identity established
      ↓
authentication capability = active
```

The OAuth callback MUST be bound to the initiating StrikeNova session/user and MUST NOT create an unrelated platform identity accidentally.

## Trading Flow

```text
StrikeNova account
      ↓
Broker authentication available
      ↓
Enable Trading
      ↓
Validate broker-specific trading prerequisites
      ↓
Trading capability = active
```

Order execution is explicitly OUT OF SCOPE for the identity implementation and must not be introduced as a side effect.

## Database Direction

The existing `users` table remains the StrikeNova identity record.

Platform authentication records should be extensible so Google and email/password can coexist without creating duplicate users.

Broker credentials remain encrypted and scoped to the owning `BrokerConnection`.

Broker capability status should be represented independently. The existing `capability_mode` field should not remain the long-term authority for capability decisions.

Before changing schema, inspect the current migration/bootstrap mechanism and preserve compatibility with existing users and connections.

## Security Requirements

- Never store Google client secrets or broker secrets in frontend code.
- Never expose broker access tokens to browser JavaScript unless the broker protocol explicitly requires it and the security model has been reviewed.
- Encrypt broker credentials/tokens at rest.
- Bind OAuth state to the initiating StrikeNova session/user.
- Prevent OAuth login from silently replacing an existing StrikeNova identity.
- Prevent one user's broker credential from being selected for another user.
- Do not place user broker credentials in shared Railway environment variables.
- Platform-level broker application credentials, if required by a broker OAuth application, are configuration for the application—not user credentials—and must never be used as a substitute for per-user authorization.

## UX Requirements

Public pages:

- `Log in` / `Get Started` open StrikeNova authentication.
- Google and email/password are platform authentication choices.
- Broker OAuth is not the default public login mechanism.

Authenticated Settings should expose three clearly separated sections:

1. StrikeNova Account
2. Market Data Connections
3. Broker Login / Trading Connections

Example:

```text
StrikeNova Account
  Google                    Connected ✓

Market Data
  Upstox — Analytics Token  Connected ✓

Broker Login
  Upstox — OAuth             Not connected

Trading
  Upstox                     Not enabled
```

## Explicit Non-Goals

- No order-placement implementation.
- No new broker adapter implementation as part of this architecture work.
- No automatic Railway/Vercel deployment.
- No storing shared user credentials in Railway environment variables.
- No assumption that one broker token grants all capabilities.
- No forced broker connection during StrikeNova registration.

## Implementation Order

1. Stabilize StrikeNova platform identity/session model.
2. Add Google authentication alongside email/password.
3. Ensure protected routes use StrikeNova sessions, not broker sessions.
4. Refactor broker connection representation so auth/data/trading are independent.
5. Implement Upstox Analytics Token data-only connection.
6. Verify per-user token authorization boundaries.
7. Only then proceed with additional broker authentication adapters.
8. Trading remains a later, separate capability project.

## Acceptance Criteria

- A user can register/login to StrikeNova with email/password without any broker.
- A user can sign in with Google without any broker.
- A Google-authenticated user can later connect Upstox independently.
- A user can connect an Upstox Analytics Token without completing broker OAuth.
- An Analytics Token connection cannot place orders.
- Broker OAuth can establish broker authentication without automatically enabling trading.
- Trading status is independent from market-data status.
- Multiple broker connections can coexist under one StrikeNova user.
- Existing authenticated users are not silently duplicated when Google/email identity is added.
- No user broker secret is required in Railway environment variables for data-only operation.
- All tests and build checks pass before implementation is considered complete.
