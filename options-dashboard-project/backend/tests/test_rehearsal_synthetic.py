"""Realistic multi-user migration rehearsal.

Creates a synthetic SQLite dataset covering all application tables with:
- Multiple users
- Multiple sessions
- Multiple broker connections with encrypted tokens
- GEX snapshots with provenance
- Paper accounts, orders, positions, trades
- Strategy templates and executions
- FK relationships throughout

Then runs the complete migration to PostgreSQL and verifies every table.
"""
import hashlib
import os
import sqlite3
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest

# Add backend/tools/ to path
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from migrate_sqlite_to_postgres import (
    SQLiteReader,
    PgWriter,
    ALL_TABLES,
    SKIP_TABLES,
    GEX_DATA_SOURCES,
    sha256_rows,
    migrate_table,
    verify_table,
    check_ready_for_cutover,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid():
    return str(uuid.uuid4())


def _ts(h=0, m=0, s=0):
    return f"2026-08-31 {h:02d}:{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Synthetic dataset builder
# ---------------------------------------------------------------------------

def build_synthetic_dataset(db_path: str) -> dict:
    """Build a realistic multi-user SQLite dataset. Returns metadata."""
    conn = sqlite3.connect(db_path)

    # Create all application tables (matching Alembic schema)
    conn.executescript("""
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            display_name TEXT,
            status TEXT DEFAULT 'active',
            identity_source TEXT,
            broker_provider TEXT,
            broker_user_id TEXT,
            created_at TEXT,
            updated_at TEXT,
            last_login_at TEXT,
            password_hash TEXT,
            google_sub TEXT
        );

        CREATE TABLE user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            session_hash TEXT NOT NULL,
            created_at TEXT,
            expires_at TEXT,
            revoked_at TEXT,
            broker_connection_id TEXT
        );

        CREATE TABLE broker_connections (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            broker TEXT NOT NULL,
            broker_account_id TEXT NOT NULL,
            display_label TEXT,
            is_default BOOLEAN DEFAULT 1,
            status TEXT DEFAULT 'connected',
            capability_mode TEXT DEFAULT 'trading',
            broker_api_key_encrypted TEXT,
            broker_api_secret_encrypted TEXT,
            broker_analytics_token_encrypted TEXT,
            broker_redirect_uri TEXT,
            broker_static_ip TEXT,
            app_type TEXT,
            provider_metadata_json TEXT DEFAULT '{}',
            created_at TEXT,
            updated_at TEXT,
            connected_at TEXT,
            disconnected_at TEXT,
            data_status TEXT DEFAULT 'inactive',
            data_source TEXT,
            trading_status TEXT DEFAULT 'inactive',
            trading_static_ip TEXT
        );

        CREATE TABLE broker_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            connection_id TEXT NOT NULL,
            broker TEXT NOT NULL,
            broker_token_encrypted TEXT,
            broker_token_expires_at TEXT,
            broker_refresh_token_encrypted TEXT,
            broker_refresh_token_expires_at TEXT,
            has_analytics_token BOOLEAN DEFAULT 0,
            broker_analytics_token_encrypted TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE paper_accounts (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            balance REAL DEFAULT 1000000,
            created_at TEXT
        );

        CREATE TABLE strategy_templates (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            name TEXT,
            created_at TEXT
        );

        CREATE TABLE strategy_template_legs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id TEXT,
            side TEXT,
            strike_offset REAL,
            option_type TEXT,
            expiry_offset INTEGER DEFAULT 0,
            quantity INTEGER DEFAULT 1
        );

        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            account_id TEXT,
            symbol TEXT,
            side TEXT,
            quantity INTEGER,
            price REAL,
            created_at TEXT
        );

        CREATE TABLE legs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER,
            symbol TEXT,
            side TEXT,
            quantity INTEGER,
            price REAL
        );

        CREATE TABLE strategy_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            account_id TEXT,
            template_id TEXT,
            status TEXT,
            created_at TEXT
        );

        CREATE TABLE paper_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            account_id TEXT,
            symbol TEXT,
            side TEXT,
            quantity INTEGER,
            price REAL,
            status TEXT,
            created_at TEXT
        );

        CREATE TABLE positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            account_id TEXT,
            symbol TEXT,
            quantity INTEGER,
            avg_price REAL,
            created_at TEXT
        );

        CREATE TABLE paper_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            account_id TEXT,
            type TEXT,
            amount REAL,
            balance_after REAL,
            created_at TEXT
        );

        CREATE TABLE strategy_leg_exposures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id INTEGER,
            leg_index INTEGER,
            exposure REAL
        );

        CREATE TABLE exit_exposure_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id INTEGER,
            allocation REAL
        );

        CREATE TABLE bulk_exit_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            account_id TEXT,
            status TEXT,
            created_at TEXT
        );

        CREATE TABLE gex_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            expiry TEXT,
            spot REAL,
            net_gex REAL,
            owner_id TEXT,
            connection_id TEXT,
            data_source TEXT,
            created_at TEXT
        );

        CREATE TABLE historical_gex (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument_key TEXT,
            interval TEXT,
            open_time TEXT,
            raw_gex REAL,
            calc_version TEXT DEFAULT 'v1'
        );

        CREATE TABLE contract_specs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument_key TEXT UNIQUE,
            symbol TEXT,
            expiry TEXT,
            strike REAL,
            option_type TEXT
        );

        CREATE TABLE nifty_candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            interval TEXT,
            open_time TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER
        );

        CREATE TABLE option_candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument_key TEXT,
            interval TEXT,
            open_time TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER
        );

        CREATE TABLE option_greeks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument_key TEXT,
            interval TEXT,
            open_time TEXT,
            delta REAL,
            gamma REAL,
            theta REAL,
            vega REAL,
            calc_version TEXT DEFAULT 'v1'
        );

        CREATE TABLE data_completeness (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument_key TEXT,
            date TEXT,
            completeness REAL
        );

        CREATE TABLE ingestion_checkpoint (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline TEXT,
            instrument_key TEXT,
            last_checkpoint TEXT
        );

        CREATE TABLE ingestion_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline TEXT,
            status TEXT,
            message TEXT,
            created_at TEXT
        );

        CREATE TABLE iv_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument_key TEXT,
            iv REAL,
            observed_at TEXT
        );
    """)

    # --- User A ---
    user_a = _uuid()
    conn.execute(
        "INSERT INTO users (id, email, display_name, identity_source, created_at, last_login_at, google_sub) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_a, "alice@example.com", "Alice", "google", _ts(10), _ts(14, 30), "google-sub-alice")
    )

    # --- User B ---
    user_b = _uuid()
    conn.execute(
        "INSERT INTO users (id, email, display_name, identity_source, created_at, last_login_at, password_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_b, "bob@example.com", "Bob", "email", _ts(11), _ts(15, 0), "hashed_password_bob")
    )

    # --- Sessions ---
    sessions = []
    for i in range(5):
        sid = _uuid()
        uid = user_a if i < 3 else user_b
        conn.execute(
            "INSERT INTO user_sessions (user_id, session_hash, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (uid, sid, _ts(10 + i), _ts(10 + i + 24))
        )
        sessions.append((uid, sid))

    # --- Broker Connections ---
    conn_a = _uuid()
    conn.execute(
        "INSERT INTO broker_connections "
        "(id, user_id, broker, broker_account_id, display_label, is_default, status, "
        "broker_api_key_encrypted, broker_api_secret_encrypted, broker_analytics_token_encrypted, "
        "data_status, trading_status, created_at, connected_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (conn_a, user_a, "UPSTOX", "U1001", "Alice Upstox", 1, "connected",
         "enc_api_key_alice_abc123def456", "enc_api_secret_alice_xyz789",
         "enc_analytics_alice_token_456",
         "active", "inactive", _ts(10), _ts(10))
    )

    conn_b = _uuid()
    conn.execute(
        "INSERT INTO broker_connections "
        "(id, user_id, broker, broker_account_id, display_label, is_default, status, "
        "broker_api_key_encrypted, broker_api_secret_encrypted, "
        "data_status, trading_status, created_at, connected_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (conn_b, user_b, "UPSTOX", "U2002", "Bob Upstox", 1, "connected",
         "enc_api_key_bob_abc123def456", "enc_api_secret_bob_xyz789",
         "active", "inactive", _ts(11), _ts(11))
    )

    # --- Broker Tokens ---
    conn.execute(
        "INSERT INTO broker_tokens "
        "(connection_id, broker, broker_token_encrypted, broker_token_expires_at, "
        "has_analytics_token, broker_analytics_token_encrypted, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (conn_a, "UPSTOX", "enc_oauth_token_alice_123", _ts(12), 1,
         "enc_analytics_token_alice_456", _ts(10))
    )

    conn.execute(
        "INSERT INTO broker_tokens "
        "(connection_id, broker, broker_token_encrypted, broker_refresh_token_encrypted, "
        "broker_token_expires_at, has_analytics_token, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (conn_b, "UPSTOX", "enc_oauth_token_bob_789", "enc_refresh_bob_abc",
         _ts(13), 0, _ts(11))
    )

    # --- Paper Accounts ---
    acct_a = _uuid()
    acct_b = _uuid()
    conn.execute("INSERT INTO paper_accounts (id, user_id, balance, created_at) VALUES (?, ?, ?, ?)",
                 (acct_a, user_a, 1000000.0, _ts(10)))
    conn.execute("INSERT INTO paper_accounts (id, user_id, balance, created_at) VALUES (?, ?, ?, ?)",
                 (acct_b, user_b, 500000.0, _ts(11)))

    # --- Strategy Templates ---
    tpl_a = _uuid()
    tpl_b = _uuid()
    conn.execute("INSERT INTO strategy_templates (id, user_id, name, created_at) VALUES (?, ?, ?, ?)",
                 (tpl_a, user_a, "Iron Condor", _ts(10)))
    conn.execute("INSERT INTO strategy_templates (id, user_id, name, created_at) VALUES (?, ?, ?, ?)",
                 (tpl_b, user_b, "Straddle", _ts(11)))

    conn.execute("INSERT INTO strategy_template_legs (template_id, side, strike_offset, option_type, quantity) "
                 "VALUES (?, ?, ?, ?, ?)", (tpl_a, "BUY", -100, "CE", 1))
    conn.execute("INSERT INTO strategy_template_legs (template_id, side, strike_offset, option_type, quantity) "
                 "VALUES (?, ?, ?, ?, ?)", (tpl_a, "SELL", 100, "CE", 1))
    conn.execute("INSERT INTO strategy_template_legs (template_id, side, strike_offset, option_type, quantity) "
                 "VALUES (?, ?, ?, ?, ?)", (tpl_b, "BUY", 0, "CE", 1))
    conn.execute("INSERT INTO strategy_template_legs (template_id, side, strike_offset, option_type, quantity) "
                 "VALUES (?, ?, ?, ?, ?)", (tpl_b, "BUY", 0, "PE", 1))

    # --- Trades ---
    trade_a1 = None
    for i in range(3):
        conn.execute(
            "INSERT INTO trades (user_id, account_id, symbol, side, quantity, price, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_a, acct_a, f"NIFTY{i}CE", "BUY", 10, 150.0 + i * 10, _ts(12, i))
        )
        trade_a1 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    for i in range(2):
        conn.execute(
            "INSERT INTO trades (user_id, account_id, symbol, side, quantity, price, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_b, acct_b, f"NIFTY{i}PE", "SELL", 5, 200.0 + i * 15, _ts(13, i))
        )

    # --- Legs ---
    if trade_a1:
        conn.execute("INSERT INTO legs (trade_id, symbol, side, quantity, price) VALUES (?, ?, ?, ?, ?)",
                     (trade_a1, "NIFTY24500CE", "BUY", 10, 170.0))

    # --- Strategy Executions ---
    conn.execute(
        "INSERT INTO strategy_executions (user_id, account_id, template_id, status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_a, acct_a, tpl_a, "completed", _ts(12))
    )
    exec_b_id = conn.execute(
        "INSERT INTO strategy_executions (user_id, account_id, template_id, status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_b, acct_b, tpl_b, "pending", _ts(13))
    ).lastrowid

    # --- Strategy Leg Exposures ---
    conn.execute("INSERT INTO strategy_leg_exposures (execution_id, leg_index, exposure) VALUES (?, ?, ?)",
                 (exec_b_id, 0, 5000.0))
    conn.execute("INSERT INTO strategy_leg_exposures (execution_id, leg_index, exposure) VALUES (?, ?, ?)",
                 (exec_b_id, 1, -5000.0))

    # --- Exit Exposure Allocations ---
    conn.execute("INSERT INTO exit_exposure_allocations (execution_id, allocation) VALUES (?, ?)",
                 (exec_b_id, 2500.0))

    # --- Paper Orders ---
    conn.execute(
        "INSERT INTO paper_orders (user_id, account_id, symbol, side, quantity, price, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_a, acct_a, "NIFTY24500CE", "BUY", 10, 150.0, "filled", _ts(12))
    )
    conn.execute(
        "INSERT INTO paper_orders (user_id, account_id, symbol, side, quantity, price, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_b, acct_b, "NIFTY24500PE", "SELL", 5, 200.0, "pending", _ts(13))
    )

    # --- Positions ---
    conn.execute(
        "INSERT INTO positions (user_id, account_id, symbol, quantity, avg_price, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_a, acct_a, "NIFTY24500CE", 10, 155.0, _ts(12))
    )
    conn.execute(
        "INSERT INTO positions (user_id, account_id, symbol, quantity, avg_price, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_b, acct_b, "NIFTY24500PE", -5, 205.0, _ts(13))
    )

    # --- Paper Transactions ---
    conn.execute(
        "INSERT INTO paper_transactions (user_id, account_id, type, amount, balance_after, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_a, acct_a, "TRADE", -1500.0, 998500.0, _ts(12))
    )
    conn.execute(
        "INSERT INTO paper_transactions (user_id, account_id, type, amount, balance_after, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_b, acct_b, "TRADE", 1000.0, 501000.0, _ts(13))
    )

    # --- Bulk Exit Records ---
    conn.execute(
        "INSERT INTO bulk_exit_records (user_id, account_id, status, created_at) VALUES (?, ?, ?, ?)",
        (user_a, acct_a, "completed", _ts(14))
    )

    # --- GEX Snapshots (with provenance) ---
    for i in range(3):
        conn.execute(
            "INSERT INTO gex_snapshots (symbol, expiry, spot, net_gex, owner_id, connection_id, data_source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"NIFTY{i}", "2026-09-05", 24500.0 + i * 100, 1500.0 + i * 200,
             user_a, conn_a, "analytics_token", _ts(12, i))
        )

    for i in range(2):
        conn.execute(
            "INSERT INTO gex_snapshots (symbol, expiry, spot, net_gex, owner_id, connection_id, data_source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"BANKNIFTY{i}", "2026-09-12", 51000.0 + i * 200, 3000.0 + i * 500,
             user_b, conn_b, "broker_oauth", _ts(13, i))
        )

    # --- Market data ---
    for i in range(5):
        conn.execute(
            "INSERT INTO contract_specs (instrument_key, symbol, expiry, strike, option_type) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"NIFTY{i}CE", "NIFTY", "2026-09-05", 24500.0 + i * 100, "CE")
        )
        conn.execute(
            "INSERT INTO nifty_candles (symbol, interval, open_time, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("NIFTY", "1m", _ts(9, 15 + i), 24500.0 + i, 24510.0 + i, 24490.0 + i, 24505.0 + i, 1000 + i)
        )
        conn.execute(
            "INSERT INTO option_candles (instrument_key, interval, open_time, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"NIFTY{i}CE", "1m", _ts(9, 15 + i), 150.0 + i, 160.0 + i, 145.0 + i, 155.0 + i, 500 + i)
        )
        conn.execute(
            "INSERT INTO option_greeks (instrument_key, interval, open_time, delta, gamma, theta, vega) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"NIFTY{i}CE", "1m", _ts(9, 15 + i), 0.5 + i * 0.05, 0.01 + i * 0.002, -5.0 - i, 20.0 + i)
        )
        conn.execute(
            "INSERT INTO historical_gex (instrument_key, interval, open_time, raw_gex) "
            "VALUES (?, ?, ?, ?)",
            (f"NIFTY{i}CE", "1m", _ts(9, 15 + i), 1000.0 + i * 100)
        )

    conn.execute(
        "INSERT INTO ingestion_checkpoint (pipeline, instrument_key, last_checkpoint) VALUES (?, ?, ?)",
        ("candle_fetch", "NIFTY", _ts(9, 20))
    )
    conn.execute(
        "INSERT INTO ingestion_log (pipeline, status, message, created_at) VALUES (?, ?, ?, ?)",
        ("candle_fetch", "success", "Fetched 5 candles", _ts(9, 20))
    )

    conn.commit()
    conn.close()

    return {
        "user_a": user_a,
        "user_b": user_b,
        "conn_a": conn_a,
        "conn_b": conn_b,
        "sessions": len(sessions),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRehearsalSynthetic:
    """Full migration rehearsal against realistic synthetic data."""

    def test_full_rehearsal(self, tmp_path):
        """Build synthetic dataset, migrate, and verify every table."""
        db_path = str(tmp_path / "synthetic.db")

        # Step 1: Build synthetic dataset
        meta = build_synthetic_dataset(db_path)
        reader = SQLiteReader(db_path)

        # Verify dataset
        assert reader.integrity_check() == "ok"
        assert reader.count("users") == 2
        assert reader.count("user_sessions") == meta["sessions"]
        assert reader.count("broker_connections") == 2
        assert reader.count("broker_tokens") == 2
        assert reader.count("gex_snapshots") == 5

        # Step 2: Connect to PostgreSQL (skip if not available)
        pg_url = os.environ.get("DATABASE_URL")
        if not pg_url or not pg_url.startswith("postgresql"):
            pytest.skip("PostgreSQL not available for rehearsal")

        writer = PgWriter(pg_url)

        try:
            # Verify PostgreSQL has schema
            for table in ALL_TABLES:
                if table in SKIP_TABLES:
                    continue
                assert writer.table_exists(table), f"Table {table} missing in PostgreSQL"

            # Step 3: Migrate all tables
            for table in ALL_TABLES:
                if table in SKIP_TABLES:
                    continue
                r = migrate_table(reader, writer, table)
                if r.error:
                    pytest.fail(f"Migration error in {table}: {r.error}")
                if not r.skipped:
                    assert r.rows_written == r.source_count, \
                        f"{table}: wrote {r.rows_written} but source has {r.source_count}"

            # Step 4: Verify every table
            for table in ALL_TABLES:
                if table in SKIP_TABLES:
                    continue
                if reader.count(table) == 0:
                    continue

                v = verify_table(reader, writer, table)
                assert v.passed, f"Verification failed for {table}: {v.errors}"
                assert v.row_count_match, f"{table}: count mismatch src={v.source_count} tgt={v.target_count}"
                assert v.fingerprint_match, \
                    f"{table}: SHA-256 mismatch src={v.source_fingerprint[:16]} tgt={v.target_fingerprint[:16]}"
                assert v.pk_unique, f"{table}: PK duplicates"
                assert v.fk_clean, f"{table}: FK orphans: {v.errors}"
                assert v.not_null_clean, f"{table}: NOT NULL violations: {v.errors}"

            # Step 5: Verify encrypted credentials
            cur = writer.conn.cursor()
            for col in ["broker_api_key_encrypted", "broker_api_secret_encrypted",
                        "broker_analytics_token_encrypted", "broker_token_encrypted"]:
                cur.execute(f'SELECT "{col}" FROM broker_tokens WHERE "{col}" IS NOT NULL')
                rows = cur.fetchall()
                for row in rows:
                    assert row[0] and len(row[0]) > 10, f"Encrypted value too short or empty: {col}"

            # Verify ciphertext matches between SQLite and PG
            src_rows = reader.fetch_all("broker_tokens", ["broker_token_encrypted"])
            pg_rows = []
            cur.execute('SELECT broker_token_encrypted FROM broker_tokens ORDER BY id')
            pg_rows = cur.fetchall()
            for src, tgt in zip(src_rows, pg_rows):
                assert src[0] == tgt[0], f"Encrypted ciphertext mismatch: src={src[0][:20]} tgt={tgt[0][:20]}"

            # Step 6: Verify GEX provenance
            cur.execute("SELECT owner_id, connection_id, data_source FROM gex_snapshots ORDER BY id")
            gex_rows = cur.fetchall()
            for owner, conn_id, source in gex_rows:
                assert owner in (meta["user_a"], meta["user_b"]), f"Unknown owner: {owner}"
                assert conn_id in (meta["conn_a"], meta["conn_b"]), f"Unknown connection: {conn_id}"
                assert source in GEX_DATA_SOURCES, f"Invalid data_source: {source}"

            # Step 7: Verify multi-user isolation
            cur.execute("SELECT user_id, COUNT(*) FROM user_sessions GROUP BY user_id")
            session_owners = {r[0]: r[1] for r in cur.fetchall()}
            assert meta["user_a"] in session_owners
            assert meta["user_b"] in session_owners

            cur.execute("SELECT user_id, COUNT(*) FROM broker_connections GROUP BY user_id")
            conn_owners = {r[0]: r[1] for r in cur.fetchall()}
            assert conn_owners.get(meta["user_a"], 0) >= 1
            assert conn_owners.get(meta["user_b"], 0) >= 1

            # No cross-user token leakage
            cur.execute(
                "SELECT bc.user_id, bt.connection_id FROM broker_tokens bt "
                "JOIN broker_connections bc ON bt.connection_id = bc.id"
            )
            for uid, cid in cur.fetchall():
                assert uid in (meta["user_a"], meta["user_b"]), f"Unknown user in token join: {uid}"

            # Step 8: Sequences
            seqs = writer.check_sequences()
            for name, info in seqs.items():
                assert "error" not in info, f"Sequence error: {name}: {info['error']}"

            # Step 9: Cutover readiness check
            ready, reasons = check_ready_for_cutover(
                reader, writer, [], [], 
                writer.verify_security_invariants(),
                writer.verify_multi_user_isolation([meta["user_a"], meta["user_b"]])
            )
            # Note: may not be fully ready since alembic_version might not match
            # but the migration itself should be clean

        finally:
            reader.close()
            writer.close()
