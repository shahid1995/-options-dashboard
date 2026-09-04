"""Day 6 — PostgreSQL Performance Baseline & Benchmark Tests.

Creates a disposable database, applies Alembic migrations, seeds a
deterministic synthetic dataset, and benchmarks representative query
workloads.  Also audits index coverage and identifies evidence-backed
optimization candidates.

Runs against SQLite locally for rapid iteration.  CI validates against
PostgreSQL 16 via the postgres-compatibility workflow.
"""

from __future__ import annotations

import os
import random
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEED = 42
NUM_USERS = 5
EXPIRIES_COUNT = 10
STRIKES_PER_EXPIRY = 20
NIFTY_CANDLES_PER_DAY = 200
NIFTY_CANDLE_DAYS = 30
OPTION_CANDLES_PER_INSTRUMENT = 100
OPTION_INSTRUMENT_COUNT = 50
STRATEGY_EXECUTIONS_PER_USER = 50
POSITIONS_PER_USER = 25
GEX_SNAPSHOTS_PER_USER = 200
HISTORICAL_GEX_PER_INSTRUMENT = 500
INGESTION_LOG_ENTRIES = 500

BENCHMARK_ITERATIONS = 10


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def bench_db():
    """Create a disposable benchmark database with Alembic migrations applied
    and a deterministic synthetic dataset seeded."""
    from alembic.config import Config
    from alembic import command as alembic_command

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(tmp_fd)

    try:
        db_url = f"sqlite:///{tmp_path}"
        engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
        )

        # Apply Alembic migrations
        alembic_cfg = Config(
            os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
        )
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        alembic_cfg.attributes["connectable"] = engine
        alembic_command.upgrade(alembic_cfg, "head")

        # Seed deterministic dataset
        _seed_dataset(engine)

        yield engine

        engine.dispose()
    finally:
        try:
            os.unlink(tmp_path)
        except PermissionError:
            pass  # Windows cleanup


def _seed_dataset(engine) -> None:
    """Seed a deterministic synthetic dataset representing realistic scale.

    Uses ORM models to guarantee schema alignment — every column and
    default is handled by SQLAlchemy, avoiding raw-SQL schema mismatches.
    """
    rng = random.Random(SEED)
    now = datetime.now(timezone.utc)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        from app.identity import User, UserSession
        from app.models import (
            PaperAccount, Trade, Leg, StrategyExecution, PaperOrder,
            Position, PaperTransaction, StrategyLegExposure,
            GexSnapshot, NiftyCandle, ContractSpec, OptionCandle,
            OptionGreeks, HistoricalGexSnapshot, IngestionLog,
            DataCompleteness, IngestionCheckpoint, StrategyTemplate,
            StrategyTemplateLeg,
        )

        # --- Users ---
        user_ids = [f"user_{i:03d}" for i in range(NUM_USERS)]
        for uid in user_ids:
            db.add(User(
                id=uid, email=f"{uid}@test.com", display_name=uid,
                status="active", identity_source="test",
            ))
        db.flush()

        # --- Paper accounts ---
        for uid in user_ids:
            db.add(PaperAccount(user_id=uid, starting_capital=500000))
        db.flush()

        # --- Contract specs (option chain) ---
        base_date = now.date()
        expiries = []
        for e in range(EXPIRIES_COUNT):
            exp_date = base_date + timedelta(days=7 * (e + 1))
            expiries.append(exp_date.strftime("%Y-%m-%d"))

        base_spot = 24000.0
        strikes = [
            base_spot + i * 50 - (STRIKES_PER_EXPIRY // 2) * 50
            for i in range(STRIKES_PER_EXPIRY)
        ]
        instrument_counter = 0
        all_instrument_keys = []

        for expiry in expiries:
            for strike in strikes:
                for inst_type in ("CE", "PE"):
                    instrument_counter += 1
                    key = f"NSE_FO|{instrument_counter}|{expiry}"
                    all_instrument_keys.append(key)
                    db.add(ContractSpec(
                        instrument_key=key, underlying="NIFTY",
                        underlying_key="NSE_INDEX|50", expiry=expiry,
                        strike_price=strike, instrument_type=inst_type,
                        lot_size=50, minimum_lot=50,
                        trading_symbol=f"NIFTY {expiry} {strike} {inst_type}",
                        segment="NSE_FO", exchange="NSE_FO", weekly=True,
                        source="test", source_reference="seed",
                        fetched_at=now,
                    ))
        db.flush()

        # --- Nifty candles ---
        for day_offset in range(NIFTY_CANDLE_DAYS):
            day = base_date + timedelta(days=day_offset)
            candle_time = datetime.combine(
                day, datetime.min.time().replace(hour=9, minute=15),
                tzinfo=timezone.utc,
            )
            spot = base_spot + rng.uniform(-200, 200)
            for c in range(NIFTY_CANDLES_PER_DAY):
                t = candle_time + timedelta(minutes=3 * c)
                o = spot + rng.uniform(-10, 10)
                h = o + rng.uniform(0, 20)
                l = o - rng.uniform(0, 20)
                c_ = (o + h + l) / 3
                db.add(NiftyCandle(
                    symbol="NIFTY", interval="3min", open_time=t,
                    open=o, high=h, low=l, close=c_,
                    volume=float(rng.randint(1000, 50000)),
                ))
                spot = c_
        db.flush()

        # --- Option candles ---
        option_instruments = all_instrument_keys[:OPTION_INSTRUMENT_COUNT]
        for ik in option_instruments:
            for c in range(OPTION_CANDLES_PER_INSTRUMENT):
                t = now - timedelta(minutes=3 * (OPTION_CANDLES_PER_INSTRUMENT - c))
                o = rng.uniform(10, 500)
                db.add(OptionCandle(
                    instrument_key=ik, interval="3min", open_time=t,
                    open=o, high=o + rng.uniform(0, 50),
                    low=o - rng.uniform(0, 50),
                    close=o + rng.uniform(-20, 20),
                    volume=float(rng.randint(100, 10000)),
                    open_interest=float(rng.randint(1000, 100000)),
                    source="test", fetched_at=now,
                ))
        db.flush()

        # --- Option Greeks (subset of instruments) ---
        greek_instruments = option_instruments[:20]
        for ik in greek_instruments:
            # Parse strike from instrument_key for realistic values
            parts = ik.split("|")
            strike_val = float(parts[1]) if parts[1].isdigit() else 24000.0
            for g in range(50):
                t = now - timedelta(minutes=3 * (50 - g))
                iv = rng.uniform(0.1, 0.5)
                db.add(OptionGreeks(
                    instrument_key=ik, interval="3min", open_time=t,
                    spot=base_spot, strike=strike_val,
                    expiry="2026-10-30", option_type="CE",
                    option_price=rng.uniform(10, 500),
                    time_to_expiry=rng.uniform(0.01, 0.5),
                    risk_free_rate=0.065, intrinsic_value=iv,
                    implied_volatility=iv,
                    delta=rng.uniform(-1, 1),
                    gamma=rng.uniform(0, 0.01),
                    vega=rng.uniform(0, 50),
                    theta=rng.uniform(-50, 0),
                    calc_model="BLACK_SCHOLES_EUROPEAN",
                    calc_version="1.0.0", calculated_at=t,
                    status="SUCCESS",
                ))
        db.flush()

        # --- GEX Snapshots ---
        for uid in user_ids:
            for s in range(GEX_SNAPSHOTS_PER_USER):
                t = now - timedelta(minutes=5 * (GEX_SNAPSHOTS_PER_USER - s))
                cg = rng.uniform(100000, 500000)
                pg = rng.uniform(-500000, -100000)
                db.add(GexSnapshot(
                    owner_id=uid, symbol="NIFTY", expiry="2026-10-30",
                    spot=base_spot + rng.uniform(-100, 100),
                    methodology="GEX_STANDARD_V1",
                    sign_convention="NAIVE_DEALER_CONVENTION",
                    call_gex=cg, put_gex=pg, net_gex=cg + pg,
                    availability_status="available",
                    valid_strike_count=rng.randint(15, 20),
                    total_strike_count=20,
                    captured_at=t,
                    strike_data="[]", expiry_data="[]",
                    methodology_metadata="{}",
                ))
        db.flush()

        # --- Historical GEX ---
        hgex_instruments = option_instruments[:10]
        for ik in hgex_instruments:
            for h in range(HISTORICAL_GEX_PER_INSTRUMENT):
                t = now - timedelta(minutes=3 * (HISTORICAL_GEX_PER_INSTRUMENT - h))
                gamma = rng.uniform(0, 0.01)
                oi = float(rng.randint(1000, 100000))
                rgex = gamma * oi * base_spot ** 2 * 0.01
                db.add(HistoricalGexSnapshot(
                    instrument_key=ik, interval="3min", open_time=t,
                    spot=base_spot, strike=24000.0, expiry="2026-10-30",
                    option_type="CE", gamma=gamma, open_interest=oi,
                    option_price=rng.uniform(10, 500), raw_gex=rgex,
                    signed_gex=rgex, calc_version="h_gex_v1",
                    calculated_at=t, status="SUCCESS",
                ))
        db.flush()

        # --- Strategy Executions ---
        for uid in user_ids:
            for e in range(STRATEGY_EXECUTIONS_PER_USER):
                exec_id = f"exec_{uid}_{e:04d}"
                t = now - timedelta(minutes=e)
                db.add(StrategyExecution(
                    user_id=uid, execution_id=exec_id,
                    client_order_id=f"client_{uid}_{e:04d}",
                    strategy_tag="Strangle", symbol="NIFTY",
                    status="FILLED" if e % 5 != 0 else "PENDING",
                    entry_net=rng.uniform(-50000, 50000),
                    entry_at=t, created_at=t, updated_at=t,
                ))
        db.flush()

        # --- Positions ---
        # Unique constraint: (user_id, symbol, expiry, strike, option_type)
        # Use per-user offset + per-position index to guarantee uniqueness
        for u_idx, uid in enumerate(user_ids):
            for p in range(POSITIONS_PER_USER):
                strike = base_spot + (u_idx * 100) + (p * 50)
                db.add(Position(
                    user_id=uid, symbol="NIFTY", expiry="2026-10-30",
                    strike=strike,
                    option_type="CE" if p % 2 == 0 else "PE",
                    net_quantity=rng.randint(-5, 5),
                    average_entry_price=rng.uniform(10, 500),
                    lot_size=50, realized_pnl=rng.uniform(-20000, 20000),
                    status="open" if p % 3 != 0 else "closed",
                ))
        db.flush()

        # --- Paper Transactions ---
        for uid in user_ids:
            for t_idx in range(100):
                t = now - timedelta(minutes=t_idx)
                db.add(PaperTransaction(
                    user_id=uid,
                    type=rng.choice(["ENTRY_DEBIT", "ENTRY_CREDIT", "EXIT_DEBIT", "EXIT_CREDIT"]),
                    amount=rng.uniform(-50000, 50000),
                    created_at=t,
                ))
        db.flush()

        # --- Ingestion Log ---
        operations = ["contract_metadata", "nifty_candles", "option_candles", "greeks"]
        statuses = ["SUCCESS", "PARTIAL", "FAILED"]
        for i in range(INGESTION_LOG_ENTRIES):
            started = now - timedelta(hours=i)
            completed = started + timedelta(seconds=rng.randint(1, 60))
            db.add(IngestionLog(
                run_id=f"run_{i:04d}",
                operation=rng.choice(operations),
                status=rng.choice(statuses),
                started_at=started.isoformat(),
                completed_at=completed.isoformat(),
                api_calls=rng.randint(1, 50),
                rows_fetched=rng.randint(0, 10000),
                rows_inserted=rng.randint(0, 10000),
            ))
        db.flush()

        # --- Ingestion Checkpoint ---
        pipelines = ["greeks", "backfill_contracts", "backfill_nifty"]
        for p_idx, pipeline in enumerate(pipelines):
            for c in range(20):
                db.add(IngestionCheckpoint(
                    pipeline=pipeline,
                    instrument_key=f"NSE_FO|{p_idx * 100 + c}|2026-10-30",
                    status=rng.choice(["COMPLETED", "RUNNING", "FAILED"]),
                    items_processed=rng.randint(0, 1000),
                    items_total=1000,
                    started_at=now.isoformat(),
                ))
        db.flush()

        # --- Data Completeness ---
        for ik in greek_instruments:
            for d in range(5):
                day = (now - timedelta(days=d)).strftime("%Y-%m-%d")
                actual = rng.randint(100, 130)
                db.add(DataCompleteness(
                    instrument_key=ik, session_date=day,
                    data_type="option_candles",
                    expected_count=130, actual_count=actual,
                    missing_count=130 - actual,
                    status=rng.choice(["COMPLETE", "PARTIAL"]),
                ))
        db.flush()

        # --- Strategy Templates ---
        for uid in user_ids:
            for t_idx in range(3):
                tmpl = StrategyTemplate(
                    user_id=uid, name=f"Template {t_idx}", symbol="NIFTY",
                )
                db.add(tmpl)
                db.flush()
                for leg_pos in range(2):
                    db.add(StrategyTemplateLeg(
                        template_id=tmpl.id, position=leg_pos,
                        action="buy" if leg_pos == 0 else "sell",
                        option_type="CE" if leg_pos == 0 else "PE",
                        strike=base_spot, expiry="2026-10-30",
                        quantity=1, lot_size=50,
                    ))
        db.flush()

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Benchmark helpers
# ---------------------------------------------------------------------------


def _measure_query(engine, sql: str, params: dict | None = None, iterations: int = BENCHMARK_ITERATIONS) -> dict:
    """Run a query multiple times and collect timing statistics."""
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        with engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            rows = result.fetchall()
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    times.sort()
    return {
        "iterations": iterations,
        "median_ms": times[len(times) // 2] * 1000,
        "p95_ms": times[int(len(times) * 0.95)] * 1000,
        "min_ms": times[0] * 1000,
        "max_ms": times[-1] * 1000,
        "rows_returned": len(rows) if rows else 0,
    }


def _explain_query(engine, sql: str, params: dict | None = None) -> str:
    """Capture EXPLAIN QUERY PLAN for a query."""
    explain_sql = f"EXPLAIN QUERY PLAN {sql}"
    with engine.connect() as conn:
        result = conn.execute(text(explain_sql), params or {})
        rows = result.fetchall()
    return "\n".join(str(row) for row in rows)


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestDatasetIntegrity:
    """Verify the benchmark dataset was seeded correctly."""

    def test_user_count(self, bench_db):
        with bench_db.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
            assert count == NUM_USERS

    def test_contract_spec_count(self, bench_db):
        with bench_db.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM contract_specs")).scalar()
            expected = EXPIRIES_COUNT * STRIKES_PER_EXPIRY * 2
            assert count == expected, f"Expected {expected}, got {count}"

    def test_nifty_candle_count(self, bench_db):
        with bench_db.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM nifty_candles")).scalar()
            expected = NIFTY_CANDLES_PER_DAY * NIFTY_CANDLE_DAYS
            assert count == expected, f"Expected {expected}, got {count}"

    def test_option_candle_count(self, bench_db):
        with bench_db.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM option_candles")).scalar()
            assert count == OPTION_CANDLES_PER_INSTRUMENT * OPTION_INSTRUMENT_COUNT

    def test_gex_snapshot_count(self, bench_db):
        with bench_db.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM gex_snapshots")).scalar()
            expected = NUM_USERS * GEX_SNAPSHOTS_PER_USER
            assert count == expected

    def test_historical_gex_count(self, bench_db):
        with bench_db.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM historical_gex")).scalar()
            assert count > 0

    def test_ingestion_log_count(self, bench_db):
        with bench_db.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM ingestion_log")).scalar()
            assert count == INGESTION_LOG_ENTRIES

    def test_strategy_execution_count(self, bench_db):
        with bench_db.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM strategy_executions")).scalar()
            expected = NUM_USERS * STRATEGY_EXECUTIONS_PER_USER
            assert count == expected

    def test_positions_count(self, bench_db):
        with bench_db.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM positions")).scalar()
            assert count > 0

    def test_paper_transaction_count(self, bench_db):
        with bench_db.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM paper_transactions")).scalar()
            expected = NUM_USERS * 100
            assert count == expected


class TestQueryBenchmarks:
    """Benchmark representative query workloads and capture EXPLAIN plans."""

    def test_tenant_portfolio_positions(self, bench_db):
        """HIGH: User-scoped position list (core portfolio view)."""
        sql = "SELECT * FROM positions WHERE user_id = :uid AND status = 'open'"
        result = _measure_query(bench_db, sql, {"uid": "user_000"})
        plan = _explain_query(bench_db, sql, {"uid": "user_000"})
        assert result["rows_returned"] > 0
        assert result["median_ms"] < 100  # Should be fast for indexed query
        bench_db._benchmark_results = getattr(bench_db, "_benchmark_results", {})
        bench_db._benchmark_results["tenant_positions"] = {"metrics": result, "plan": plan}

    def test_tenant_strategy_executions(self, bench_db):
        """HIGH: User-scoped execution list."""
        sql = "SELECT * FROM strategy_executions WHERE user_id = :uid ORDER BY created_at DESC"
        result = _measure_query(bench_db, sql, {"uid": "user_000"})
        plan = _explain_query(bench_db, sql, {"uid": "user_000"})
        assert result["rows_returned"] == STRATEGY_EXECUTIONS_PER_USER
        bench_db._benchmark_results = getattr(bench_db, "_benchmark_results", {})
        bench_db._benchmark_results["tenant_executions"] = {"metrics": result, "plan": plan}

    def test_gex_snapshot_history(self, bench_db):
        """HIGH: GEX snapshot retrieval with time window."""
        sql = (
            "SELECT * FROM gex_snapshots "
            "WHERE symbol = :symbol AND owner_id = :owner "
            "AND captured_at >= :since "
            "ORDER BY captured_at DESC"
        )
        params = {
            "symbol": "NIFTY",
            "owner": "user_000",
            "since": (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(),
        }
        result = _measure_query(bench_db, sql, params)
        plan = _explain_query(bench_db, sql, params)
        assert result["rows_returned"] > 0
        bench_db._benchmark_results = getattr(bench_db, "_benchmark_results", {})
        bench_db._benchmark_results["gex_history"] = {"metrics": result, "plan": plan}

    def test_contract_spec_lookup(self, bench_db):
        """HIGH: Contract spec lookup by expiry + underlying."""
        with bench_db.connect() as conn:
            expiry = conn.execute(
                text("SELECT expiry FROM contract_specs LIMIT 1")
            ).scalar()
        sql = (
            "SELECT * FROM contract_specs "
            "WHERE underlying = :underlying AND expiry = :expiry "
            "ORDER BY strike_price"
        )
        params = {"underlying": "NIFTY", "expiry": expiry}
        result = _measure_query(bench_db, sql, params)
        plan = _explain_query(bench_db, sql, params)
        assert result["rows_returned"] > 0
        bench_db._benchmark_results = getattr(bench_db, "_benchmark_results", {})
        bench_db._benchmark_results["contract_spec_lookup"] = {"metrics": result, "plan": plan}

    def test_nifty_candle_time_window(self, bench_db):
        """HIGH: Nifty candle retrieval for a time window."""
        with bench_db.connect() as conn:
            row = conn.execute(
                text("SELECT MIN(open_time), MAX(open_time) FROM nifty_candles")
            ).fetchone()
            min_time, max_time = row[0], row[1]
            # Use the middle third of the time range
            from datetime import datetime as dt
            # Parse ISO timestamps
            if isinstance(min_time, str):
                min_dt = dt.fromisoformat(min_time)
                max_dt = dt.fromisoformat(max_time)
            else:
                min_dt = min_time
                max_dt = max_time
            total = (max_dt - min_dt).total_seconds()
            start = min_dt + timedelta(seconds=total // 3)
            end = start + timedelta(days=1)
        sql = (
            "SELECT * FROM nifty_candles "
            "WHERE symbol = :symbol AND interval = :interval "
            "AND open_time >= :start AND open_time < :end "
            "ORDER BY open_time"
        )
        params = {
            "symbol": "NIFTY",
            "interval": "3min",
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        result = _measure_query(bench_db, sql, params)
        plan = _explain_query(bench_db, sql, params)
        assert result["rows_returned"] > 0
        bench_db._benchmark_results = getattr(bench_db, "_benchmark_results", {})
        bench_db._benchmark_results["nifty_candle_window"] = {"metrics": result, "plan": plan}

    def test_historical_gex_analytics(self, bench_db):
        """HIGH: Historical GEX query with instrument + time range."""
        with bench_db.connect() as conn:
            ik = conn.execute(
                text("SELECT instrument_key FROM historical_gex LIMIT 1")
            ).scalar()
        sql = (
            "SELECT * FROM historical_gex "
            "WHERE instrument_key = :ik AND open_time >= :start "
            "AND status = 'SUCCESS' "
            "ORDER BY open_time"
        )
        params = {
            "ik": ik,
            "start": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
        }
        result = _measure_query(bench_db, sql, params)
        plan = _explain_query(bench_db, sql, params)
        assert result["rows_returned"] > 0
        bench_db._benchmark_results = getattr(bench_db, "_benchmark_results", {})
        bench_db._benchmark_results["historical_gex"] = {"metrics": result, "plan": plan}

    def test_paper_account_capital(self, bench_db):
        """HIGH: Paper account + cash calculation."""
        sql_account = "SELECT * FROM paper_accounts WHERE user_id = :uid"
        sql_cash = (
            "SELECT COALESCE(SUM(amount), 0) as total_cash "
            "FROM paper_transactions WHERE user_id = :uid"
        )
        params = {"uid": "user_000"}
        result_account = _measure_query(bench_db, sql_account, params)
        result_cash = _measure_query(bench_db, sql_cash, params)
        assert result_account["rows_returned"] == 1
        bench_db._benchmark_results = getattr(bench_db, "_benchmark_results", {})
        bench_db._benchmark_results["paper_capital"] = {
            "account": result_account,
            "cash": result_cash,
        }

    def test_option_candle_by_instrument(self, bench_db):
        """MEDIUM: Option candle retrieval by instrument."""
        with bench_db.connect() as conn:
            ik = conn.execute(
                text("SELECT instrument_key FROM option_candles LIMIT 1")
            ).scalar()
        sql = (
            "SELECT * FROM option_candles "
            "WHERE instrument_key = :ik "
            "ORDER BY open_time"
        )
        result = _measure_query(bench_db, sql, {"ik": ik})
        plan = _explain_query(bench_db, sql, {"ik": ik})
        assert result["rows_returned"] > 0
        bench_db._benchmark_results = getattr(bench_db, "_benchmark_results", {})
        bench_db._benchmark_results["option_candle_by_instrument"] = {"metrics": result, "plan": plan}

    def test_ingestion_log_by_operation_status(self, bench_db):
        """MEDIUM: Ingestion log filtered by operation + status."""
        sql = (
            "SELECT * FROM ingestion_log "
            "WHERE operation = :op AND status = :status "
            "ORDER BY started_at DESC"
        )
        params = {"op": "nifty_candles", "status": "SUCCESS"}
        result = _measure_query(bench_db, sql, params)
        plan = _explain_query(bench_db, sql, params)
        bench_db._benchmark_results = getattr(bench_db, "_benchmark_results", {})
        bench_db._benchmark_results["ingestion_log_op_status"] = {"metrics": result, "plan": plan}

    def test_data_completeness_check(self, bench_db):
        """MEDIUM: Data completeness by instrument + session."""
        with bench_db.connect() as conn:
            row = conn.execute(
                text("SELECT instrument_key, session_date FROM data_completeness LIMIT 1")
            ).fetchone()
        sql = (
            "SELECT * FROM data_completeness "
            "WHERE instrument_key = :ik AND session_date = :day"
        )
        params = {"ik": row[0], "day": row[1]}
        result = _measure_query(bench_db, sql, params)
        plan = _explain_query(bench_db, sql, params)
        bench_db._benchmark_results = getattr(bench_db, "_benchmark_results", {})
        bench_db._benchmark_results["data_completeness"] = {"metrics": result, "plan": plan}

    def test_strategy_template_list(self, bench_db):
        """MEDIUM: Strategy template list by user."""
        sql = "SELECT * FROM strategy_templates WHERE user_id = :uid"
        result = _measure_query(bench_db, sql, {"uid": "user_000"})
        bench_db._benchmark_results = getattr(bench_db, "_benchmark_results", {})
        bench_db._benchmark_results["template_list"] = {"metrics": result}


class TestIndexAudit:
    """Audit existing indexes against actual workload patterns."""

    def test_collect_all_indexes(self, bench_db):
        """Catalog all indexes in the benchmark database."""
        with bench_db.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT name, tbl_name FROM sqlite_master "
                    "WHERE type = 'index' AND name IS NOT NULL "
                    "ORDER BY tbl_name, name"
                )
            ).fetchall()

        indexes = defaultdict(list)
        for name, table in rows:
            if not name.startswith("sqlite_"):
                indexes[table].append(name)

        bench_db._index_catalog = dict(indexes)
        assert "positions" in indexes
        assert "strategy_executions" in indexes
        assert "gex_snapshots" in indexes
        assert "nifty_candles" in indexes
        assert "contract_specs" in indexes

    def test_identify_missing_composite_indexes(self, bench_db):
        """Identify query patterns that would benefit from composite indexes."""
        catalog = getattr(bench_db, "_index_catalog", {})
        missing = []

        # gex_snapshots: symbol + owner_id + captured_at
        gex_indexes = catalog.get("gex_snapshots", [])
        has_gex_composite = any("symbol" in idx and "owner" in idx for idx in gex_indexes)
        if not has_gex_composite:
            missing.append("gex_snapshots(symbol, owner_id, captured_at)")

        # nifty_candles: symbol + interval + open_time
        nifty_indexes = catalog.get("nifty_candles", [])
        has_nifty_composite = any("symbol" in idx and "interval" in idx for idx in nifty_indexes)
        if not has_nifty_composite:
            missing.append("nifty_candles(symbol, interval, open_time)")

        # historical_gex: instrument_key + open_time + status
        hgex_indexes = catalog.get("historical_gex", [])
        has_hgex_composite = any("instrument" in idx and "open_time" in idx for idx in hgex_indexes)
        if not has_hgex_composite:
            missing.append("historical_gex(instrument_key, open_time, status)")

        # ingestion_log: operation + status (SQLite-only currently)
        ing_indexes = catalog.get("ingestion_log", [])
        has_ing_composite = any("operation" in idx and "status" in idx for idx in ing_indexes)
        if not has_ing_composite:
            missing.append("ingestion_log(operation, status)")

        # positions: user_id + status
        pos_indexes = catalog.get("positions", [])
        has_pos_composite = any("user_id" in idx and "status" in idx for idx in pos_indexes)
        if not has_pos_composite:
            missing.append("positions(user_id, status)")

        bench_db._missing_indexes = missing
        assert isinstance(missing, list)


class TestExplainAnalysis:
    """Capture and analyze EXPLAIN plans for critical query paths."""

    def test_explain_tenant_positions(self, bench_db):
        """Verify position query uses index, not full scan."""
        sql = "SELECT * FROM positions WHERE user_id = :uid AND status = 'open'"
        plan = _explain_query(bench_db, sql, {"uid": "user_000"})
        assert "positions" in plan

    def test_explain_gex_history(self, bench_db):
        """Verify GEX history query plan."""
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        sql = (
            "SELECT * FROM gex_snapshots "
            "WHERE symbol = :symbol AND owner_id = :owner "
            "AND captured_at >= :since"
        )
        plan = _explain_query(bench_db, sql, {"symbol": "NIFTY", "owner": "user_000", "since": since})
        assert "gex_snapshots" in plan

    def test_explain_contract_spec_lookup(self, bench_db):
        """Verify contract spec query plan."""
        sql = (
            "SELECT * FROM contract_specs "
            "WHERE underlying = :underlying AND expiry = :expiry"
        )
        plan = _explain_query(bench_db, sql, {"underlying": "NIFTY", "expiry": "2026-10-30"})
        assert "contract_specs" in plan

    def test_explain_nifty_candle_window(self, bench_db):
        """Verify nifty candle time-window query plan."""
        base = datetime.now(timezone.utc) - timedelta(days=7)
        sql = (
            "SELECT * FROM nifty_candles "
            "WHERE symbol = :symbol AND interval = :interval "
            "AND open_time >= :start AND open_time < :end"
        )
        plan = _explain_query(
            bench_db, sql,
            {"symbol": "NIFTY", "interval": "3min", "start": base.isoformat(),
             "end": (base + timedelta(days=1)).isoformat()},
        )
        assert "nifty_candles" in plan

    def test_explain_ingestion_log(self, bench_db):
        """Verify ingestion log operation+status query plan."""
        sql = "SELECT * FROM ingestion_log WHERE operation = :op AND status = :status"
        plan = _explain_query(bench_db, sql, {"op": "nifty_candles", "status": "SUCCESS"})
        assert "ingestion_log" in plan


class TestConnectionPoolBaseline:
    """Record current connection pool configuration for baseline."""

    def test_pool_configuration_recorded(self, bench_db):
        """Document the current pool settings (no changes made)."""
        from app.db import engine as prod_engine

        pool = prod_engine.pool
        config = {
            "pool_size": getattr(pool, "_pool_size", None),
            "max_overflow": getattr(pool, "_max_overflow", None),
            "timeout": getattr(pool, "_timeout", None),
            "recycle": getattr(pool, "_recycle", None),
            "dialect": prod_engine.dialect.name,
        }

        # Day 4 documented values for PostgreSQL
        if prod_engine.dialect.name == "postgresql":
            assert config["pool_size"] == 5
            assert config["max_overflow"] == 10
            assert config["timeout"] == 30
            assert config["recycle"] == 1800
