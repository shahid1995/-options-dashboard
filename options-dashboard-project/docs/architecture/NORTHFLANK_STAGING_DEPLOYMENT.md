# StrikeNova — Northflank + CockroachDB Cloud Staging Deployment

Date: 2026-09-13
Branch: `feat/strikenova-day35-portfolio-intelligence`
Final status: **STAGING DEPLOYED WITH FOLLOW-UP REQUIRED**

Database infrastructure is fully deployed and migrated on CockroachDB Cloud staging. The
Northflank application service is blocked on an account-level billing prerequisite and a
migration-graph defect in the deployable commit. Details below.

---

## 1. Git commit deployed

* **Deployable commit:** `b847e58` — `docs(spec): correct task parallelism, vitest commands, and SC-001 traceability`
* **Remote verified:** YES — exists on `origin/feat/strikenova-day35-portfolio-intelligence`
* Local HEAD `5efb79b` (`feat(public): add evidence and trust section`) is 1 commit ahead and
  UNPUSHED — per the HARD RULE it was NOT deployed. Day41.2 implementation work remains
  uncommitted locally and was excluded from all deployment steps.

## 2. Git reconciliation

| Item | Value |
|---|---|
| Local HEAD at session start | `5efb79b` (unpushed, 1 ahead) |
| Remote HEAD | `b847e58` |
| Deployed/used SHA | `b847e58` (remote) |
| Uncommitted local work | Day41.2 Cross-D1 implementation, protected-file parallel edits — untouched |

The repo ships **no Dockerfile**; the backend is buildpack/Procfile-based:

```text
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## 3. Northflank

| Item | Value |
|---|---|
| Authenticated account | team `shahid2024s-team-17…` (CLI context, browser login) |
| Project | `strikenova` (**reused** — see deviation below) |
| Environment | staging (single project, no production infra created) |
| Service | `strikenova-api-staging` — **CREATION BLOCKED** (see §14) |

**Deviation:** the plan called for a project named `strikenova-staging`. The account's free
tier allows only ONE project (`409 Maximum number of free projects reached`). The existing
`strikenova` project was empty (no services/addons/jobs) and is in region `europe-west`; it
was reused for staging. No production infrastructure exists anywhere on the account.

## 4. CockroachDB Cloud

| Item | Value |
|---|---|
| Auth | `ccloud` CLI v0.6.12, browser login (user authorized; token stored locally by CLI) |
| Cluster | `strikenova-staging` (id `5ff4b7da-9421-4f9e-8acb-939657b11c4e`) |
| Plan | SERVERLESS (Basic) — non-production |
| Region | GCP `asia-south1` (closest supported to the pre-existing `best-lioness` ap-south-1 cluster) |
| CockroachDB version | v26.2.6 |
| Database | `strikenova_staging` |
| SQL user | `strikenova_staging_app` (dedicated; `root` not used) |
| Grants | `ALL` on `strikenova_staging` only |
| Password handling | Generated locally, stored only in `~/.strikenova_staging_crdb.txt` (0600), never committed, never echoed |

**Secret-hygiene incident (contained):** one `ccloud cluster sql --connection-params` call
printed the SQL password to the session transcript. The password was rotated immediately
(`ccloud cluster user password`), invalidating the exposed value. Never use
`--connection-params` non-interactively.

**Connection scheme note:** CockroachDB Cloud requires SQLAlchemy's CockroachDB dialect.
`DATABASE_URL` must use the `cockroachdb+psycopg://` scheme (the repo's own
`COCKROACH_RUNTIME_VALIDATION.md` documents exactly this). Plain `postgresql+psycopg://`
URLs crash SQLAlchemy with
`AssertionError: Could not determine version from string 'CockroachDB CCL v26.2.6 …'`.

## 5. Migration result (Phase 11) — PASS

Run from a throwaway `git worktree` checkout of the exact deployable commit `b847e58`:

```text
DATABASE_URL=cockroachdb+psycopg://strikenova_staging_app:…@strikenova-staging-20783.jxf.gcp-asia-south1.cockroachlabs.cloud:26257/strikenova_staging?sslmode=require
python -m alembic upgrade head
```

* Chain: base → **`5e2a7b9c3f4d (head)`** — completed without errors on real CRDB
* `alembic current`: `5e2a7b9c3f4d (head) (mergepoint)`
* Catalog verified: **37 tables** in `public`, including `users`,
  `broker_sync_idempotency`, `broker_raw_observation`, `gex_snapshots`
* `Base.metadata.create_all()` was NOT used; this is real Alembic chain proof
* The throwaway worktree was removed after the run

**Required glue:** the chain only resolves with `alembic/versions/merge_day38_gex.py`
present. That file exists in the local working tree but is **UNTRACKED** — it is NOT in
commit `b847e58` (nor any commit; `fdd0edb` added only the day39-side merge file). At the
exact deployable commit the graph is broken.

## 6. Deploy-blocking defect (evidence, not speculation)

Proven empirically at `b847e58` (without the untracked file):

1. `python -m alembic heads` → `KeyError: 'merge_day38_gex'`
2. `python -m uvicorn app.main:app --port 8123` with staging DATABASE_URL → startup crash,
   same `KeyError: 'merge_day38_gex'`

`app.main:lifespan` calls `init_db()` → `_run_alembic_migrations()` → `command.upgrade(cfg,
"head")` **unconditionally on startup**. A service built from `b847e58` would crash-loop
before ever serving traffic, regardless of health-check configuration.

**Fix required before deploy:** commit `backend/alembic/versions/merge_day38_gex.py`
(pure no-op merge revision, `down_revision = ("b2c3d4e5f6a7", "e8f9a0b1c2d3")`).

## 7. Build / runtime configuration (prepared, not yet applied)

* Service: `strikenova-api-staging`, project `strikenova`
* Build: buildpack, context `/options-dashboard-project/backend`, branch
  `feat/strikenova-day35-portfolio-intelligence` @ `b847e58`
* Deployment: 1 instance, plan `nf-compute-20` (smallest general plan; free-tier
  `nf-compute-100` plan also hits the same billing gate)
* Port: public HTTPS 443 → internal 8000; health check HTTP `/health` (30 s initial delay,
  10 s period); `/readiness` also exists
* Runtime env: `PORT=8000`, `DATABASE_URL` (managed secret, `cockroachdb+psycopg://…`
  staging URL). Not yet applied — service creation blocked (§14).

## 8. API / DB / CRDB verification

* Direct DB verification: PASSED (catalog, grants, migrations above)
* HTTP API verification: NOT YET POSSIBLE — service does not exist yet
* Planned CRDB smoke tests (ON CONFLICT / RETURNING / transaction commit + rollback) are
  deferred to the post-deploy verification pass; the repo's CRDB compatibility design docs
  already cover retry/serialization behavior

## 9. Security verification

* Production DB touched: **NO** (Railway untouched)
* Vercel production touched: **NO**
* Production DNS changed: **NO**
* Secrets committed: **NO** (`.env` files, `.gitignore`, and all pre-existing dirty files untouched)
* Credentials logged: one SQL password was exposed in the transcript and **rotated immediately** (invalid)
* CockroachDB cluster is new, isolated, non-production

## 10. Problems encountered

1. Northflank free tier = 1 project → reused `strikenova` project (name deviation)
2. `northflank create service` → `409 Please complete your account by adding a default
   payment method` (account-level gate, independent of plan)
3. `sqlalchemy-cockroachdb` missing locally → installed (tooling only, no repo change)
4. `ccloud auth login` requires a real interactive console → fixed launcher
   `~/ccloud_login.cmd` to use absolute binary path and no stdin piping; user completed
   browser login after one retry
5. `merge_day38_gex.py` untracked → migration graph and app startup broken at `b847e58`
6. CRDB version-string incompatibility with plain postgres dialect → documented
   `cockroachdb+psycopg://` requirement (matches repo's own validation docs)

## 11. Remaining follow-ups (ordered)

1. Add a default payment method in the Northflank console (account owner action)
2. Commit the untracked `backend/alembic/versions/merge_day38_gex.py` (repo-level fix;
   requires a new commit on the branch — NOT done in this session)
3. Push the branch so the deployable SHA contains the fix, then create the service from the
   corrected commit
4. Apply `DATABASE_URL` (managed secret) and deploy
5. Re-run Alembic from the deployed service (idempotent — chain already at head)
6. Complete Phase 13–16 verification: `/health`, `/readiness`, API endpoints, DB round-trip,
   CRDB smoke tests
7. Write post-deploy verification results into this report

## 12. What IS verified end-to-end today

```text
CockroachDB Cloud (Basic, asia-south1)
    └── strikenova-staging cluster
          └── strikenova_staging database
                └── full Alembic chain base → 5e2a7b9c3f4d (37 tables)
                      └── dedicated app user, least-privilege grants
```

The Northflank → API leg awaits the billing prerequisite and the migration-graph fix.

---

## 13. Pre-Deployment Blockers Discovered (2026-09-13, follow-up session)

Both deployment blockers were corrected and verified. This session did NOT create the
Northflank service and did NOT deploy.

### Blocker 1 — Missing `merge_day38_gex` migration reference

**Root cause.** At `b847e58` the migration
`f7aa24156f6d_merge_day39_broker_sync_day38_gex_heads.py` references
`down_revision = ('9b675f8a3af0', 'merge_day38_gex')`, but no committed file defined
`revision = "merge_day38_gex"`. The file existed only as an UNTRACKED local file.
Mechanical graph analysis (AST parse of all 16 committed migration files) showed exactly
one dangling reference and two heads: `b2c3d4e5f6a7` (GEX provenance branch) and
`5e2a7b9c3f4d` (main line).

**Intent evidence (not guessed).** Two documents committed at `b847e58` both list
`merge_day38_gex.py` as a repository migration file and describe it as a no-op merge:
`NORTHFLANK_COCKROACH_MIGRATION_AUDIT.md` (§2.4 file inventory, §4.3.9 "No-op merge. ✅",
§ 4.3.9 quoting `down_revision = ('9b675f8a3af0', 'merge_day38_gex')`) and
`COCKROACH_COMPATIBILITY_EXPERIMENT.md` (compatibility table). Commit `fdd0edb`
("Merge alembic heads: day39 broker-sync + day38 gex") added only the day39-side merge
file — the day38-side merge file was never `git add`-ed. Conclusion: `merge_day38_gex`
was a real merge revision, intended to merge `b2c3d4e5f6a7` (GEX provenance) with
`e8f9a0b1c2d3` (Day38 trade lifecycle), lost to an incomplete commit.

**Fix.** Committed `backend/alembic/versions/merge_day38_gex.py`
(`revision = "merge_day38_gex"`, `down_revision = ("b2c3d4e5f6a7", "e8f9a0b1c2d3")`,
no-op upgrade/downgrade) — restoring true ancestry, not a fabricated no-op-to-silence-
KeyError. After the fix: `alembic heads` → `5e2a7b9c3f4d (head)` — exactly one head,
17 history entries, no dangling references, no unreachable migrations.

**Verification.** Fresh CRDB database `strikenova_staging_v2` (dropped + recreated):
`alembic upgrade head` completed base → `5e2a7b9c3f4d`, 37 tables, single
`alembic_version` row.

### Blocker 2 — Missing CockroachDB SQLAlchemy dialect dependency

**Root cause.** `backend/requirements.txt` at `b847e58` contained SQLAlchemy 2.0.43 and
psycopg 3 but no CockroachDB dialect. SQLAlchemy's postgresql dialect crashes against
CRDB (`AssertionError: Could not determine version from string 'CockroachDB CCL …'`), so
`cockroachdb+psycopg://` URLs could not load in a deployment environment.

**Package verification (Step 2A).** `sqlalchemy-cockroachdb 2.0.4` (latest) declares
`SQLAlchemy>=2.0.47` — it would force an upgrade of the pinned 2.0.43. Releases
2.0.0–2.0.3 declare no SQLAlchemy constraint. Selected **2.0.3** with the repository's
existing `sqlalchemy==2.0.43` pin (smallest delta; no driver replacement; psycopg 3 kept).

**Fix.** Added `sqlalchemy-cockroachdb==2.0.3` to `backend/requirements.txt`.

**Clean-install verification (Step 2C).** Fresh venv built ONLY from the resulting
requirements: SQLAlchemy 2.0.43 + sqlalchemy-cockroachdb 2.0.3 + psycopg 3.3.5 +
alembic 1.15.2. `create_engine("cockroachdb+psycopg://…")` → dialect `cockroachdb`,
driver `psycopg`. PASS.

### Application startup on CockroachDB (Step 4/5) — the decisive proof

Using the exact deployment venv and a checkout of the deployable tree containing ONLY
committed files plus the two fixes (no untracked migrations):

* Fresh empty database `strikenova_staging_v3` created (0 tables, verified BEFORE boot)
* App started with `DATABASE_URL=cockroachdb+psycopg://…strikenova_staging_v3…`
* **The application's own startup path migrated the empty database**: 33 tables observed
  mid-boot (`alembic_version` at `f7aa24156f6d`, CRDB index-backfill jobs running), then
  completed to **37 tables / `5e2a7b9c3f4d` / exactly one version row**
* `Application startup complete` with zero errors; `/health` → `{"status":"ok"}`;
  `/readiness` → `{"status":"ready","checks":{"database":"ok",…}}`
* CRDB runtime smoke (deployment venv): ON CONFLICT upsert PASS, RETURNING PASS,
  rollback PASS

**Works without untracked migration files: YES** — the bootstrap test ran in a
worktree where the only migration files present were committed ones plus the repaired
`merge_day38_gex.py`.

### Known non-blocking issue (out of scope, documented)

Migration `c7d3e5f8a9b2_google_sub_index.py` passes raw strings to
`postgresql_where`/`sqlite_where`, which crashes SQLAlchemy 2.0.43 compilers
(`'str' object has no attribute '_compiler_dispatch'`) — 12 SQLite-path tests fail at
`b847e58` for this reason; they pass with a `text()` wrapper (a fix already present as an
uncommitted working-tree change by a parallel session). The CRDB path of this migration
uses its dedicated `cockroachdb` branch and is unaffected — both fresh CRDB chains passed.
This is a repo-level latent defect, NOT a CRDB deployment blocker, and was NOT modified
by this session.

### Production boundary

Railway / Railway PostgreSQL / Vercel / production data: NOT TOUCHED.
Northflank service: NOT CREATED. No deploy performed. Session ends at
**DEPLOYMENT PRECONDITIONS VERIFIED**.

---

## 14. Retry Using User-Created Northflank Project (2026-09-13)

**Context.** The user manually created/uses the existing Northflank project
`strikenova` (https://app.northflank.com/t/shahid2024s-team/project/strikenova) and has
decided NOT to add a payment card. Deployment baseline moved to the fixed commit.

### Git verification before deploy

* Current remote HEAD of `feat/strikenova-day35-portfolio-intelligence`:
  **`2139097f2f11bba77dd2c79c9815333306d74fe7`** (no commits beyond it; local HEAD identical)
* `backend/alembic/versions/merge_day38_gex.py`: **COMMITTED** ✅
* `backend/requirements.txt` contains `sqlalchemy-cockroachdb==2.0.3`: **YES** ✅
* `b847e58` correctly excluded as deployable.

### Project verification (authenticated CLI, team context `shahid2024s-team-17…`)

* Project `strikenova`: exists, accessible, region `europe-west`, cluster `nf-europe-west`
* Resources: 0 services, 0 jobs, 0 addons (empty; nothing pre-existing affected)
* No production infrastructure exists on the account; no environment separation needed
  (single-project free tier)

### Service creation attempt

```text
northflank create service combined --project strikenova  (strikenova-api-staging,
buildpack buildContext /options-dashboard-project/backend, branch
feat/strikenova-day35-portfolio-intelligence @ 2139097, 1 instance,
nf-compute-20, public HTTPS 443 → 8000, health check /health)
```

Result: **`409 Please complete your account by adding a default payment method`**

Classification (Phase 17): **account/billing gate**. The gate is account-level and
applies regardless of project ownership, compute plan, or project emptiness. Per the
user's explicit decision not to add a card, creation was attempted exactly once this
session; no retry loop, no paid resources, no workarounds.

### Deployable state summary (ready when hosting is resolved)

* Deployable commit: `2139097` (both CRDB prerequisites fixed and verified)
* CRDB staging: cluster `strikenova-staging` (Basic, asia-south1), database
  `strikenova_staging`, user `strikenova_staging_app`, migration head `5e2a7b9c3f4d`
  (37 tables) — migration + startup + health/readiness + smoke proofs in §13
* Not executed this session: service creation (blocked), therefore build/runtime/health/
  smoke checks against Northflank remain pending

### Final result

**BLOCKED — NORTHFLANK ACCOUNT REQUIRES PAYMENT METHOD**

Northflank viability must be re-decided by the user: add a payment method in the
Northflank console, or evaluate an alternative staging host. No further Northflank
attempts will be made without new instructions.
