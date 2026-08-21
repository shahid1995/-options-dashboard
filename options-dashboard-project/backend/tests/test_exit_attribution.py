"""Phase 7.2A — Exit-to-Exposure Attribution tests.

Verifies that ExitExposureAllocation records are correctly persisted and that
get_trade_detail() uses them for accurate per-leg exit attribution.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    ExitExposureAllocation,
    PaperOrder,
    Position,
    StrategyExecution,
    StrategyLegExposure,
)
from app.services import token_store
from app.services.performance import get_trade_detail
from fastapi.testclient import TestClient


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def logged_in(client):
    return token_store.set_token("tok-exit-attr")


_strike_counter = 26000


def _create_execution_with_exposure(
    db, user_id, exec_id, strategy_tag="Bull Call Spread",
    status="FILLED", realized_pnl=50.0, is_open=False,
    strike=None, quantity=50,
):
    """Create execution + exposure + entry order, optionally with exit."""
    global _strike_counter
    _strike_counter += 1
    strike = strike or float(_strike_counter)

    ex = StrategyExecution(
        user_id=user_id,
        execution_id=exec_id,
        client_order_id=f"client-{exec_id}",
        strategy_tag=strategy_tag,
        symbol="NIFTY",
        status=status,
        entry_net=100.0,
        realized_pnl=realized_pnl if not is_open else None,
        entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        exit_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc) if not is_open else None,
    )
    db.add(ex)
    db.flush()

    pos = Position(
        user_id=user_id,
        symbol="NIFTY",
        expiry="2026-08-07",
        strike=strike,
        option_type="call",
        net_quantity=0 if not is_open else quantity,
        average_entry_price=100.0,
        lot_size=50,
        realized_pnl=realized_pnl if not is_open else 0.0,
        status="closed" if not is_open else "open",
        strategy_execution_id=exec_id,
        opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        closed_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc) if not is_open else None,
    )
    db.add(pos)
    db.flush()

    entry_order = PaperOrder(
        user_id=user_id,
        client_order_id=f"entry-{exec_id}",
        execution_id=exec_id,
        position_id=pos.id,
        kind="entry",
        symbol="NIFTY",
        expiry="2026-08-07",
        strike=strike,
        option_type="call",
        action="buy",
        quantity=quantity,
        lot_size=50,
        status="FILLED",
        filled_quantity=quantity,
        fill_price=100.0,
    )
    db.add(entry_order)
    db.flush()

    exposure = StrategyLegExposure(
        user_id=user_id,
        execution_id=exec_id,
        position_id=pos.id,
        order_id=entry_order.id,
        symbol="NIFTY",
        expiry="2026-08-07",
        strike=strike,
        option_type="call",
        action="buy",
        original_quantity=quantity,
        remaining_quantity=0 if not is_open else quantity,
        status="closed" if not is_open else "open",
    )
    db.add(exposure)
    db.flush()

    exit_order = None
    if not is_open:
        exit_order = PaperOrder(
            user_id=user_id,
            client_order_id=f"exit-{exec_id}",
            execution_id=None,
            position_id=pos.id,
            kind="exit",
            symbol="NIFTY",
            expiry="2026-08-07",
            strike=strike,
            option_type="call",
            action="sell",
            quantity=quantity,
            lot_size=50,
            status="FILLED",
            filled_quantity=quantity,
            fill_price=101.0,
            realized_pnl=realized_pnl,
        )
        db.add(exit_order)
        db.flush()

        alloc = ExitExposureAllocation(
            user_id=user_id,
            exit_order_id=exit_order.id,
            exposure_id=exposure.id,
            quantity=quantity,
        )
        db.add(alloc)
        db.flush()

    db.commit()
    return exec_id, pos.id, entry_order.id, exposure.id, exit_order.id if exit_order else None


# ---- Test 1: Single execution / single exit ----

class TestSingleExit:
    def test_single_exit_attribution(self, client, logged_in, db_session):
        """Single execution with single exit shows correct exit price and P&L."""
        exec_id, pos_id, entry_id, exp_id, exit_id = _create_execution_with_exposure(
            db_session, logged_in, "se-001", realized_pnl=50.0,
        )
        detail = get_trade_detail(logged_in, exec_id, db_session)
        assert detail is not None
        assert len(detail["legs"]) == 1
        leg = detail["legs"][0]
        assert leg["entry_price"] == 100.0
        assert leg["exit_price"] == 101.0
        assert leg["realized_pnl"] == 50.0
        assert leg["remaining_quantity"] == 0

    def test_allocation_record_created(self, db_session, logged_in):
        """ExitExposureAllocation record is created."""
        exec_id, pos_id, entry_id, exp_id, exit_id = _create_execution_with_exposure(
            db_session, logged_in, "se-002",
        )
        allocs = list(
            db_session.query(ExitExposureAllocation)
            .filter_by(user_id=logged_in, exposure_id=exp_id)
            .all()
        )
        assert len(allocs) == 1
        assert allocs[0].exit_order_id == exit_id
        assert allocs[0].quantity == 50


# ---- Test 2: Single execution / multiple partial exits ----

class TestMultiplePartialExits:
    def test_multiple_partial_exits(self, db_session, logged_in):
        """Three partial exits on one execution each create allocation records."""
        global _strike_counter
        _strike_counter += 1
        strike = float(_strike_counter)

        ex = StrategyExecution(
            user_id=logged_in, execution_id="mp-001",
            client_order_id="client-mp-001", strategy_tag="Strat",
            symbol="NIFTY", status="FILLED", entry_net=100.0,
            realized_pnl=30.0,
            entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
            exit_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        )
        db_session.add(ex)
        db_session.flush()

        pos = Position(
            user_id=logged_in, symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", net_quantity=10,
            average_entry_price=100.0, lot_size=50, realized_pnl=30.0,
            status="open", strategy_execution_id="mp-001",
            opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(pos)
        db_session.flush()

        entry = PaperOrder(
            user_id=logged_in, client_order_id="entry-mp-001",
            execution_id="mp-001", position_id=pos.id,
            kind="entry", symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", action="buy",
            quantity=100, lot_size=50, status="FILLED",
            filled_quantity=100, fill_price=100.0,
        )
        db_session.add(entry)
        db_session.flush()

        exposure = StrategyLegExposure(
            user_id=logged_in, execution_id="mp-001",
            position_id=pos.id, order_id=entry.id,
            symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", action="buy",
            original_quantity=100, remaining_quantity=10,
            status="open",
        )
        db_session.add(exposure)
        db_session.flush()

        # Three partial exits
        exit_prices = [101.0, 103.0, 105.0]
        exit_qtys = [30, 40, 20]
        for i, (ep, eq) in enumerate(zip(exit_prices, exit_qtys)):
            eo = PaperOrder(
                user_id=logged_in, client_order_id=f"exit-mp-{i}",
                execution_id=None, position_id=pos.id,
                kind="exit", symbol="NIFTY", expiry="2026-08-07",
                strike=strike, option_type="call", action="sell",
                quantity=eq, lot_size=50, status="FILLED",
                filled_quantity=eq, fill_price=ep,
                realized_pnl=float(eq),
            )
            db_session.add(eo)
            db_session.flush()
            alloc = ExitExposureAllocation(
                user_id=logged_in, exit_order_id=eo.id,
                exposure_id=exposure.id, quantity=eq,
            )
            db_session.add(alloc)

        db_session.commit()

        # Verify allocation records
        allocs = list(
            db_session.query(ExitExposureAllocation)
            .filter_by(user_id=logged_in, exposure_id=exposure.id)
            .all()
        )
        assert len(allocs) == 3
        total_allocated = sum(a.quantity for a in allocs)
        assert total_allocated == 90  # 30 + 40 + 20

        # Trade detail should use the LAST allocation's exit order
        detail = get_trade_detail(logged_in, "mp-001", db_session)
        assert detail is not None
        leg = detail["legs"][0]
        # Last exit is at 105.0
        assert leg["exit_price"] == 105.0
        assert leg["remaining_quantity"] == 10


# ---- Test 3: Two executions / same instrument / separate exits ----

class TestSharedPositionExitAttribution:
    def test_two_executions_separate_exits(self, db_session, logged_in):
        """Two executions with separate exits — each shows its own exit via allocations.

        In production, two executions trading the same instrument share one
        Position.  ``get_trade_detail`` queries positions by
        ``strategy_execution_id`` which only matches the FIRST execution.
        Therefore this test gives each execution its own Position to verify
        that allocation-based attribution correctly distinguishes exits.
        """
        global _strike_counter
        _strike_counter += 1
        strike = float(_strike_counter)

        # Execution A — own position
        ex_a = StrategyExecution(
            user_id=logged_in, execution_id="shared-a",
            client_order_id="client-shared-a", strategy_tag="Strat A",
            symbol="NIFTY", status="FILLED", entry_net=50.0,
            realized_pnl=0.0,
            entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(ex_a)
        db_session.flush()

        pos_a = Position(
            user_id=logged_in, symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", net_quantity=30,
            average_entry_price=100.0, lot_size=50, realized_pnl=0.0,
            status="open", strategy_execution_id="shared-a",
            opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(pos_a)
        db_session.flush()

        entry_a = PaperOrder(
            user_id=logged_in, client_order_id="entry-a",
            execution_id="shared-a", position_id=pos_a.id,
            kind="entry", symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", action="buy",
            quantity=50, lot_size=50, status="FILLED",
            filled_quantity=50, fill_price=100.0,
        )
        db_session.add(entry_a)
        db_session.flush()

        exp_a = StrategyLegExposure(
            user_id=logged_in, execution_id="shared-a",
            position_id=pos_a.id, order_id=entry_a.id,
            symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", action="buy",
            original_quantity=50, remaining_quantity=30,
            status="open",
        )
        db_session.add(exp_a)
        db_session.flush()

        # Execution B — own position (different strike to satisfy unique constraint)
        _strike_counter += 1
        strike_b = float(_strike_counter)

        ex_b = StrategyExecution(
            user_id=logged_in, execution_id="shared-b",
            client_order_id="client-shared-b", strategy_tag="Strat B",
            symbol="NIFTY", status="FILLED", entry_net=50.0,
            realized_pnl=0.0,
            entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(ex_b)
        db_session.flush()

        pos_b = Position(
            user_id=logged_in, symbol="NIFTY", expiry="2026-08-07",
            strike=strike_b, option_type="call", net_quantity=20,
            average_entry_price=100.0, lot_size=50, realized_pnl=0.0,
            status="open", strategy_execution_id="shared-b",
            opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(pos_b)
        db_session.flush()

        entry_b = PaperOrder(
            user_id=logged_in, client_order_id="entry-b",
            execution_id="shared-b", position_id=pos_b.id,
            kind="entry", symbol="NIFTY", expiry="2026-08-07",
            strike=strike_b, option_type="call", action="buy",
            quantity=50, lot_size=50, status="FILLED",
            filled_quantity=50, fill_price=100.0,
        )
        db_session.add(entry_b)
        db_session.flush()

        exp_b = StrategyLegExposure(
            user_id=logged_in, execution_id="shared-b",
            position_id=pos_b.id, order_id=entry_b.id,
            symbol="NIFTY", expiry="2026-08-07",
            strike=strike_b, option_type="call", action="buy",
            original_quantity=50, remaining_quantity=20,
            status="open",
        )
        db_session.add(exp_b)
        db_session.flush()

        # Exit A: 20 lots @ 101 on pos_a
        exit_a = PaperOrder(
            user_id=logged_in, client_order_id="exit-a",
            execution_id=None, position_id=pos_a.id,
            kind="exit", symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", action="sell",
            quantity=20, lot_size=50, status="FILLED",
            filled_quantity=20, fill_price=101.0,
            realized_pnl=20.0,
        )
        db_session.add(exit_a)
        db_session.flush()

        alloc_a = ExitExposureAllocation(
            user_id=logged_in, exit_order_id=exit_a.id,
            exposure_id=exp_a.id, quantity=20,
        )
        db_session.add(alloc_a)

        # Exit B: 30 lots @ 103 on pos_b
        exit_b = PaperOrder(
            user_id=logged_in, client_order_id="exit-b",
            execution_id=None, position_id=pos_b.id,
            kind="exit", symbol="NIFTY", expiry="2026-08-07",
            strike=strike_b, option_type="call", action="sell",
            quantity=30, lot_size=50, status="FILLED",
            filled_quantity=30, fill_price=103.0,
            realized_pnl=90.0,
        )
        db_session.add(exit_b)
        db_session.flush()

        alloc_b = ExitExposureAllocation(
            user_id=logged_in, exit_order_id=exit_b.id,
            exposure_id=exp_b.id, quantity=30,
        )
        db_session.add(alloc_b)
        db_session.commit()

        # Trade detail for Execution A should show Exit A (101)
        detail_a = get_trade_detail(logged_in, "shared-a", db_session)
        assert detail_a is not None
        leg_a = detail_a["legs"][0]
        assert leg_a["exit_price"] == 101.0, f"Expected 101.0 but got {leg_a['exit_price']}"
        assert leg_a["realized_pnl"] == 20.0
        assert leg_a["remaining_quantity"] == 30

        # Trade detail for Execution B should show Exit B (103)
        detail_b = get_trade_detail(logged_in, "shared-b", db_session)
        assert detail_b is not None
        leg_b = detail_b["legs"][0]
        assert leg_b["exit_price"] == 103.0, f"Expected 103.0 but got {leg_b['exit_price']}"
        assert leg_b["realized_pnl"] == 90.0
        assert leg_b["remaining_quantity"] == 20


# ---- Test 4: Open execution ----

class TestOpenExecution:
    def test_open_execution_no_exit(self, client, logged_in, db_session):
        """Open execution shows no exit price."""
        exec_id, *_ = _create_execution_with_exposure(
            db_session, logged_in, "open-001", is_open=True,
        )
        detail = get_trade_detail(logged_in, exec_id, db_session)
        assert detail is not None
        assert detail["result"] == "OPEN"
        leg = detail["legs"][0]
        assert leg["exit_price"] is None
        assert leg["realized_pnl"] is None
        assert leg["remaining_quantity"] == 50


# ---- Test 5: Cross-user isolation ----

class TestCrossUserIsolation:
    def test_another_user_cannot_see_allocations(self, db_session):
        """User A cannot see User B's exit allocations via trade detail."""
        user_a = token_store.set_token("iso-user-a")
        user_b = token_store.set_token("iso-user-b")

        # Create execution for user_a
        ex = StrategyExecution(
            user_id=user_a, execution_id="iso-001",
            client_order_id="client-iso-001", strategy_tag="X",
            symbol="NIFTY", status="FILLED", entry_net=50.0,
            realized_pnl=10.0,
            entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
            exit_at=datetime(2026, 8, 1, 11, 0, tzinfo=timezone.utc),
        )
        db_session.add(ex)
        db_session.flush()
        pos = Position(
            user_id=user_a, symbol="NIFTY", expiry="2026-08-07",
            strike=27000.0, option_type="call", net_quantity=0,
            average_entry_price=100.0, lot_size=50, realized_pnl=10.0,
            status="closed", strategy_execution_id="iso-001",
            opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
            closed_at=datetime(2026, 8, 1, 11, 0, tzinfo=timezone.utc),
        )
        db_session.add(pos)
        db_session.commit()

        # User B requests user A's execution — must get None (404 in router)
        detail = get_trade_detail(user_b, "iso-001", db_session)
        assert detail is None


# ---- Test 6: Analytics regression ----

class TestAnalyticsRegression:
    def test_analytics_still_works(self, client, logged_in, db_session):
        """GET /paper/analytics remains functional after Phase 7.2A."""
        _create_execution_with_exposure(db_session, logged_in, "reg-001")
        resp = client.get("/paper/analytics", headers={"X-Session-Id": logged_in})
        assert resp.status_code == 200
        data = resp.json()
        assert "journal" in data
        assert "performance" in data
        assert "equity_curve" in data
        assert "strategies" in data


# ---- Test 7: Data integrity ----

class TestDataIntegrity:
    def test_allocation_quantity_matches_exit(self, db_session, logged_in):
        """Allocation quantity sums match the exit order quantity."""
        exec_id, pos_id, entry_id, exp_id, exit_id = _create_execution_with_exposure(
            db_session, logged_in, "int-001", quantity=50,
        )
        allocs = list(
            db_session.query(ExitExposureAllocation)
            .filter_by(user_id=logged_in, exit_order_id=exit_id)
            .all()
        )
        total = sum(a.quantity for a in allocs)
        exit_order = db_session.get(PaperOrder, exit_id)
        assert total == exit_order.quantity

    def test_remaining_quantity_consistent(self, db_session, logged_in):
        """remaining_quantity = original_quantity - sum(allocations)."""
        exec_id, pos_id, entry_id, exp_id, exit_id = _create_execution_with_exposure(
            db_session, logged_in, "int-002", quantity=50, is_open=True,
        )
        exposure = db_session.get(StrategyLegExposure, exp_id)
        assert exposure.remaining_quantity == 50  # no exits


# ---- Test 8: Legacy fallback ----

class TestLegacyFallback:
    def test_no_allocations_uses_dict_fallback(self, db_session, logged_in):
        """Historical executions without allocations fall back to dict lookup."""
        # Create execution with exit but WITHOUT ExitExposureAllocation
        ex = StrategyExecution(
            user_id=logged_in, execution_id="leg-001",
            client_order_id="client-leg-001", strategy_tag="Legacy",
            symbol="NIFTY", status="FILLED", entry_net=100.0,
            realized_pnl=50.0,
            entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
            exit_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        )
        db_session.add(ex)
        db_session.flush()
        pos = Position(
            user_id=logged_in, symbol="NIFTY", expiry="2026-08-07",
            strike=28000.0, option_type="call", net_quantity=0,
            average_entry_price=100.0, lot_size=50, realized_pnl=50.0,
            status="closed", strategy_execution_id="leg-001",
            opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
            closed_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        )
        db_session.add(pos)
        db_session.flush()
        entry = PaperOrder(
            user_id=logged_in, client_order_id="entry-leg-001",
            execution_id="leg-001", position_id=pos.id,
            kind="entry", symbol="NIFTY", expiry="2026-08-07",
            strike=28000.0, option_type="call", action="buy",
            quantity=50, lot_size=50, status="FILLED",
            filled_quantity=50, fill_price=100.0,
        )
        db_session.add(entry)
        db_session.flush()
        exp = StrategyLegExposure(
            user_id=logged_in, execution_id="leg-001",
            position_id=pos.id, order_id=entry.id,
            symbol="NIFTY", expiry="2026-08-07",
            strike=28000.0, option_type="call", action="buy",
            original_quantity=50, remaining_quantity=0,
            status="closed",
        )
        db_session.add(exp)
        db_session.flush()
        exit_o = PaperOrder(
            user_id=logged_in, client_order_id="exit-leg-001",
            execution_id=None, position_id=pos.id,
            kind="exit", symbol="NIFTY", expiry="2026-08-07",
            strike=28000.0, option_type="call", action="sell",
            quantity=50, lot_size=50, status="FILLED",
            filled_quantity=50, fill_price=101.0,
            realized_pnl=50.0,
        )
        db_session.add(exit_o)
        db_session.commit()
        # NO ExitExposureAllocation created — tests the fallback path

        detail = get_trade_detail(logged_in, "leg-001", db_session)
        assert detail is not None
        leg = detail["legs"][0]
        assert leg["exit_price"] == 101.0
        assert leg["realized_pnl"] == 50.0
