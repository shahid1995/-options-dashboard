# SQLite → PostgreSQL Stage 2 Design

## Goal
Prepare a safe, reversible migration path from the current Railway file-backed SQLite database to the provisioned Railway PostgreSQL service without changing production database routing.

## Scope
- Create a consistent SQLite backup command using SQLite's online backup API.
- Add preflight checks for source schema, target connectivity, schema parity, and estimated target storage.
- Copy application data in foreign-key dependency order in bounded batches.
- Preserve values exactly; do not reinterpret market-data timestamps or change application semantics.
- Reset PostgreSQL identity/serial sequences after import.
- Produce deterministic source/target row counts and SHA-256 fingerprints for validation.
- Add CI rehearsal coverage using an ephemeral PostgreSQL 16 service and a generated SQLite source database.
- Document the production cutover gate; the migration utility must never modify `DATABASE_URL`, switch Railway services, or deploy automatically.

## Non-goals
- No production `DATABASE_URL` change.
- No production SQLite read/write through Railway automation.
- No deletion of the SQLite source.
- No broker credential transformation.
- No market-data recalculation or timestamp normalization.

## Architecture
A standalone CLI lives at `backend/tools/migrate_sqlite_to_postgres.py` with four explicit operations:

1. `backup`: create a byte-consistent SQLite backup file.
2. `preflight`: validate source/target accessibility, schema parity, row counts, and target storage budget.
3. `migrate`: copy rows from SQLite to PostgreSQL in dependency order, then reset PostgreSQL sequences.
4. `verify`: compare row counts and deterministic table fingerprints between source and target.

The CLI requires explicit source and target URLs for `migrate`; it has no production defaults. Target schema is created only through Alembic before data import. A migration aborts before writing if required source/target table sets differ, if a foreign-key dependency cycle is detected, or if the projected target footprint exceeds the configured safety threshold.

## Safety
- Default batch size: 1000 rows.
- Default PostgreSQL storage warning threshold: 80% of configured target budget.
- Default target budget for this rehearsal: 500 MiB, matching the current Railway Hobby volume ceiling.
- Verification is required after migration; any mismatch causes a non-zero exit code.
- Credentials are never printed; URL diagnostics redact everything after the scheme/user portion.

## Validation
- Unit tests cover URL parsing, topological table ordering, canonical row hashing, sequence reset SQL generation, and storage-threshold decisions.
- Integration test creates a fresh SQLite schema via Alembic, inserts representative identity/GEX rows, migrates into PostgreSQL 16, and asserts counts/fingerprints plus FK behavior.
- Existing PostgreSQL compatibility CI remains green.
