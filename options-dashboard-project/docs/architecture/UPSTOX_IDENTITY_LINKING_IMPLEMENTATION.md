# StrikeNova — Upstox Identity Linking Implementation

Date: 2026-09-14
Design authority: `docs/architecture/UPSTOX_IDENTITY_LINKING_DESIGN.md` (commit `e897ce4`), §17 acceptance contract
Branch: `feat/strikenova-day35-portfolio-intelligence`
Status: **IMPLEMENTED + DEPLOYED TO STAGING — LIVE CONSENT FLOW PENDING (requires human Upstox consent)**

Staging validation update (2026-09-14, second pass): the implementation is
deployed to staging (Render `dep-dajtnch5efls73aajifg`, commit `8c47018`)
and every automatable gate passed. The single remaining gate — completing
the real Upstox OAuth consent in a browser — requires the account holder
because Upstox sandbox apps are portal-token based and cannot OAuth at all
(documented in `tests/staging_smoke/test_staging_broker_smoke.py`, audit
decision 2026-09-13). See §7.

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

`alembic/versions/d9e0f1a2b3c4_uq_broker_identity_global.py` — final form
(after two staging-deploy-driven corrections, commits `8e7302f`, `0ecd82c`,
`8c47018`), parented on the committed chain head `5e2a7b9c3f4d`:

```sql
CREATE UNIQUE INDEX uq_broker_identity_global
ON broker_connections (broker, broker_account_id)
WHERE broker_account_id <> 'pending'
  AND broker_account_id <> 'data-only';
```

* Pre-creation duplicate-ownership audit (2026-09-14, local dev DB):
  zero `(broker, broker_account_id)` groups with more than one distinct
  owner among live rows. Migration proceeds; no data was modified or
  reassigned.
* **Correction 1 (dangling parent).** The first version was parented on the
  parallel session's *untracked* Day41.2 file (`e2b4c6d8f0a1`), so the
  committed tree had no such revision and Alembic could not build the
  revision map on a clean checkout — staging deploy `f461125` failed at
  startup with `KeyError: 'e2b4c6d8f0a1'`. Re-parented onto the committed
  head `5e2a7b9c3f4d` (commit `8e7302f`).
* **Correction 2 (`data-only` sentinel).** Staging CRDB legitimately holds
  multiple `('UPSTOX', 'data-only')` rows — `data-only` is the BYOB
  analytics-token per-user sentinel (see `store_analytics_token`), not a
  real broker account id — and the deploy of `0ecd82c` failed with
  `UniqueViolation` on that key. The design predicate excluded only
  `pending`; both sentinels are now excluded (commit `0ecd82c`). Live
  `(broker, broker_account_id)` identities remain globally unique.
* **Correction 3 (dialect predicate loss).** The dialect-dispatch form
  (`postgresql_where` / `cockroachdb_where` kwargs) silently dropped the
  WHERE clause on Render's `cockroachdb+psycopg` stack — the index was
  created as a FULL unique index and the backfill hit the sentinel
  collision above. The migration now executes the design SQL verbatim via
  `op.execute()` (valid on PostgreSQL, CockroachDB ≥ 22.2, SQLite); commit
  `8c47018`. Lesson recorded: never rely on dialect kwargs for partial
  indexes on CRDB.
* Where-clauses inside the test-predicate mirror use `sqlalchemy.text()` —
  on SQLAlchemy 2.0.52 a raw string fails to compile (matches the
  `c7d3e5f8a9b2` google-sub index convention).

## 6. Verification results

### SQLite (disposable file DB)
`alembic upgrade head` from empty → OK; idempotent re-upgrade → OK;
`downgrade -1` + re-upgrade → OK; index DDL verified in `sqlite_master`.

Existing migration suites: `test_alembic_migrations.py` +
`test_broker_connection_migration.py` — 10/10 passed.

### PostgreSQL (real server, localhost:5432, disposable `striketest` DB)
Re-verified at the deployed commit `8c47018`: full migration chain from
empty → OK; stored index DDL retains the partial predicate with both
sentinels excluded (`WHERE ((broker_account_id)::text <> 'pending'::text)
AND ((broker_account_id)::text <> 'data-only'::text)`).

Behavior: cross-user duplicate INSERT statically rejected (`IntegrityError`);
pending + `data-only` sentinel rows preserved across two users (4/4).
Concurrency: barrier-synchronized two-thread race on the same broker
identity from two different users — exactly one COMMIT, one
`IntegrityError` rejection, exactly one owner row. The test database was
restored to pristine (all dropped) afterwards.

### CockroachDB (live staging cluster — authoritative check)
No local CRDB server exists (no binary, no Docker), so the authoritative
check ran against the **live staging CockroachDB Cloud cluster**
(`strikenova-staging`, db `strikenova_staging`) via the application itself:

* Deploy `8c47018` (`dep-dajtnch5efls73aajifg`): application startup
  executes Alembic `upgrade head` — `Waiting for application startup`
  (11:35:15Z) → `Application startup complete` (11:35:26Z), no errors,
  service `live`, `/health` 200. Startup succeeding **while the cluster
  holds ≥ 2 pre-existing `('UPSTOX','data-only')` rows** is only possible if
  the partial predicate (both sentinels excluded) survived on CRDB — under
  the earlier full-index DDL the same state caused a hard `UniqueViolation`
  failure (`dep-dajti367bikc73df4ngg`). This is the live-CRDB proof that
  the `op.execute()` verbatim DDL takes effect on the
  `cockroachdb+psycopg` stack.
* Direct `alembic_version`/`pg_indexes` inspection was not possible (CRDB
  credentials deliberately not stored in the repo or local env; Render
  one-off jobs and SSH are blocked on the free web-service plan).
* Postgres parity: the same commit's stored DDL was verified byte-for-byte
  on a local PostgreSQL 16 disposable DB, including the threaded race:
  exactly one COMMIT, one `IntegrityError`, one owner row (DB restored
  pristine afterwards).

## 7. Staging result (2026-09-14 validation pass)

**Deployments (manual only; production untouched):**

| Artifact | Identifier | Commit | Result |
| --- | --- | --- | --- |
| Render backend `strikenova-api-staging` | `dep-dajtnch5efls73aajifg` | `8c47018` | **live**, `/health` 200 |
| Vercel frontend `strikenova-frontend-staging` | `dpl_BrC1mqHpzaYvFXcWXLvH8mUbJtHY` | `f461125` | Ready, aliased |

(Failed deploys `dep-dajt61ek1f9s739be460` / `dep-dajteaeq1p3s739g9i1g` /
`dep-dajti367bikc73df4ngg` are the three root-cause iterations documented
in §5; staging was served by the prior release throughout — no outage.)

**Automated live checks (all green):**

* Smoke suite `STAGING_SMOKE=1`: **14 passed, 11 skipped, 0 failed** —
  register→login→masked session→`/auth/me` identity→logout→401 cycle,
  `/paper/capital` on the live CRDB path, CORS allow-list enforcement
  (staging origin allowed, foreign origin rejected), WebSocket handshake
  (both subprotocol variants), Google state endpoint.
* Broker smoke `STAGING_BROKER_SMOKE=1`: **8 passed, 0 failed** — OAuth
  initiation requires an authenticated session (401 anonymous), connect
  requires BYOB credentials (400), graceful no-broker contract,
  `data-only` analytics-token lifecycle **against live CRDB** (exercises
  the sentinel rows the ownership index must tolerate), token value never
  in any response, two-user isolation.
* CRDB-probe smoke (needs a direct staging DSN): skipped — credential
  policy, documented above.
* Live callback hardening: `GET /auth/callback` with forged and with
  unsigned states → `400 Invalid or expired OAuth state` before any
  exchange, linking, or persistence.
* `users.email UniqueViolation`: the original failure occurred during
  callback processing; the callback path now provably never INSERTs a
  `User` (unit suite Test A–H + `test_callback_never_creates_users`), and
  the deployed build starts and serves on the same cluster that triggered
  the original error. The consent-completed callback itself is the one
  step not yet executed live (below).

**Not yet executable without the account holder:**

* Phases 6–8 of the validation plan (real Upstox OAuth consent →
  exchange → profile → same existing user preserved →
  BrokerConnection/UserSession/BrokerToken row check → profile / funds /
  market-data paths with real broker data). Upstox **sandbox** apps are
  portal-token based and cannot OAuth (repo audit decision, 2026-09-13),
  so this requires a human to complete consent with the real staging
  Upstox app in a browser.
* Identity ownership cases A–E on live staging — mechanically identical
  to the green unit suite (Test A–H) and partially covered live by the
  broker smoke (isolation b08, ownership gates b01/b02); they become
  fully demonstrable only once a real consented link exists.

## 8. Remaining limitations

1. **Live Upstox consent flow** — the single remaining validation gate.
   Requires the account holder to complete Upstox OAuth consent in a
   browser against the staging app (sandbox apps cannot OAuth); every
   automatable step around it is green (see §7).
2. Direct `alembic_version` / `pg_indexes` inspection of staging CRDB —
   not possible without storing CRDB credentials outside the service
   (deliberately not done); live evidence is the startup-migration
   behavior described in §6, plus the `data-only` lifecycle test running
   against the same cluster.
3. `get_or_create_user_from_upstox()` remains as a lookup-only shim for the
   separate legacy Upstox-only sign-in migration workstream; it must not be
   reintroduced into the callback.
4. The in-memory OAuth state map is process-local (deliberate, pre-existing):
   a restart during an OAuth redirect fails that attempt closed; the user
   retries. No persistence was added — unchanged behavior.
5. The pre-existing phase10 401-contract test failure (§3) is tracked
   separately with the platform-session workstream; it is not touched here.
   The `test_day7_session_persistence.py` suite also has a pre-existing
   SQLAlchemy-2.0 fixture bug (raw string passed to `Index`, 9 setup
   errors; last touched by `b3f495f`, outside this change set).
6. Optional hardening from design §10 (best-effort revocation of the
   orphaned Upstox token after a Phase-1 failure) remains unimplemented —
   the token is simply dropped, which is safe (nothing persisted).
7. The parallel session's untracked Day41.2 migration
   (`e2b4c6d8f0a1`) must be committed and re-parented onto
   `d9e0f1a2b3c4` (or re-based) when it lands, to keep the revision graph
   linear; until then the committed graph (head `d9e0f1a2b3c4`) is the
   deployable truth.
