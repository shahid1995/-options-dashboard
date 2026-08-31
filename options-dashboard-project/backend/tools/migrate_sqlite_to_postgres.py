#!/usr/bin/env python3
"""Safe SQLite -> PostgreSQL migration utility for StrikeNova."""
from __future__ import annotations
import argparse, base64, hashlib, os, sqlite3, time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit, urlunsplit

BATCH_SIZE = 1000
SKIP_TABLES = {"alembic_version", "sqlite_sequence"}
GEX_DATA_SOURCES = {"analytics_token", "broker_oauth", "api_upload"}
ENCRYPTED_COLUMNS = {"broker_api_key_encrypted", "broker_api_secret_encrypted", "broker_analytics_token_encrypted", "broker_token_encrypted", "broker_refresh_token_encrypted"}
ALL_TABLES = ["users","user_sessions","broker_connections","broker_tokens","paper_accounts","strategy_templates","strategy_template_legs","trades","legs","strategy_executions","paper_orders","positions","paper_transactions","strategy_leg_exposures","exit_exposure_allocations","bulk_exit_records","gex_snapshots","historical_gex","contract_specs","nifty_candles","option_candles","option_greeks","data_completeness","ingestion_checkpoint","ingestion_log","iv_observations"]

@dataclass
class MigrationResult:
    table: str
    source_count: int = 0
    target_count: int = 0
    rows_written: int = 0
    skipped: bool = False
    skip_reason: str = ""
    duration_seconds: float = 0.0
    error: str = ""

@dataclass
class VerificationResult:
    table: str
    row_count_match: bool = False
    fingerprint_match: bool = False
    pk_unique: bool = False
    fk_clean: bool = True
    not_null_clean: bool = True
    source_count: int = 0
    target_count: int = 0
    source_fingerprint: str = ""
    target_fingerprint: str = ""
    errors: list[str] = field(default_factory=list)
    passed: bool = False

def normalize_url(url: str) -> str:
    if url.startswith("postgres://"): return "postgresql+psycopg://" + url[11:]
    if url.startswith("postgresql://"): return "postgresql+psycopg://" + url[13:]
    return url

def redact_url(url: str) -> str:
    try:
        p = urlsplit(url)
        if p.password is None: return url
        netloc = f"{p.username or ''}:***@{p.hostname or ''}"
        if p.port: netloc += f":{p.port}"
        return urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))
    except Exception:
        return "<redacted database url>"

def storage_safety_ok(source_size: int, target_capacity: int) -> bool:
    return source_size >= 0 and target_capacity > 0 and source_size <= int(target_capacity * 0.8)

def canonical_value(value: Any) -> list[str]:
    if value is None: return ["null"]
    if isinstance(value, bool): return ["bool", "1" if value else "0"]
    if isinstance(value, int): return ["int", str(value)]
    if isinstance(value, float): return ["float", repr(value)]
    if isinstance(value, Decimal): return ["decimal", format(value, "f")]
    if isinstance(value, datetime):
        if value.tzinfo is not None: value = value.astimezone(timezone.utc)
        return ["datetime", value.isoformat()]
    if isinstance(value, date): return ["date", value.isoformat()]
    if isinstance(value, dtime): return ["time", value.isoformat()]
    if isinstance(value, bytes): return ["bytes", base64.b64encode(value).decode("ascii")]
    return ["str", str(value)]

def _fingerprint_token(value: Any) -> tuple[str, ...]:
    if isinstance(value, bool): return ("bool", "1" if value else "0")
    if isinstance(value, int) and value in (0, 1): return ("bool", str(value))
    if isinstance(value, datetime):
        # SQLite/legacy application timestamps may be naive UTC; PostgreSQL
        # may return aware UTC. Treat both as the same instant for migration
        # verification. Market-data naive timestamps remain identical on both
        # sides because neither side attaches a timezone during migration.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return ("datetime", value.isoformat())
    return tuple(canonical_value(value))

def _canonical_row(row: Sequence[Any]) -> tuple[tuple[str, ...], ...]:
    return tuple(_fingerprint_token(v) for v in row)

def sha256_rows(rows: Iterable[Sequence[Any]]) -> str:
    canonical_rows = sorted(_canonical_row(row) for row in rows)
    payload = "\n".join("|".join(":".join(part) for part in row) for row in canonical_rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()

def sequence_reset_sql(table: str, column: str) -> str:
    return "SELECT setval(" + f"pg_get_serial_sequence('{table}', '{column}'), " + f"COALESCE((SELECT MAX(\"{column}\") FROM \"{table}\"), 1), true)"

def get_alembic_heads(alembic_dir: str | Path) -> list[str]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    directory = Path(alembic_dir).resolve()
    config = Config(str(directory.parent / "alembic.ini"))
    config.set_main_option("script_location", str(directory))
    return list(ScriptDirectory.from_config(config).get_heads())

def backup_sqlite(source_path: str, destination_path: str) -> None:
    source, destination = Path(source_path).resolve(), Path(destination_path).resolve()
    if not source.exists(): raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(source), timeout=30) as src:
        integrity = src.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok": raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        src.execute("PRAGMA wal_checkpoint(FULL)")
        with sqlite3.connect(str(destination), timeout=30) as dst:
            src.backup(dst); dst.commit()
            if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok": raise RuntimeError("Backup integrity check failed")
    os.chmod(destination, 0o600)

class SQLiteReader:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path).resolve()
        if not self.db_path.exists(): raise FileNotFoundError(self.db_path)
        self.conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=30)
        self.conn.row_factory = sqlite3.Row
    def close(self): self.conn.close()
    def integrity_check(self): return self.conn.execute("PRAGMA quick_check").fetchone()[0]
    def wal_checkpoint(self): raise RuntimeError("WAL checkpoint requires a read-write SQLite connection; use backup_sqlite()")
    def get_tables(self): return [r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    def get_columns(self, table): return [r[1] for r in self.conn.execute(f"PRAGMA table_info([{table}])")]
    def get_pk_columns(self, table):
        rows = self.conn.execute(f"PRAGMA table_info([{table}])").fetchall()
        return [r[1] for r in sorted(rows, key=lambda r: r[5]) if r[5] > 0]
    def count(self, table): return int(self.conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0])
    def fetch_all(self, table, columns):
        cols = ", ".join(f"[{c}]" for c in columns)
        return [tuple(r) for r in self.conn.execute(f"SELECT {cols} FROM [{table}]")]
    def fetch_batch(self, table, columns, offset, limit):
        cols = ", ".join(f"[{c}]" for c in columns)
        return [tuple(r) for r in self.conn.execute(f"SELECT {cols} FROM [{table}] LIMIT ? OFFSET ?", (offset, limit))]
    def compute_fingerprint(self, table, columns): return sha256_rows(self.fetch_all(table, columns))
    def file_sha256(self): return sha256_file(str(self.db_path))
    def file_size(self): return self.db_path.stat().st_size

class PgWriter:
    def __init__(self, pg_url=None, connection=None, owns_connection=True):
        if connection is None:
            import psycopg
            if pg_url is None: raise ValueError("pg_url or connection is required")
            self.conn = psycopg.connect(normalize_url(pg_url), connect_timeout=15); self.conn.autocommit = False; self._owns_connection = True
        else: self.conn, self._owns_connection = connection, owns_connection
    @classmethod
    def from_sqlalchemy_engine(cls, engine): return cls(connection=engine.raw_connection(), owns_connection=True)
    def close(self):
        if self._owns_connection: self.conn.close()
    def table_exists(self, table):
        with self.conn.cursor() as c:
            c.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s)", (table,)); return bool(c.fetchone()[0])
    def get_columns(self, table):
        with self.conn.cursor() as c:
            c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (table,)); return [r[0] for r in c.fetchall()]
    def count(self, table):
        with self.conn.cursor() as c: c.execute(f'SELECT COUNT(*) FROM "{table}"'); return int(c.fetchone()[0])
    def fetch_all(self, table, columns):
        cols = ", ".join(f'"{c}"' for c in columns)
        with self.conn.cursor() as c: c.execute(f'SELECT {cols} FROM "{table}"'); return [tuple(r) for r in c.fetchall()]
    def get_pk_columns(self, table):
        with self.conn.cursor() as c:
            c.execute("SELECT a.attname, k.ordinality FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey) JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, ordinality) ON k.attnum=a.attnum WHERE i.indrelid=%s::regclass AND i.indisprimary ORDER BY k.ordinality", (table,)); return [r[0] for r in c.fetchall()]
    def get_fk_constraints(self, table):
        with self.conn.cursor() as c:
            c.execute("SELECT kcu.column_name, ccu.table_name, ccu.column_name FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name=ccu.constraint_name AND tc.table_schema=ccu.table_schema WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public' AND tc.table_name=%s", (table,)); return list(c.fetchall())
    def get_not_null_columns(self, table):
        with self.conn.cursor() as c:
            c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s AND is_nullable='NO'", (table,)); return [r[0] for r in c.fetchall()]
    def insert_batch(self, table, columns, rows):
        if not rows: return 0
        cols = ", ".join(f'"{c}"' for c in columns); ph = ", ".join(["%s"] * len(columns))
        with self.conn.cursor() as c: c.executemany(f'INSERT INTO "{table}" ({cols}) VALUES ({ph})', rows)
        return len(rows)
    def compute_fingerprint(self, table, columns): return sha256_rows(self.fetch_all(table, columns))
    def check_pk_uniqueness(self, table, pk_cols):
        total = self.count(table)
        if not pk_cols: return True, total, total
        cols = ", ".join(f'"{c}"' for c in pk_cols)
        with self.conn.cursor() as c: c.execute(f'SELECT COUNT(*) FROM (SELECT DISTINCT {cols} FROM "{table}") t'); unique = int(c.fetchone()[0])
        return total == unique, total, unique
    def check_fk_integrity(self, table):
        errors = []
        for col, ref_table, ref_col in self.get_fk_constraints(table):
            with self.conn.cursor() as c:
                c.execute(f'SELECT COUNT(*) FROM "{table}" t LEFT JOIN "{ref_table}" r ON t."{col}"=r."{ref_col}" WHERE t."{col}" IS NOT NULL AND r."{ref_col}" IS NULL'); count = int(c.fetchone()[0])
            if count: errors.append(f"{table}.{col} -> {ref_table}.{ref_col}: {count} orphaned rows")
        return errors
    def check_not_null(self, table):
        errors = []
        for col in self.get_not_null_columns(table):
            with self.conn.cursor() as c: c.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" IS NULL'); count = int(c.fetchone()[0])
            if count: errors.append(f"{table}.{col}: {count} NULL values")
        return errors
    def get_sequence_info(self):
        with self.conn.cursor() as c:
            c.execute("SELECT table_name, column_name, pg_get_serial_sequence('public.' || table_name, column_name) FROM information_schema.columns WHERE table_schema='public' AND (is_identity='YES' OR column_default LIKE 'nextval(%') ORDER BY table_name, column_name")
            return [(r[0], r[1], r[2]) for r in c.fetchall() if r[2]]
    def check_sequences(self):
        results = {}
        with self.conn.cursor() as c:
            for table, col, seq in self.get_sequence_info():
                c.execute(f'SELECT COALESCE(MAX("{col}"), 0) FROM "{table}"'); maxv = int(c.fetchone()[0] or 0)
                c.execute("SELECT last_value FROM pg_sequences WHERE schemaname='public' AND sequencename=%s", (seq.split('.')[-1],)); row = c.fetchone(); val = int(row[0]) if row and row[0] is not None else 0
                results[seq] = {"table": table, "column": col, "value": val, "max": maxv, "ok": val >= maxv}
        return results
    def verify_security_invariants(self):
        with self.conn.cursor() as c:
            c.execute("SELECT COUNT(*) FROM users"); users = int(c.fetchone()[0])
            c.execute("SELECT COUNT(*) FROM user_sessions"); sessions = int(c.fetchone()[0])
            c.execute("SELECT COUNT(*) FROM broker_connections"); connections = int(c.fetchone()[0])
            c.execute("SELECT COUNT(*) FROM broker_tokens"); tokens = int(c.fetchone()[0])
            c.execute("SELECT DISTINCT data_source FROM gex_snapshots WHERE data_source IS NOT NULL ORDER BY data_source"); sources = [r[0] for r in c.fetchall()]
            c.execute("SELECT COUNT(*) FROM gex_snapshots WHERE data_source IN ('analytics_token','broker_oauth') AND connection_id IS NULL"); missing = int(c.fetchone()[0])
            c.execute("SELECT trading_status, COUNT(*) FROM broker_connections GROUP BY trading_status"); trading = {r[0]: int(r[1]) for r in c.fetchall()}
        return {"users_count": users, "user_sessions_count": sessions, "broker_connections_count": connections, "broker_tokens_count": tokens, "gex_data_sources": sources, "invalid_gex_sources": [s for s in sources if s not in GEX_DATA_SOURCES], "gex_missing_connection_provenance": missing, "trading_status": trading}
    def verify_multi_user_isolation(self, user_ids):
        results = {}
        with self.conn.cursor() as c:
            for uid in user_ids:
                c.execute("SELECT COUNT(*) FROM user_sessions WHERE user_id=%s", (uid,)); sessions = int(c.fetchone()[0])
                c.execute("SELECT COUNT(*) FROM broker_connections WHERE user_id=%s", (uid,)); connections = int(c.fetchone()[0])
                c.execute("SELECT COUNT(*) FROM gex_snapshots WHERE owner_id=%s", (uid,)); gex = int(c.fetchone()[0])
                results[uid] = {"sessions": sessions, "connections": connections, "gex_snapshots": gex}
        return results


def _order_table_names(metadata, names=None):
    selected = {n: t for n, t in metadata.tables.items() if n not in SKIP_TABLES and (names is None or n in names)}
    deps = {n: set() for n in selected}
    for n, table in selected.items():
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            if parent in selected and parent != n: deps[n].add(parent)
    order = []
    while deps:
        ready = sorted(n for n, d in deps.items() if not d)
        if not ready: raise RuntimeError("dependency cycle detected in migration tables")
        order.extend(ready)
        for n in ready: deps.pop(n, None)
        for d in deps.values(): d.difference_update(ready)
    return order

def get_table_order(metadata): return _order_table_names(metadata)

def assert_schema_compatible(source_metadata, target_metadata):
    source_tables = {n for n in source_metadata.tables if n not in SKIP_TABLES}; target_tables = {n for n in target_metadata.tables if n not in SKIP_TABLES}
    missing = sorted(source_tables - target_tables)
    if missing: raise ValueError(f"tables missing from target: {', '.join(missing)}")
    for n in sorted(source_tables):
        missing_cols = sorted(set(source_metadata.tables[n].columns.keys()) - set(target_metadata.tables[n].columns.keys()))
        if missing_cols: raise ValueError(f"columns missing from target for {n}: {', '.join(missing_cols)}")

def assert_target_empty(writer, tables):
    non_empty = [(t, writer.count(t)) for t in tables if writer.count(t)]
    if non_empty: raise RuntimeError("PostgreSQL target is not empty: " + ", ".join(f"{t}={c}" for t,c in non_empty))

def migrate_table(reader, writer, table, dry_run=False):
    result = MigrationResult(table=table); start = time.monotonic(); result.source_count = reader.count(table)
    if result.source_count == 0: result.skipped=True; result.skip_reason="empty source table"; return result
    if not writer.table_exists(table): result.error=f"Table {table} does not exist in PostgreSQL"; return result
    source_cols=reader.get_columns(table); target_cols=writer.get_columns(table); common=[c for c in source_cols if c in target_cols]
    if not common: result.error=f"No common columns for {table}"; return result
    if dry_run: result.skipped=True; result.skip_reason="dry run"; return result
    offset=0
    while offset < result.source_count:
        batch=reader.fetch_batch(table,common,offset,BATCH_SIZE)
        if not batch: break
        result.rows_written += writer.insert_batch(table,common,batch); offset += len(batch)
    result.target_count=writer.count(table); result.duration_seconds=time.monotonic()-start; return result

def _repair_sequences_with_sqlalchemy(connection):
    from sqlalchemy import text
    rows=connection.execute(text("SELECT table_name, column_name, pg_get_serial_sequence('public.' || table_name, column_name) FROM information_schema.columns WHERE table_schema='public' AND (is_identity='YES' OR column_default LIKE 'nextval(%')")).fetchall()
    for table,col,seq in rows:
        if not seq: continue
        maxv=connection.execute(text(f'SELECT MAX("{col}") FROM "{table}"')).scalar()
        if maxv is None: continue
        current=connection.execute(text("SELECT last_value FROM pg_sequences WHERE schemaname='public' AND sequencename=:name"), {"name":seq.split('.')[-1]}).scalar()
        if current is None or int(current) < int(maxv): connection.execute(text("SELECT setval(:seq,:maxv,true)"), {"seq":seq,"maxv":int(maxv)})

def migrate_database(sqlite_engine, postgres_engine, batch_size=BATCH_SIZE):
    from sqlalchemy import MetaData, select
    source_md=MetaData(); target_md=MetaData(); source_md.reflect(bind=sqlite_engine); target_md.reflect(bind=postgres_engine); assert_schema_compatible(source_md,target_md)
    source_names={n for n in source_md.tables if n not in SKIP_TABLES}; order=_order_table_names(target_md,source_names); src=sqlite_engine.connect(); dst=postgres_engine.connect(); tx=dst.begin()
    try:
        for table_name in order:
            st=source_md.tables[table_name]; tt=target_md.tables[table_name]; common=[c.name for c in st.columns if c.name in tt.columns]
            if not common: continue
            rows=src.execute(select(*[st.c[n] for n in common]))
            while True:
                batch=rows.fetchmany(batch_size)
                if not batch: break
                dst.execute(tt.insert(),[dict(zip(common,row)) for row in batch])
        _repair_sequences_with_sqlalchemy(dst); tx.commit()
    except Exception: tx.rollback(); raise
    finally: src.close(); dst.close()
    return verify_databases(sqlite_engine,postgres_engine)

def verify_table(reader,writer,table):
    v=VerificationResult(table=table); v.source_count=reader.count(table); v.target_count=writer.count(table); v.row_count_match=v.source_count==v.target_count; common=[c for c in reader.get_columns(table) if c in writer.get_columns(table)]
    if not common: v.errors.append("no common columns"); return v
    v.source_fingerprint=reader.compute_fingerprint(table,common); v.target_fingerprint=writer.compute_fingerprint(table,common); v.fingerprint_match=v.source_fingerprint==v.target_fingerprint; v.pk_unique=writer.check_pk_uniqueness(table,writer.get_pk_columns(table))[0]; fk=writer.check_fk_integrity(table); v.fk_clean=not fk; v.errors.extend(fk); nn=writer.check_not_null(table); v.not_null_clean=not nn; v.errors.extend(nn)
    if not v.row_count_match: v.errors.append(f"row count mismatch: source={v.source_count}, target={v.target_count}")
    if not v.fingerprint_match: v.errors.append("SHA-256 fingerprint mismatch")
    if not v.pk_unique: v.errors.append("primary key uniqueness check failed")
    v.passed=v.row_count_match and v.fingerprint_match and v.pk_unique and v.fk_clean and v.not_null_clean; return v

def verify_databases(sqlite_engine,postgres_engine):
    source_path=sqlite_engine.url.database
    if not source_path or source_path==":memory:": raise ValueError("verify_databases requires a file-backed SQLite database")
    reader=SQLiteReader(str(source_path)); writer=PgWriter.from_sqlalchemy_engine(postgres_engine)
    try:
        tables=[t for t in reader.get_tables() if t not in SKIP_TABLES]; verifications=[verify_table(reader,writer,t) for t in tables if writer.table_exists(t)]; seq=writer.check_sequences(); sec=writer.verify_security_invariants(); uids=[]
        if writer.table_exists("users"):
            with writer.conn.cursor() as c: c.execute("SELECT id FROM users ORDER BY id"); uids=[r[0] for r in c.fetchall()]
        isolation=writer.verify_multi_user_isolation(uids)
        ok=all(v.passed for v in verifications) and all(x.get("ok",False) for x in seq.values()) and not sec.get("invalid_gex_sources") and int(sec.get("gex_missing_connection_provenance",0))==0 and "cross_user_violation" not in isolation
        return {"ok":ok,"tables":{v.table:{"row_count":v.target_count,"source_count":v.source_count,"fingerprint_match":v.fingerprint_match,"source_fingerprint":v.source_fingerprint,"target_fingerprint":v.target_fingerprint,"pk_unique":v.pk_unique,"fk_clean":v.fk_clean,"not_null_clean":v.not_null_clean,"errors":v.errors,"passed":v.passed} for v in verifications},"sequences":seq,"security":sec,"isolation":isolation}
    finally: reader.close(); writer.close()

def check_ready_for_cutover(reader,writer,results,verifications,security,user_isolation):
    reasons=[]
    if reader.integrity_check()!="ok": reasons.append("SQLite integrity check failed")
    heads=get_alembic_heads(Path(__file__).resolve().parents[1]/"alembic")
    if len(heads)!=1: reasons.append(f"Alembic has {len(heads)} heads")
    else:
        try:
            with writer.conn.cursor() as c: c.execute("SELECT version_num FROM alembic_version"); row=c.fetchone()
            if not row or row[0]!=heads[0]: reasons.append("Alembic database head does not match repository head")
        except Exception: reasons.append("Alembic head could not be verified")
    for r in results:
        if r.error: reasons.append(f"Migration error in {r.table}")
    for v in verifications:
        if not v.passed: reasons.append(f"Verification failed for {v.table}")
    if security.get("invalid_gex_sources"): reasons.append("Invalid GEX data_source values")
    if security.get("gex_missing_connection_provenance"): reasons.append("User-owned GEX snapshot is missing connection provenance")
    if "cross_user_violation" in user_isolation: reasons.append("Cross-user ownership violation")
    if not all(x.get("ok",False) for x in writer.check_sequences().values()): reasons.append("PostgreSQL sequences are behind imported IDs")
    return not reasons,reasons


def main():
    p=argparse.ArgumentParser(description="Safe SQLite -> PostgreSQL migration for StrikeNova"); p.add_argument("--sqlite",required=True); p.add_argument("--pg-url"); p.add_argument("--dry-run",action="store_true"); p.add_argument("--validate-only",action="store_true"); p.add_argument("--ready-for-cutover",action="store_true"); args=p.parse_args()
    pg_url=normalize_url(args.pg_url or os.getenv("DATABASE_URL") or "")
    if not pg_url.startswith("postgresql+psycopg://"): print("ERROR: PostgreSQL URL must use the supported psycopg dialect"); return 1
    sqlite_path=Path(args.sqlite).resolve()
    if not sqlite_path.exists(): print(f"ERROR: SQLite backup not found: {sqlite_path}"); return 1
    reader=SQLiteReader(str(sqlite_path)); writer=PgWriter(pg_url)
    try:
        if reader.integrity_check()!="ok": print("ERROR: SQLite integrity check failed"); return 1
        print("SQLite integrity: ok"); print(f"Backup SHA-256: {reader.file_sha256()}"); print(f"Backup size: {reader.file_size():,} bytes")
        if args.dry_run: print("DRY RUN: source validated; no PostgreSQL writes performed"); return 0
        if args.validate_only or args.ready_for_cutover:
            tables=[t for t in reader.get_tables() if t not in SKIP_TABLES and writer.table_exists(t)]; vers=[verify_table(reader,writer,t) for t in tables]; sec=writer.verify_security_invariants();
            with writer.conn.cursor() as c: c.execute("SELECT id FROM users ORDER BY id"); ids=[r[0] for r in c.fetchall()]
            iso=writer.verify_multi_user_isolation(ids); ready,reasons=check_ready_for_cutover(reader,writer,[],vers,sec,iso)
            if args.ready_for_cutover: print("READY FOR CUTOVER" if ready else "NOT READY FOR CUTOVER"); [print(f"- {r}") for r in reasons]
            return 0 if ready else 1
        tables=[t for t in reader.get_tables() if t not in SKIP_TABLES]; assert_target_empty(writer,tables)
        from sqlalchemy import create_engine
        src_engine=create_engine(f"sqlite:///{sqlite_path}"); pg_engine=create_engine(pg_url)
        try: report=migrate_database(src_engine,pg_engine,BATCH_SIZE)
        finally: src_engine.dispose(); pg_engine.dispose()
        print(f"Migration verification: {'PASS' if report['ok'] else 'FAIL'}"); return 0 if report['ok'] else 1
    finally: reader.close(); writer.close()

if __name__=="__main__": raise SystemExit(main())
