# StrikeNova — Upstox Identity Linking Implementation

Date: 2026-09-14
Design authority: `docs/architecture/UPSTOX_IDENTITY_LINKING_DESIGN.md` (commit `e897ce4`), §17 acceptance contract
Branch: `feat/strikenova-day35-portfolio-intelligence`
Status: **IMPLEMENTED — STAGING VALIDATION PENDING**

No secrets appear in this document: no API keys, access tokens, refresh
tokens, encryption keys, session identifiers, or user identifiers beyond
synthetic test values.

---

## 1. Root cause

The staging Upstox OAuth callback (`GET /auth/callback`) provisioned the
platform identity via `get_or_create_user_from_upstox()`, which looked up
users only by `(broker_provider, broker_user_id)` and, on first sight of a
broker identity, INSERTed a brand-new `User` carrying the Upstox profile
email. When that email already belonged to an existing platform account,
the insert collided with the `users.email` unique index:

```text
Upstox callback
→ get_or_create_user_from_upstox()
→ duplicate User INSERT
→ users.email UniqueViolation
→ rollback, token discarded
→ ?login_error=account_setup_failed
```

The collision was only the visible symptom: the deeper defect was that the
callback created a second platform user at all, despite the OAuth state
already binding the authenticated StrikeNova session that initiated the
connection. This forked one human into two StrikeNova accounts.

## 2. Implementation (Option A — session-bound broker linking)

All changes are confined to the backend identity/auth path plus tests:

* `backend/app/identity.py`
  * `BrokerIdentityInUse` — ownership-conflict exception.
  * `resolve_platform_user()` — resolves the user ONLY from the state-bound
    session's `user_id`; never creates a User; never consults broker
    profile data.
  * `find_broker_identity_owner()` — checks `broker_connections` and the
    legacy `users.broker_*` stamp; conflicting records raise rather than
    silently resolve.
  * `ensure_broker_stamp()` — stamps legacy columns only when NULL or
    identical; any different existing stamp raises `BrokerIdentityInUse`.
  * `get_or_create_connection()` — upsert inside a SAVEPOINT
    (`begin_nested`) with a bounded re-read/retry recover path: same-user
    conflict → deterministic idempotent reconnect; other-user winner →
    `BrokerIdentityInUse` (design §11/§17.3).
  * `get_or_create_user_from_upstox()` retired to lookup-only (kept solely
    for the separate legacy Upstox-only migration workstream).
* `backend/app/routers/auth.py`
  * Callback resolves the user exclusively from the bound session
    (`session.user_id`), uses `profile.data.user_id` as the authoritative
    Upstox identity (§17.2/§17.5), performs ownership arbitration, and
    persists ONE transaction via `_persist_broker_link()`.
  * Profile email/display name are stored as informational metadata in
    `provider_metadata_json` on the connection — never on `users.email`,
    never compared for authorization.
  * `IntegrityError` handler classifies by re-reading the committed winner:
    other-user → `broker_identity_in_use`; same-user → one deterministic
    retry of the link transaction.
  * In-memory broker token cache is populated only after commit (§10
    Phase 2). The old "non-critical" token-persist warning no longer exists
    in this flow.
* `backend/app/services/token_store.py`
  * New session-scoped API: `prepare_broker_session()` (reserve id, memory
    untouched) → `persist_broker_token_row()` (encrypted BrokerToken row on
    the CALLER's transaction; failures propagate and roll everything back)
    → `cache_broker_session()` (post-commit, idempotent).
  * `set_token()` gains `persist_to_db` (already present upstream) — used by
    tests for initiator sessions only; the callback path uses the three-step
    API.

## 3. Tests

Focused suite `backend/tests/test_identity_linking.py` — **17 passed, 0
failed** — covers the design's acceptance contract:

| Design case | Test |
|---|---|
| A — existing-email collision, same user preserved | `test_callback_links_identity_to_session_user_when_emails_match` |
| B — email mismatch allowed, `users.email` untouched | `test_email_mismatch_is_allowed` |
| C — Upstox email = another user's email is NOT authority | `test_email_collision_with_another_user_is_not_authority` |
| D — broker identity owned by another user | `test_broker_identity_owned_by_other_user_is_rejected` |
| E — same-user reconnect idempotent | `test_same_user_reconnect_is_idempotent`, `test_same_legacy_stamp_is_a_noop` |
| F/G — cross-user + same-user races | `test_cross_user_race_loser_surfaces_broker_identity_in_use`, `test_same_user_race_recovers_via_reread` |
| H — forced rollback after connection creation | `test_forced_db_failure_after_connection_rolls_back_everything` |
| atomic token persistence | `test_token_persisted_in_main_transaction` |
| state validation | forged / replayed / expired state tests |
| pending-sentinel preservation | `test_global_partial_index_blocks_cross_user_duplicate_and_allows_pending` |
| invariant sweep (never creates users) | `test_callback_never_creates_users_any_scenario` |

Regression suites run (all green except one pre-existing failure unrelated
to this change): identity foundation/hardening, Phase 10.2A, BYOB
credentials, broker-connection model, auth router, Day 3 security, Day 7
session persistence, platform-session separation, token store/persistence,
Google auth, Day 39 identity, hardening final/v3, migration hardening,
CockroachDB compatibility unit tests, Alembic + broker-connection migration
suites. Two legacy tests were updated to the authorized semantics
(`test_identity_foundation.py` — lookup-only `get_or_create_user_from_upstox`;
`test_auth_router.py` / `test_day3_security.py` — committed setup rows and
identity-consistent fixture stamps per §10 Phase 0 ordering).

Known pre-existing failure (unchanged by this work, proven failing at clean
HEAD in a throwaway worktree):
`test_phase10_2a_identity.py::TestTokenStoreIntegration::test_session_record_but_no_token_raises_401`
encodes the superseded "token required → 401" contract, while the platform
session workstream deliberately returns `access_token=None` for valid
platform sessions. Also pre-existing at HEAD:
`test_token_persistence.py::TestSignedOAuthState::test_dot_in_unsigned_state_not_created`
(Day 3 already rejected unsigned states; the test predates that change).

## 4. Transaction boundary (§10 / §17.4)

```text
Phase 0 — no local transaction
  consume signed state (single-use, 10 min TTL)
  re-validate initiating session (DB)
  resolve BYOB credentials
  EXTERNAL: exchange_authorization_code
  EXTERNAL: get_profile

Phase 1 — ONE transaction (single SessionLocal)
  resolve user = session.user_id          (SELECT only)
  ownership pre-checks                    (SELECT only)
  stamp users.broker_* when NULL          (rare UPDATE)
  upsert BrokerConnection                 (SAVEPOINT-guarded)
  INSERT user_sessions (new broker session)
  INSERT broker_tokens (SAME transaction)
  COMMIT

Phase 2 — post-commit, idempotent
  cache_broker_session (in-memory)
  redirect /dashboard#session_id=…
```

A failure anywhere in Phase 1 rolls back connection, session, token, and
stamp together — proven by `test_forced_db_failure_after_connection_rolls_
back_everything` (zero new rows in every table). No token value is ever
printed; logs carry at most an 8-character session-id prefix (existing repo
convention, pre-dating this change).

## 5. Migration

`alembic/versions/d9e0f1a2b3c4_uq_broker_identity_global.py` (single
revision, on top of Day41.2 head `e2b4c6d8f0a1`):

```sql
CREATE UNIQUE INDEX uq_broker_identity_global
ON broker_connections (broker, broker_account_id)
WHERE broker_account_id <> 'pending';
```

* Pre-creation duplicate-ownership audit (2026-09-14, local dev DB):
  zero `(broker, broker_account_id)` groups with more than one distinct
  owner among live rows (1 live connection, 0 pending). Migration proceeds;
  no data was modified or reassigned.
* Where-clause uses `sqlalchemy.text()` — on SQLAlchemy 2.0.52 a raw string
  fails to compile for partial indexes (verified; matches the
  `c7d3e5f8a9b2` google-sub index convention).
* Dialect dispatch: PostgreSQL / CockroachDB / SQLite partial-index forms;
  the created DDL matches the design SQL exactly on both engines tested.

## 6. Verification results

### SQLite (disposable file DB)
`alembic upgrade head` from empty → OK; idempotent re-upgrade → OK;
`downgrade -1` + re-upgrade → OK; index DDL verified in `sqlite_master`.

Existing migration suites: `test_alembic_migrations.py` +
`test_broker_connection_migration.py` — 10/10 passed.

### PostgreSQL (real server, localhost:5432, disposable `striketest` DB)
Full migration chain from empty → OK; index present:
`CREATE UNIQUE INDEX uq_broker_identity_global ON public.broker_connections
USING btree (broker, broker_account_id) WHERE ((broker_account_id)::text <>
'pending'::text)`.

Behavior: cross-user duplicate INSERT statically rejected (`IntegrityError`);
pending sentinel rows preserved (2/2). Concurrency: barrier-synchronized
two-thread race on the same broker identity from two different users —
exactly one COMMIT, one `IntegrityError` rejection, exactly one owner row.
The test database was restored to pristine (all dropped) afterwards.

### CockroachDB
A live CRDB server was not available in this environment (no `cockroach`
binary, no Docker daemon, port 26257 unreachable). Evidence for CRDB comes
from (a) the PostgreSQL partial-index result — CRDB ≥ 22.2 implements the
same partial-index semantics, (b) the migration's `cockroachdb_where`
dispatch mirroring the previously CRDB-validated `c7d3e5f8a9b2` pattern, and
(c) the green `test_cockroachdb_compat.py` unit suite. **Live CRDB migration
verification remains an open item**, to be executed against the Northflank
staging CRDB instance during the staging validation pass.

## 7. Staging result

NOT YET EXECUTED in this change set. Staging endpoints answered during
development (API `/auth/status` → `{"logged_in": false}`, frontend HTTP
200). The live flow — authenticated StrikeNova user → Connect Upstox →
consent → callback → exchange → profile → same existing user →
BrokerConnection + BrokerToken + UserSession in one commit — must be
re-run on the deployed staging build to prove the original
`users.email UniqueViolation` failure is gone. The suite above already
proves the mechanism; the staging pass proves the deployment.

## 8. Remaining limitations

1. **CRDB live migration verification** — pending (see §6).
2. **Live staging re-run** — pending manual deployment; auto-deploy must
   remain OFF for Render and Vercel.
3. `get_or_create_user_from_upstox()` remains as a lookup-only shim for the
   separate legacy Upstox-only sign-in migration workstream; it must not be
   reintroduced into the callback.
4. The in-memory OAuth state map is process-local (deliberate, pre-existing):
   a restart during an OAuth redirect fails that attempt closed; the user
   retries. No persistence was added — unchanged behavior.
5. The pre-existing phase10 401-contract test failure (§3) is tracked
   separately with the platform-session workstream; it is not touched here.
6. Optional hardening from design §10 (best-effort revocation of the
   orphaned Upstox token after a Phase-1 failure) remains unimplemented —
   the token is simply dropped, which is safe (nothing persisted).
