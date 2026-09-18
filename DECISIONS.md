# StrikeNova — Decision Records

**Status:** Canonical · **Owner:** Founder · **Last reviewed:** 2026-09-18

Durable reasoning and full context live in the **Obsidian Second Brain**
(knowledge authority). This file mirrors the **engineering effect** of accepted
decisions so agents can honor them from inside the repository. When a decision
changes, it changes through the governance process — not by silent edits.

Format: **ADR-NNN · Title · Status · Evidence**.

---

## ADR-001 · Authority hierarchy and single governance system · Accepted

Founder (final) · Obsidian (knowledge/context) · GitHub (implementation/
project) · Hermes/FreeBuff (execution). Exactly one governance layer: the
canonical control-document set at the repository root. Evidence:
[`PROJECT-CONTROL.md`](PROJECT-CONTROL.md).

## ADR-002 · Alembic is the sole schema authority · Accepted

All schema changes flow through Alembic migrations. Application code and tests
never issue ad-hoc DDL. Existing migrations are never edited to satisfy tests;
new migrations require independent evidence of a schema-contract gap. Evidence:
`docs/PHASE_10_1A_DATABASE_MIGRATIONS.md`, `backend/alembic/`,
`backend/tests/test_day5_alembic_authority.py`.

## ADR-003 · Database portability with CockroachDB production target · Accepted

The backend stays portable: SQLite for local development, PostgreSQL-compatible
CI (service container), CockroachDB validated as the production runtime
(dialect `cockroachdb+psycopg`). Production deploys target CockroachDB Cloud.
Evidence: `docs/architecture/COCKROACH_RUNTIME_VALIDATION.md`,
`docs/architecture/COCKROACH_LIVE_COMPATIBILITY_VALIDATION.md`,
`backend/tests/test_cockroachdb_compat.py`, CI `PostgreSQL compatibility`.

## ADR-004 · Railway superseded; production topology is Vercel/Render/CockroachDB · Accepted

Railway was an early staging experiment (see `docs/RAILWAY_INFRASTRUCTURE_AUDIT.md`,
2026-08-31 — historical). Current topology: frontend on **Vercel**, backend on
**Render**, production database on **CockroachDB Cloud**. Evidence:
`docs/architecture/VERCEL_STAGING_DEPLOYMENT.md`,
`docs/architecture/RENDER_STAGING_DEPLOYMENT.md`, `frontend/vercel.json`.

## ADR-005 · BYOB broker architecture · Accepted

Users connect their own broker accounts (Upstox first) through OAuth. Broker
tokens authorize broker API calls only; they never authenticate the StrikeNova
platform. Broker credentials are encrypted at rest and scoped per connection.
Evidence: `docs/BROKER_AUTHORIZATION_ARCHITECTURE.md`,
`docs/PHASE_10_2B_CONNECTION_ARCHITECTURE.md`.

## ADR-006 · Platform identity separate from broker authorization · Accepted

StrikeNova platform identity (email/Google) issues its own durable
`UserSession` records. A valid platform session needs no broker token;
platform-only users authenticate with `access_token = None`. Evidence:
`docs/PHASE_10_2_IDENTITY_HARDENING.md`, `docs/superpowers/specs/2026-09-16-strikenova-auth-account-security-design.md`.

## ADR-007 · Secure browser session transport (cookie-only) · Accepted

The only browser platform-session transport is the HttpOnly `strikenova_session`
cookie. Retired: `session_id` cookie name, `localStorage`/`sessionStorage`
session storage, URL-fragment/query session capture, frontend `X-Session-Id`
injection, WebSocket subprotocol credentials. `X-Session-Id` remains a
server-side compatibility transport for legacy/test clients. Transient (5xx/
network) `/auth/me` failures preserve authenticated UI state with a retryable
error; only 401/403 clear it. Evidence: PR #62 (merged at `aa70629`),
`backend/app/routers/deps.py`, `frontend/lib/session.js`,
`backend/tests/test_secure_session_cookies.py`,
`frontend/lib/session-transport.test.js`, `frontend/lib/useAuth.behavior.test.js`.

## ADR-008 · Signed broker OAuth state · Accepted

Broker OAuth state is HMAC-signed with session binding and a TTL; legacy
unsigned state is rejected. Google id-token flows bind a nonce through the same
signing mechanism. Evidence: `docs/PHASE_10_2B_3` line of work,
`backend/app/services/token_store.py` (`create_oauth_state`,
`consume_oauth_state`, Google nonce binding), `backend/tests/test_day3_security.py`.

## ADR-009 · Server-authoritative paper trading · Accepted

Paper-trading equity, positions, exits, and P&L are computed and persisted
server-side; the client is a renderer. GEX conventions (sign, flip/wall,
aggregation) are owned by `docs/GEX_V1_0_SPEC.md`. Evidence:
`backend/app/services/paper_execution.py`, `docs/GEX_V1_0_SPEC.md`.

## ADR-010 · Historical engineering record is evidence, not open work · Accepted

`options-dashboard-project/docs/` documents completed phases. They are not
recreated as open issues unless an issue explicitly reopens or supersedes the
work. The current status snapshot is
`docs/superpowers/STRIKENOVA_IMPLEMENTATION_STATUS.md`. Evidence:
[`PROJECT-CONTROL.md`](PROJECT-CONTROL.md) §Existing project history.

## ADR-011 · Phase 10.2 account security — standing status record · Accepted

The approved Phase 10.2 design and execution plan
(`docs/superpowers/specs/2026-09-16-strikenova-auth-account-security-design.md`,
`docs/superpowers/plans/2026-09-16-strikenova-auth-account-security-execution-plan.md`)
is **not uniformly complete**. Standing status:

| Workstream | Status |
|---|---|
| Identity/session hardening | Completed |
| Token/OAuth-state work | Completed |
| Account-auth implementation | Substantially implemented |
| Secure browser session transport | Completed by PR #62 (Issue #61) |
| Transactional email provider integration | **Implemented in code (Brevo adapter, Issue #65); real delivery not yet verified** |
| Real mailbox/email-delivery verification | Pending |
| Final end-to-end Phase 10.2 release/security gate | Pending |

Evidence: account-auth route surface (`/auth/account/*` in
`backend/app/routers/auth.py`), security record models and services
(`backend/app/services/account_security.py`, `app/identity.py`), provider-neutral
`EmailSender` boundary with the explicit `EMAIL_PROVIDER` selection and the
Brevo adapter behind it (`backend/app/services/email.py` —
`BrevoEmailSender`, `api-key` header, Brevo `smtp/email` payload; default
remains the deterministic in-memory test sender), secure-transport regressions
(`backend/tests/test_secure_session_cookies.py`,
`frontend/lib/useAuth.behavior.test.js`). Real mailbox/email-delivery
verification and the final Phase 10.2 release/security gate remain pending —
until both pass, no document may describe Phase 10.2 account security as
fully complete.
