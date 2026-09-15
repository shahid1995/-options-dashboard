# SQLite → PostgreSQL Stage 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a safe, reversible SQLite→PostgreSQL migration and verification workflow without changing production database routing.

**Architecture:** A standalone backend CLI owns backup, preflight, migration, and verification. It uses SQLAlchemy reflection for data transfer, Alembic for target schema creation, dependency ordering from reflected foreign keys, 1000-row batches, sequence repair, and deterministic table fingerprints. Production cutover remains a separate explicit operation and is not part of this plan.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0, Alembic 1.15, psycopg 3, SQLite stdlib `sqlite3`, pytest, GitHub Actions PostgreSQL 16 service.

**Spec:** `options-dashboard-project/docs/superpowers/specs/2026-08-30-sqlite-postgres-migration-stage2-design.md`

## Global Constraints

- SQLite remains the current production database until a separately approved cutover.
- The migration CLI must require explicit source and target database URLs for write operations.
- Target schema creation uses Alembic only.
- Migration copies values without market-data timestamp reinterpretation.
- Credentials and full database passwords/tokens must never be printed.
- Default batch size is 1000 rows.
- Default target storage safety threshold is 80% of the configured 500 MiB rehearsal budget.
- A verification mismatch must return a non-zero exit code.

---

### Task 1: Migration CLI foundation and deterministic helpers

**Files:**
- Create: `options-dashboard-project/backend/tools/migrate_sqlite_to_postgres.py`
- Test: `options-dashboard-project/backend/tests/test_sqlite_postgres_migration.py`

**Interfaces:**
- Consumes: SQLAlchemy database URLs and reflected metadata.
- Produces: `normalize_url()`, `redact_url()`, `get_table_order()`, `canonical_value()`, `table_fingerprint()`, `estimate_sqlite_size_bytes()`, and `storage_safety_ok()` for later migration tasks.

- [ ] **Step 1: Write failing tests for URL normalization and identifier-safe redaction**

```python
from tools.migrate_sqlite_to_postgres import normalize_url, redact_url


def test_normalize_postgres_url_to_psycopg():
    assert normalize_url("postgres://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"


def test_redact_url_does_not_expose_password():
    redacted = redact_url("postgresql+psycopg://user:secret@host:5432/db")
    assert "secret" not in redacted
    assert redacted.startswith("postgresql+psycopg://user:")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd options-dashboard-project/backend && python -m pytest -q tests/test_sqlite_postgres_migration.py -k 'normalize or redact'`

Expected: FAIL because `tools/migrate_sqlite_to_postgres.py` does not yet exist.

- [ ] **Step 3: Implement minimal URL helpers**

```python
def normalize_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def redact_url(url: str) -> str:
    from sqlalchemy.engine import make_url
    parsed = make_url(normalize_url(url))
    if parsed.password is None:
        return str(parsed)
    return str(parsed.set(password="***"))
```

- [ ] **Step 4: Write failing tests for canonical values and storage checks**

```python
from datetime import date, datetime, timezone
from decimal import Decimal

from tools.migrate_sqlite_to_postgres import canonical_value, storage_safety_ok


def test_canonical_value_is_stable_for_common_database_types():
    assert canonical_value(None) == ["null"]
    assert canonical_value(True) == ["bool", "1"]
    assert canonical_value(12) == ["int", "12"]
    assert canonical_value(1.5) == ["float", "1.5"]
    assert canonical_value(Decimal("1.50")) == ["decimal", "1.50"]
    assert canonical_value(date(2026, 8, 30)) == ["date", "2026-08-30"]
    assert canonical_value(datetime(2026, 8, 30, tzinfo=timezone.utc)) == ["datetime", "2026-08-30T00:00:00+00:00"]


def test_storage_safety_rejects_over_budget():
    assert storage_safety_ok(399 * 1024 * 1024, 500 * 1024 * 1024)
    assert not storage_safety_ok(401 * 1024 * 1024, 500 * 1024 * 1024)
```

- [ ] **Step 5: Run focused tests and verify RED**

Run: `cd options-dashboard-project/backend && python -m pytest -q tests/test_sqlite_postgres_migration.py -k 'canonical or storage'`

Expected: FAIL because helper functions are not implemented.

- [ ] **Step 6: Implement deterministic helpers**

```python
def canonical_value(value: object) -> list[str]:
    from datetime import date, datetime
    from decimal import Decimal

    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", "1" if value else "0"]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, float):
        return ["float", repr(value)]
    if isinstance(value, Decimal):
        return ["decimal", format(value, "f")]
    if isinstance(value, datetime):
        return ["datetime", value.isoformat()]
    if isinstance(value, date):
        return ["date", value.isoformat()]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return ["bytes", bytes(value).hex()]
    return [type(value).__name__, str(value)]


def storage_safety_ok(estimated_bytes: int, budget_bytes: int, threshold: float = 0.80) -> bool:
    return estimated_bytes <= int(budget_bytes * threshold)
```

- [ ] **Step 7: Run focused tests and verify GREEN**

Run: `cd options-dashboard-project/backend && python -m pytest -q tests/test_sqlite_postgres_migration.py -k 'normalize or redact or canonical or storage'`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add options-dashboard-project/backend/tools/migrate_sqlite_to_postgres.py options-dashboard-project/backend/tests/test_sqlite_postgres_migration.py
git commit -m "feat(db): add migration utility foundations"
```

---

### Task 2: Foreign-key ordering, backup, and schema preflight

**Files:**
- Modify: `options-dashboard-project/backend/tools/migrate_sqlite_to_postgres.py`
- Modify: `options-dashboard-project/backend/tests/test_sqlite_postgres_migration.py`

**Interfaces:**
- Consumes: SQLAlchemy `MetaData` objects from source/target engines.
- Produces: `backup_sqlite()`, `get_table_order()`, `assert_schema_compatible()`, and `preflight()`.

- [ ] **Step 1: Write failing tests for FK dependency ordering**

```python
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table
from tools.migrate_sqlite_to_postgres import get_table_order


def test_table_order_places_parent_before_child():
    metadata = MetaData()
    Table("parent", metadata, Column("id", Integer, primary_key=True))
    Table(
        "child",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("parent_id", Integer, ForeignKey("parent.id")),
    )
    assert get_table_order(metadata) == ["parent", "child"]
```

- [ ] **Step 2: Run focused test and verify RED**

Run: `cd options-dashboard-project/backend && python -m pytest -q tests/test_sqlite_postgres_migration.py::test_table_order_places_parent_before_child`

Expected: FAIL because `get_table_order()` does not exist.

- [ ] **Step 3: Implement dependency ordering with cycle detection**

```python
def get_table_order(metadata):
    tables = {name: table for name, table in metadata.tables.items()}
    deps = {name: set() for name in tables}
    for name, table in tables.items():
        for fk in table.foreign_keys:
            parent = fk.target_fullname.split(".", 1)[0]
            if parent in tables and parent != name:
                deps[name].add(parent)

    order: list[str] = []
    remaining = set(tables)
    while remaining:
        ready = sorted(name for name in remaining if not (deps[name] & remaining))
        if not ready:
            cycle = ", ".join(sorted(remaining))
            raise RuntimeError(f"foreign-key dependency cycle detected: {cycle}")
        order.extend(ready)
        remaining.difference_update(ready)
    return order
```

- [ ] **Step 4: Write failing tests for schema parity and SQLite backup**

```python
import sqlite3

from tools.migrate_sqlite_to_postgres import assert_schema_compatible, backup_sqlite


def test_schema_parity_rejects_missing_target_table():
    source = MetaData()
    target = MetaData()
    Table("source_only", source, Column("id", Integer, primary_key=True))
    with pytest.raises(ValueError, match="missing from target"):
        assert_schema_compatible(source, target)


def test_sqlite_backup_produces_a_valid_copy(tmp_path):
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO demo(value) VALUES ('ok')")
        conn.commit()
    backup_sqlite(str(source), str(backup))
    with sqlite3.connect(backup) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT value FROM demo").fetchone()[0] == "ok"
```

- [ ] **Step 5: Run focused tests and verify RED**

Run: `cd options-dashboard-project/backend && python -m pytest -q tests/test_sqlite_postgres_migration.py -k 'schema_parity or backup'`

Expected: FAIL because the helpers are missing.

- [ ] **Step 6: Implement parity and backup**

```python
def assert_schema_compatible(source, target):
    source_names = set(source.tables)
    target_names = set(target.tables)
    missing = sorted(source_names - target_names)
    if missing:
        raise ValueError(f"tables missing from target: {missing}")
    for table_name in sorted(source_names):
        source_columns = set(source.tables[table_name].columns.keys())
        target_columns = set(target.tables[table_name].columns.keys())
        missing_columns = sorted(source_columns - target_columns)
        if missing_columns:
            raise ValueError(
                f"columns missing from target table {table_name}: {missing_columns}"
            )


def backup_sqlite(source_path: str, backup_path: str) -> None:
    import sqlite3
    source = sqlite3.connect(source_path)
    try:
        target = sqlite3.connect(backup_path)
        try:
            source.backup(target)
            result = target.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"SQLite backup integrity check failed: {result}")
            target.commit()
        finally:
            target.close()
    finally:
        source.close()
```

- [ ] **Step 7: Run focused tests and verify GREEN**

Run: `cd options-dashboard-project/backend && python -m pytest -q tests/test_sqlite_postgres_migration.py -k 'table_order or schema_parity or backup'`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add options-dashboard-project/backend/tools/migrate_sqlite_to_postgres.py options-dashboard-project/backend/tests/test_sqlite_postgres_migration.py
git commit -m "feat(db): add migration preflight and sqlite backup"
```

---

### Task 3: Batched migration, sequence repair, and verification

**Files:**
- Modify: `options-dashboard-project/backend/tools/migrate_sqlite_to_postgres.py`
- Modify: `options-dashboard-project/backend/tests/test_sqlite_postgres_migration.py`

**Interfaces:**
- Consumes: validated source/target engines and metadata.
- Produces: `migrate_database()`, `reset_postgres_sequences()`, `table_fingerprint()`, and `verify_databases()`.

- [ ] **Step 1: Write failing tests for fingerprints and sequence reset SQL**

```python
from tools.migrate_sqlite_to_postgres import sequence_reset_sql


def test_sequence_reset_sql_uses_pg_get_serial_sequence():
    sql = sequence_reset_sql("users", "id")
    assert "pg_get_serial_sequence" in sql
    assert "setval" in sql
    assert "users" in sql
```

- [ ] **Step 2: Run focused test and verify RED**

Run: `cd options-dashboard-project/backend && python -m pytest -q tests/test_sqlite_postgres_migration.py::test_sequence_reset_sql_uses_pg_get_serial_sequence`

Expected: FAIL because `sequence_reset_sql()` does not exist.

- [ ] **Step 3: Implement sequence-reset SQL generation**

```python
def sequence_reset_sql(table_name: str, column_name: str) -> str:
    if not table_name.replace("_", "").isalnum() or not column_name.replace("_", "").isalnum():
        raise ValueError("unsafe SQL identifier")
    return (
        "SELECT setval(pg_get_serial_sequence('"
        + table_name
        + "', '"
        + column_name
        + "'), GREATEST(COALESCE((SELECT MAX("
        + column_name
        + ") FROM "
        + table_name
        + "), 1), 1), true)"
    )
```

- [ ] **Step 4: Write failing integration test for full rehearsal migration**

```python
def test_rehearsal_migrates_sqlite_rows_into_postgres(postgres_engine, tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    sqlite_url = f"sqlite:///{tmp_path / 'source.db'}"
    sqlite_engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    cfg.attributes["connectable"] = sqlite_engine
    command.upgrade(cfg, "head")

    target_cfg = Config(str(ROOT / "alembic.ini"))
    target_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    target_cfg.set_main_option("sqlalchemy.url", str(postgres_engine.url))
    target_cfg.attributes["connectable"] = postgres_engine
    command.upgrade(target_cfg, "head")

    source = sessionmaker(bind=sqlite_engine)()
    try:
        user = User(id="rehearsal-user", email="rehearsal@example.com", identity_source="email")
        connection = BrokerConnection(
            id="rehearsal-connection",
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="account-rehearsal",
            is_default=True,
            status="connected",
            capability_mode="data",
            data_status="active",
            trading_status="inactive",
        )
        source.add_all([user, connection])
        source.add(GexSnapshot(
            owner_id=user.id,
            connection_id=connection.id,
            data_source="analytics_token",
            symbol="NIFTY",
            expiry="2026-12-31",
            spot=25000.0,
            methodology="GEX_STANDARD_V1",
            sign_convention="NAIVE_DEALER_CONVENTION",
            availability_status="available",
            valid_strike_count=1,
            total_strike_count=1,
            captured_at=datetime.now(timezone.utc),
            strike_data="[]",
            expiry_data="[]",
            methodology_metadata="{}",
        ))
        source.commit()
    finally:
        source.close()

    migrate_database(sqlite_engine, postgres_engine, batch_size=1000)
    report = verify_databases(sqlite_engine, postgres_engine)
    assert report["ok"] is True
    assert report["tables"]["users"]["row_count"] == 1
    assert report["tables"]["gex_snapshots"]["row_count"] == 1

    sqlite_engine.dispose()
```

- [ ] **Step 5: Run integration test and verify RED**

Run: `cd options-dashboard-project/backend && TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/strikenova_test python -m pytest -q tests/test_sqlite_postgres_migration.py::test_rehearsal_migrates_sqlite_rows_into_postgres`

Expected: FAIL because `migrate_database()` and `verify_databases()` are not implemented.

- [ ] **Step 6: Implement batched migration and verification**

```python
def migrate_database(source_engine, target_engine, *, batch_size: int = 1000):
    source = MetaData()
    target = MetaData()
    source.reflect(bind=source_engine)
    target.reflect(bind=target_engine)
    assert_schema_compatible(source, target)
    order = get_table_order(source)

    with target_engine.begin() as target_conn:
        for table_name in order:
            source_table = source.tables[table_name]
            target_table = target.tables[table_name]
            with source_engine.connect().execution_options(stream_results=True) as source_conn:
                result = source_conn.execute(source_table.select())
                while True:
                    rows = result.fetchmany(batch_size)
                    if not rows:
                        break
                    payload = [dict(row._mapping) for row in rows]
                    target_conn.execute(target_table.insert(), payload)

    reset_postgres_sequences(target_engine, target)


def reset_postgres_sequences(engine, metadata):
    from sqlalchemy import text
    with engine.begin() as conn:
        for table_name, table in metadata.tables.items():
            for column in table.columns:
                if not column.primary_key or not column.name:
                    continue
                if "INTEGER" not in str(column.type).upper() and "BIGINT" not in str(column.type).upper():
                    continue
                sequence_sql = sequence_reset_sql(table_name, column.name)
                try:
                    conn.execute(text(sequence_sql))
                except Exception:
                    # Tables whose PK is not sequence-backed are valid; only
                    # reset when PostgreSQL reports an attached sequence.
                    continue


def table_fingerprint(engine, table):
    import hashlib
    import json

    primary_key = list(table.primary_key.columns)
    order_columns = primary_key or list(table.columns)
    digest = hashlib.sha256()
    count = 0
    with engine.connect().execution_options(stream_results=True) as conn:
        stmt = table.select().order_by(*order_columns)
        result = conn.execute(stmt)
        for row in result:
            values = []
            for column in table.columns:
                values.append([column.name, *canonical_value(row._mapping[column.name])])
            digest.update((json.dumps(values, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8"))
            count += 1
    return count, digest.hexdigest()


def verify_databases(source_engine, target_engine):
    source = MetaData()
    target = MetaData()
    source.reflect(bind=source_engine)
    target.reflect(bind=target_engine)
    assert_schema_compatible(source, target)
    report = {"ok": True, "tables": {}}
    for table_name in sorted(source.tables):
        source_count, source_hash = table_fingerprint(source_engine, source.tables[table_name])
        target_count, target_hash = table_fingerprint(target_engine, target.tables[table_name])
        match = source_count == target_count and source_hash == target_hash
        report["tables"][table_name] = {
            "row_count": target_count,
            "source_row_count": source_count,
            "source_fingerprint": source_hash,
            "target_fingerprint": target_hash,
            "match": match,
        }
        report["ok"] &= match
    return report
```

- [ ] **Step 7: Run full migration-test file and verify GREEN**

Run: `cd options-dashboard-project/backend && TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/strikenova_test python -m pytest -q tests/test_sqlite_postgres_migration.py`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add options-dashboard-project/backend/tools/migrate_sqlite_to_postgres.py options-dashboard-project/backend/tests/test_sqlite_postgres_migration.py
git commit -m "feat(db): add batched sqlite postgres migration and verification"
```

---

### Task 4: CLI commands, safety gates, and cutover documentation

**Files:**
- Modify: `options-dashboard-project/backend/tools/migrate_sqlite_to_postgres.py`
- Modify: `options-dashboard-project/backend/.env.example`
- Create: `options-dashboard-project/docs/POSTGRES_MIGRATION_RUNBOOK.md`
- Modify: `options-dashboard-project/backend/tests/test_sqlite_postgres_migration.py`

**Interfaces:**
- Consumes: helper functions from Tasks 1–3.
- Produces: CLI subcommands `backup`, `preflight`, `migrate`, `verify`; preflight output suitable for operator review; explicit no-cutover contract.

- [ ] **Step 1: Write failing CLI tests for safety behavior**

```python
def test_cli_requires_explicit_source_and_target_for_migrate():
    result = runner.invoke(cli, ["migrate"])
    assert result.exit_code != 0
    assert "--source" in result.output
    assert "--target" in result.output


def test_cli_refuses_migration_when_target_budget_is_exceeded(tmp_path):
    source = tmp_path / "source.db"
    source.write_bytes(b"0" * (10 * 1024 * 1024))
    result = runner.invoke(
        cli,
        [
            "migrate",
            "--source", f"sqlite:///{source}",
            "--target", "postgresql+psycopg://u:p@host/db",
            "--target-budget-mib", "1",
        ],
    )
    assert result.exit_code != 0
    assert "safety threshold" in result.output
```

- [ ] **Step 2: Run focused CLI tests and verify RED**

Run: `cd options-dashboard-project/backend && python -m pytest -q tests/test_sqlite_postgres_migration.py -k cli`

Expected: FAIL because the CLI is not implemented.

- [ ] **Step 3: Implement an explicit Click CLI with no production defaults**

```python
import click
from sqlalchemy import create_engine


@click.group()
def cli():
    """Safe SQLite→PostgreSQL migration utilities."""


@cli.command()
@click.option("--source", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--backup", "backup_path", required=True, type=click.Path(dir_okay=False))
def backup(source, backup_path):
    backup_sqlite(source, backup_path)
    click.echo(f"Backup created: {backup_path}")


@cli.command()
@click.option("--source", required=True)
@click.option("--target", required=True)
@click.option("--target-budget-mib", default=500, show_default=True, type=int)
def preflight(source, target, target_budget_mib):
    report = preflight_databases(source, target, target_budget_mib * 1024 * 1024)
    click.echo(json.dumps(report, indent=2, sort_keys=True))
    if not report["ok"]:
        raise click.ClickException("Preflight failed")


@cli.command()
@click.option("--source", required=True)
@click.option("--target", required=True)
@click.option("--batch-size", default=1000, show_default=True, type=click.IntRange(min=1))
@click.option("--target-budget-mib", default=500, show_default=True, type=int)
def migrate(source, target, batch_size, target_budget_mib):
    report = preflight_databases(source, target, target_budget_mib * 1024 * 1024)
    if not report["ok"]:
        raise click.ClickException("Migration blocked by preflight safety checks")
    migrate_database(create_engine(normalize_url(source)), create_engine(normalize_url(target)), batch_size=batch_size)
    click.echo("Migration completed; run verify before cutover.")


@cli.command()
@click.option("--source", required=True)
@click.option("--target", required=True)
def verify(source, target):
    report = verify_databases(
        create_engine(normalize_url(source)),
        create_engine(normalize_url(target)),
    )
    click.echo(json.dumps(report, indent=2, sort_keys=True))
    if not report["ok"]:
        raise click.ClickException("Verification mismatch detected")
```

- [ ] **Step 4: Add documented production cutover gate**

`POSTGRES_MIGRATION_RUNBOOK.md` must state:

```text
1. Back up the live SQLite database.
2. Copy the backup to a controlled operator workstation or staging location.
3. Run preflight against the backup and Railway Postgres.
4. Run migrate against the backup, never the live file.
5. Run verify and archive the report.
6. Confirm migrated size remains below the Railway volume safety ceiling.
7. Test the backend against Postgres in a separate environment/service.
8. Only after all gates pass may DATABASE_URL be changed explicitly.
9. Keep the SQLite backup untouched until post-cutover validation is complete.
10. No script in this repository changes DATABASE_URL or performs the production cutover automatically.
```

- [ ] **Step 5: Document the current Railway-specific state**

The runbook must record:

```text
Production backend: -options-dashboard
Production backend DATABASE_URL: not currently configured; SQLite remains active.
Postgres service: Postgres
Persistent mount: /var/lib/postgresql/data
Current Railway Hobby volume ceiling: 500 MB
Current Railway Postgres deployment: SUCCESS
```

- [ ] **Step 6: Run CLI/unit tests and verify GREEN**

Run: `cd options-dashboard-project/backend && TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/strikenova_test python -m pytest -q tests/test_sqlite_postgres_migration.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add options-dashboard-project/backend/tools/migrate_sqlite_to_postgres.py options-dashboard-project/backend/.env.example options-dashboard-project/docs/POSTGRES_MIGRATION_RUNBOOK.md options-dashboard-project/backend/tests/test_sqlite_postgres_migration.py
git commit -m "feat(db): add safe migration cli and production runbook"
```

---

### Task 5: CI rehearsal gate and complete verification

**Files:**
- Modify: `options-dashboard-project/.github/workflows/postgres-compatibility.yml`
- Modify: `options-dashboard-project/backend/tests/test_sqlite_postgres_migration.py`

**Interfaces:**
- Consumes: migration CLI and compatibility helpers.
- Produces: automated SQLite→PostgreSQL rehearsal coverage on every backend PR.

- [ ] **Step 1: Add rehearsal test invocation to the existing PostgreSQL workflow**

```yaml
- name: Run SQLite to PostgreSQL rehearsal
  env:
    TEST_DATABASE_URL: postgresql+psycopg://postgres:postgres@127.0.0.1:5432/strikenova_test
  run: python -m pytest -q tests/test_postgres_compatibility.py tests/test_sqlite_postgres_migration.py
```

- [ ] **Step 2: Run the repository's backend PostgreSQL workflow**

Run through the pushed branch/PR CI. Expected: PostgreSQL service healthy and both compatibility + rehearsal test files green.

- [ ] **Step 3: Run the existing backend regression suite**

Run: `cd options-dashboard-project/backend && python -m pytest -q`

Expected: PASS with no migration-related regressions.

- [ ] **Step 4: Inspect the final diff for scope**

Run: `git diff --check && git diff --stat main...HEAD`

Expected: clean diff, limited to migration tooling, tests, workflow, env example, and runbook/spec/plan documentation.

- [ ] **Step 5: Commit the CI update**

```bash
git add options-dashboard-project/.github/workflows/postgres-compatibility.yml options-dashboard-project/backend/tests/test_sqlite_postgres_migration.py
git commit -m "test(db): gate sqlite postgres migration in ci"
```

- [ ] **Step 6: Verify branch and PR state**

Run: `git status --short && git log -5 --oneline`

Expected: clean working tree and migration branch contains only the intended Stage 2 commits.
