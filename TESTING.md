# StrikeNova — Testing

**Status:** Canonical · **Owner:** Founder · **Last reviewed:** 2026-09-18

---

## 1. Principles

1. **Tests are behavior truth.** Comments and docstrings are not evidence.
2. **Baseline before changing.** Capture the failure set before any edit;
   afterwards require **no new failure signatures** — pre-existing failures are
   classified, never hidden.
3. **Isolate, then integrate.** Reproduce failures individually, per-file, then
   full-suite; test interactions are real defects (see the Phase 7.24 shared-
   engine pollution fix, PR #60).
4. **Hermetic by default.** Tests that exercise `init_db()`/migrations use
   isolated engines (`tests/conftest.py::hermetic_init_db`,
   `test_db_migration.py` pattern) — never the shared in-memory test engine.
5. **Local passes are not CI evidence.** Authoritative results come from the
   GitHub Actions gates below.

## 2. Backend (pytest)

```bash
cd options-dashboard-project/backend
python -m pytest tests/ -q            # full suite
python -m pytest tests/<file> -q      # focused
```

- 185 test files; conftest swaps in an in-memory SQLite engine under pytest.
- **Focused security/auth set (Issue #61):**
  `tests/test_secure_session_cookies.py` (cookie transport, canonical-cookie
  end-to-end incl. platform-only sessions, WebSocket cookie auth),
  `tests/test_auth_router.py`, `tests/test_phase10_2a_identity.py`,
  `tests/test_auth_account_flows.py`, `tests/test_auth_security_gaps.py`,
  `tests/test_day3_security.py`, `tests/test_google_auth.py`,
  `tests/test_identity_linking.py`, `tests/test_gex_security.py`.
- **Database safety set:** `test_postgres_compatibility.py`,
  `test_sqlite_postgres_migration.py`, `test_migrate_sqlite_to_postgres.py`,
  `test_rehearsal_ci_database.py`, `test_migration_hardening.py`,
  `test_migration_failure_injection.py`, `test_migration_large_rehearsal.py`,
  `test_day5_alembic_authority.py`, `test_day6_performance_baseline.py`, plus
  `test_cockroachdb_compat.py`.
- PostgreSQL-only tests skip locally by design; the CI service container
  enforces them.

## 3. Frontend (vitest)

```bash
cd options-dashboard-project/frontend
npm test            # full suite
npm test -- <path>  # focused
```

- ~84 files. **Focused auth/transport set:** `lib/session-transport.test.js`
  (no header/storage/URL/subprotocol session transport; consumer scans),
  `lib/useAuth.behavior.test.js` (transient-failure vs 401/403 semantics),
  `components/AuthGate.test.js` (`/auth/me` authority, redirect/retry rules),
  `lib/api.test.js`, `lib/useAuth.test.js`, `tests/auth-flow.test.js`,
  `components/public/AuthModal.test.js`, `lib/resolveApi.test.js`.

## 4. CI gates (authoritative)

| Workflow | Trigger paths | Job | Scope |
|---|---|---|---|
| **PostgreSQL compatibility** | `backend/**` | Backend PostgreSQL compatibility | The database-safety set above against a real `postgres:16` service container |
| **StrikeNova Status Gate** | `backend/**`, `frontend/**`, `docs/superpowers/**` | Status tracker and master plan validation | Tracker + master plan + execution protocol exist; master-plan SHA sync; warns when implementation files change without a tracker update |

Per the Status Gate: substantial backend/frontend changes should also update
`docs/superpowers/STRIKENOVA_IMPLEMENTATION_STATUS.md`.

## 5. Known pre-existing baseline failures (transparent ledger)

The full backend suite carries five long-standing failures **unrelated to
auth/session/BYOB** (verified identical on the base line and after every Issue
#61 change):

1. `test_live_verification.py::TestVerifyDbRoundtrip::test_candle_roundtrip`
2. `test_phase721_persistence.py::TestDatabasePathDeterminism::test_engine_url_is_absolute`
3. `test_strategy_resolver.py::TestNonStandardExpiries::test_custom_expiry_list`
4. `test_timestamp_standardization.py::test_no_naive_now_in_production`
5. `test_upstox_adapter.py::test_capabilities_matrix_is_complete_and_session_aware`

These are open work items to triage/fix through the normal issue flow — they
are listed here so "no new failure signatures" comparisons stay honest, not to
normalize them.

## 6. Verification checklist for a change

1. Focused tests for the touched area (own pytest process).
2. Complete affected files.
3. Relevant regression group (see §2/§3).
4. Full suite — compare failure lists against the recorded baseline.
5. Database-safety set when models/migrations/engine code changed.
6. Status Gate + PostgreSQL compatibility green on the final commit SHA.
7. Report exact commands and observed results — successes **and** failures.
