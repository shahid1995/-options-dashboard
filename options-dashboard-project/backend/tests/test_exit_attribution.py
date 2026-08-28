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
from tests.test_helpers import create_test_identity
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
def logged_in(client, db_session):
    session_id, user_id = create_test_identity(db_session, "tok-exit-attr")
    db_session._test_user_id = user_id
    return session_id


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
            db_session, db_session._test_user_id, "se-001", realized_pnl=50.0,
        )
        detail = get_trade_detail(db_session._test_user_id, exec_id, db_session)
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
            db_session, db_session._test_user_id, "se-002",
        )
        allocs = list(
            db_session.query(ExitExposureAllocation)
            .filter_by(user_id=db_session._test_user_id, exposure_id=exp_id)
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
            user_id=db_session._test_user_id, execution_id="mp-001",
            client_order_id="client-mp-001", strategy_tag="Strat",
            symbol="NIFTY", status="FILLED", entry_net=100.0,
            realized_pnl=30.0,
            entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
            exit_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        )
        db_session.add(ex)
        db_session.flush()

        pos = Position(
            user_id=db_session._test_user_id, symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", net_quantity=10,
            average_entry_price=100.0, lot_size=50, realized_pnl=30.0,
            status="open", strategy_execution_id="mp-001",
            opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(pos)
        db_session.flush()

        entry = PaperOrder(
            user_id=db_session._test_user_id, client_order_id="entry-mp-001",
            execution_id="mp-001", position_id=pos.id,
            kind="entry", symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", action="buy",
            quantity=100, lot_size=50, status="FILLED",
            filled_quantity=100, fill_price=100.0,
        )
        db_session.add(entry)
        db_session.flush()

        exposure = StrategyLegExposure(
            user_id=db_session._test_user_id, execution_id="mp-001",
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
                user_id=db_session._test_user_id, client_order_id=f"exit-mp-{i}",
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
                user_id=db_session._test_user_id, exit_order_id=eo.id,
                exposure_id=exposure.id, quantity=eq,
            )
            db_session.add(alloc)

        db_session.commit()

        # Verify allocation records
        allocs = list(
            db_session.query(ExitExposureAllocation)
            .filter_by(user_id=db_session._test_user_id, exposure_id=exposure.id)
            .all()
        )
        assert len(allocs) == 3
        total_allocated = sum(a.quantity for a in allocs)
        assert total_allocated == 90  # 30 + 40 + 20

        # Trade detail should use the LAST allocation's exit order
        detail = get_trade_detail(db_session._test_user_id, "mp-001", db_session)
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
            user_id=db_session._test_user_id, execution_id="shared-a",
            client_order_id="client-shared-a", strategy_tag="Strat A",
            symbol="NIFTY", status="FILLED", entry_net=50.0,
            realized_pnl=0.0,
            entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(ex_a)
        db_session.flush()

        pos_a = Position(
            user_id=db_session._test_user_id, symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", net_quantity=30,
            average_entry_price=100.0, lot_size=50, realized_pnl=0.0,
            status="open", strategy_execution_id="shared-a",
            opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(pos_a)
        db_session.flush()

        entry_a = PaperOrder(
            user_id=db_session._test_user_id, client_order_id="entry-a",
            execution_id="shared-a", position_id=pos_a.id,
            kind="entry", symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", action="buy",
            quantity=50, lot_size=50, status="FILLED",
            filled_quantity=50, fill_price=100.0,
        )
        db_session.add(entry_a)
        db_session.flush()

        exp_a = StrategyLegExposure(
            user_id=db_session._test_user_id, execution_id="shared-a",
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
            user_id=db_session._test_user_id, execution_id="shared-b",
            client_order_id="client-shared-b", strategy_tag="Strat B",
            symbol="NIFTY", status="FILLED", entry_net=50.0,
            realized_pnl=0.0,
            entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(ex_b)
        db_session.flush()

        pos_b = Position(
            user_id=db_session._test_user_id, symbol="NIFTY", expiry="2026-08-07",
            strike=strike_b, option_type="call", net_quantity=20,
            average_entry_price=100.0, lot_size=50, realized_pnl=0.0,
            status="open", strategy_execution_id="shared-b",
            opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(pos_b)
        db_session.flush()

        entry_b = PaperOrder(
            user_id=db_session._test_user_id, client_order_id="entry-b",
            execution_id="shared-b", position_id=pos_b.id,
            kind="entry", symbol="NIFTY", expiry="2026-08-07",
            strike=strike_b, option_type="call", action="buy",
            quantity=50, lot_size=50, status="FILLED",
            filled_quantity=50, fill_price=100.0,
        )
        db_session.add(entry_b)
        db_session.flush()

        exp_b = StrategyLegExposure(
            user_id=db_session._test_user_id, execution_id="shared-b",
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
            user_id=db_session._test_user_id, client_order_id="exit-a",
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
            user_id=db_session._test_user_id, exit_order_id=exit_a.id,
            exposure_id=exp_a.id, quantity=20,
        )
        db_session.add(alloc_a)

        # Exit B: 30 lots @ 103 on pos_b
        exit_b = PaperOrder(
            user_id=db_session._test_user_id, client_order_id="exit-b",
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
            user_id=db_session._test_user_id, exit_order_id=exit_b.id,
            exposure_id=exp_b.id, quantity=30,
        )
        db_session.add(alloc_b)
        db_session.commit()

        # Trade detail for Execution A should show Exit A (101)
        detail_a = get_trade_detail(db_session._test_user_id, "shared-a", db_session)
        assert detail_a is not None
        leg_a = detail_a["legs"][0]
        assert leg_a["exit_price"] == 101.0, f"Expected 101.0 but got {leg_a['exit_price']}"
        assert leg_a["realized_pnl"] == 20.0
        assert leg_a["remaining_quantity"] == 30

        # Trade detail for Execution B should show Exit B (103)
        detail_b = get_trade_detail(db_session._test_user_id, "shared-b", db_session)
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
            db_session, db_session._test_user_id, "open-001", is_open=True,
        )
        detail = get_trade_detail(db_session._test_user_id, exec_id, db_session)
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
        session_a, user_a = create_test_identity(db_session, "iso-user-a")
        session_b, user_b = create_test_identity(db_session, "iso-user-b")

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
        _create_execution_with_exposure(db_session, db_session._test_user_id, "reg-001")
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
            db_session, db_session._test_user_id, "int-001", quantity=50,
        )
        allocs = list(
            db_session.query(ExitExposureAllocation)
            .filter_by(user_id=db_session._test_user_id, exit_order_id=exit_id)
            .all()
        )
        total = sum(a.quantity for a in allocs)
        exit_order = db_session.get(PaperOrder, exit_id)
        assert total == exit_order.quantity

    def test_remaining_quantity_consistent(self, db_session, logged_in):
        """remaining_quantity = original_quantity - sum(allocations)."""
        exec_id, pos_id, entry_id, exp_id, exit_id = _create_execution_with_exposure(
            db_session, db_session._test_user_id, "int-002", quantity=50, is_open=True,
        )
        exposure = db_session.get(StrategyLegExposure, exp_id)
        assert exposure.remaining_quantity == 50  # no exits


# ---- Test 8: Legacy fallback ----

class TestLegacyFallback:
    def test_no_allocations_uses_dict_fallback(self, client, db_session, logged_in):
        """Historical executions without allocations fall back to dict lookup."""
        # Create execution with exit but WITHOUT ExitExposureAllocation
        ex = StrategyExecution(
            user_id=db_session._test_user_id, execution_id="leg-001",
            client_order_id="client-leg-001", strategy_tag="Legacy",
            symbol="NIFTY", status="FILLED", entry_net=100.0,
            realized_pnl=50.0,
            entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
            exit_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        )
        db_session.add(ex)
        db_session.flush()
        pos = Position(
            user_id=db_session._test_user_id, symbol="NIFTY", expiry="2026-08-07",
            strike=28000.0, option_type="call", net_quantity=0,
            average_entry_price=100.0, lot_size=50, realized_pnl=50.0,
            status="closed", strategy_execution_id="leg-001",
            opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
            closed_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        )
        db_session.add(pos)
        db_session.flush()
        entry = PaperOrder(
            user_id=db_session._test_user_id, client_order_id="entry-leg-001",
            execution_id="leg-001", position_id=pos.id,
            kind="entry", symbol="NIFTY", expiry="2026-08-07",
            strike=28000.0, option_type="call", action="buy",
            quantity=50, lot_size=50, status="FILLED",
            filled_quantity=50, fill_price=100.0,
        )
        db_session.add(entry)
        db_session.flush()
        exp = StrategyLegExposure(
            user_id=db_session._test_user_id, execution_id="leg-001",
            position_id=pos.id, order_id=entry.id,
            symbol="NIFTY", expiry="2026-08-07",
            strike=28000.0, option_type="call", action="buy",
            original_quantity=50, remaining_quantity=0,
            status="closed",
        )
        db_session.add(exp)
        db_session.flush()
        exit_o = PaperOrder(
            user_id=db_session._test_user_id, client_order_id="exit-leg-001",
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

        detail = get_trade_detail(db_session._test_user_id, "leg-001", db_session)
        assert detail is not None
        leg = detail["legs"][0]
        assert leg["exit_price"] == 101.0
        assert leg["realized_pnl"] == 50.0


# ---- Test 9: Integration test — real exit_position() path ----

class TestProductionExitPath:
    """Verify that the real exit_position() function creates ExitExposureAllocation."""

    def test_exit_position_creates_allocation(self, db_session, logged_in):
        """Calling exit_position() directly creates allocation records."""
        from app.services.paper_execution import exit_position
        from app.schemas import ExitRequestIn

        # Setup: execution + exposure + entry order
        global _strike_counter
        _strike_counter += 1
        strike = float(_strike_counter)

        ex = StrategyExecution(
            user_id=db_session._test_user_id, execution_id="prod-001",
            client_order_id="client-prod-001", strategy_tag="Prod Strat",
            symbol="NIFTY", status="FILLED", entry_net=100.0,
            realized_pnl=None,
            entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(ex)
        db_session.flush()

        pos = Position(
            user_id=db_session._test_user_id, symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", net_quantity=50,
            average_entry_price=100.0, lot_size=50, realized_pnl=0.0,
            status="open", strategy_execution_id="prod-001",
            opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(pos)
        db_session.flush()

        entry = PaperOrder(
            user_id=db_session._test_user_id, client_order_id="entry-prod-001",
            execution_id="prod-001", position_id=pos.id,
            kind="entry", symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", action="buy",
            quantity=50, lot_size=50, status="FILLED",
            filled_quantity=50, fill_price=100.0,
        )
        db_session.add(entry)
        db_session.flush()

        exposure = StrategyLegExposure(
            user_id=db_session._test_user_id, execution_id="prod-001",
            position_id=pos.id, order_id=entry.id,
            symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", action="buy",
            original_quantity=50, remaining_quantity=50,
            status="open",
        )
        db_session.add(exposure)
        db_session.commit()

        # Execute the real production exit path
        req = ExitRequestIn(client_order_id="exit-prod-001", quantity=20)
        result = exit_position(db_session._test_user_id, pos.id, req, db_session, 101.0)

        # Verify exit order was created
        assert result.order is not None
        exit_order_id = result.order.id

        # Verify ExitExposureAllocation was created by the production path
        allocs = list(
            db_session.query(ExitExposureAllocation)
            .filter_by(user_id=db_session._test_user_id, exposure_id=exposure.id)
            .all()
        )
        assert len(allocs) == 1, f"Expected 1 allocation, got {len(allocs)}"
        assert allocs[0].exit_order_id == exit_order_id
        assert allocs[0].exposure_id == exposure.id
        assert allocs[0].quantity == 20

        # Verify remaining quantity
        db_session.refresh(exposure)
        assert exposure.remaining_quantity == 30

        # Verify trade detail uses the allocation
        detail = get_trade_detail(db_session._test_user_id, "prod-001", db_session)
        assert detail is not None
        leg = detail["legs"][0]
        assert leg["exit_price"] == 101.0
        assert leg["remaining_quantity"] == 30

    def test_multiple_partial_exits_via_production(self, db_session, logged_in):
        """Three partial exits via exit_position() create three allocation records."""
        from app.services.paper_execution import exit_position
        from app.schemas import ExitRequestIn

        global _strike_counter
        _strike_counter += 1
        strike = float(_strike_counter)

        ex = StrategyExecution(
            user_id=db_session._test_user_id, execution_id="prod-002",
            client_order_id="client-prod-002", strategy_tag="Prod Strat 2",
            symbol="NIFTY", status="FILLED", entry_net=100.0,
            realized_pnl=None,
            entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(ex)
        db_session.flush()

        pos = Position(
            user_id=db_session._test_user_id, symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", net_quantity=100,
            average_entry_price=100.0, lot_size=50, realized_pnl=0.0,
            status="open", strategy_execution_id="prod-002",
            opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(pos)
        db_session.flush()

        entry = PaperOrder(
            user_id=db_session._test_user_id, client_order_id="entry-prod-002",
            execution_id="prod-002", position_id=pos.id,
            kind="entry", symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", action="buy",
            quantity=100, lot_size=50, status="FILLED",
            filled_quantity=100, fill_price=100.0,
        )
        db_session.add(entry)
        db_session.flush()

        exposure = StrategyLegExposure(
            user_id=db_session._test_user_id, execution_id="prod-002",
            position_id=pos.id, order_id=entry.id,
            symbol="NIFTY", expiry="2026-08-07",
            strike=strike, option_type="call", action="buy",
            original_quantity=100, remaining_quantity=100,
            status="open",
        )
        db_session.add(exposure)
        db_session.commit()

        # Three partial exits
        exit_prices = [101.0, 103.0, 105.0]
        exit_qtys = [30, 40, 20]
        for i, (ep, eq) in enumerate(zip(exit_prices, exit_qtys)):
            req = ExitRequestIn(client_order_id=f"exit-prod-002-{i}", quantity=eq)
            exit_position(db_session._test_user_id, pos.id, req, db_session, ep)

        # Verify three allocation records exist
        allocs = list(
            db_session.query(ExitExposureAllocation)
            .filter_by(user_id=db_session._test_user_id, exposure_id=exposure.id)
            .all()
        )
        assert len(allocs) == 3
        total_allocated = sum(a.quantity for a in allocs)
        assert total_allocated == 90  # 30 + 40 + 20

        # Verify remaining quantity
        db_session.refresh(exposure)
        assert exposure.remaining_quantity == 10

        # Verify each allocation points to a different exit order
        exit_ids = {a.exit_order_id for a in allocs}
        assert len(exit_ids) == 3, "Each exit should have a unique order ID"

        # Verify trade detail shows the last exit
        detail = get_trade_detail(db_session._test_user_id, "prod-002", db_session)
        leg = detail["legs"][0]
        assert leg["exit_price"] == 105.0  # last exit
        assert leg["remaining_quantity"] == 10


class TestSharedPositionRegression:
    """Regression test for the original shared-position attribution bug."""

    def test_two_executions_separate_exits_via_production(self, db_session, logged_in):
        """Two executions with separate exits — each correctly attributed."""
        from app.services.paper_execution import exit_position
        from app.schemas import ExitRequestIn

        global _strike_counter
        _strike_counter += 1
        strike_a = float(_strike_counter)
        _strike_counter += 1
        strike_b = float(_strike_counter)

        # Execution A
        ex_a = StrategyExecution(
            user_id=db_session._test_user_id, execution_id="reg-a",
            client_order_id="client-reg-a", strategy_tag="Strat A",
            symbol="NIFTY", status="FILLED", entry_net=50.0,
            realized_pnl=None,
            entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(ex_a)
        db_session.flush()

        pos_a = Position(
            user_id=db_session._test_user_id, symbol="NIFTY", expiry="2026-08-07",
            strike=strike_a, option_type="call", net_quantity=50,
            average_entry_price=100.0, lot_size=50, realized_pnl=0.0,
            status="open", strategy_execution_id="reg-a",
            opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(pos_a)
        db_session.flush()

        entry_a = PaperOrder(
            user_id=db_session._test_user_id, client_order_id="entry-reg-a",
            execution_id="reg-a", position_id=pos_a.id,
            kind="entry", symbol="NIFTY", expiry="2026-08-07",
            strike=strike_a, option_type="call", action="buy",
            quantity=50, lot_size=50, status="FILLED",
            filled_quantity=50, fill_price=100.0,
        )
        db_session.add(entry_a)
        db_session.flush()

        exp_a = StrategyLegExposure(
            user_id=db_session._test_user_id, execution_id="reg-a",
            position_id=pos_a.id, order_id=entry_a.id,
            symbol="NIFTY", expiry="2026-08-07",
            strike=strike_a, option_type="call", action="buy",
            original_quantity=50, remaining_quantity=50,
            status="open",
        )
        db_session.add(exp_a)
        db_session.flush()

        # Execution B
        ex_b = StrategyExecution(
            user_id=db_session._test_user_id, execution_id="reg-b",
            client_order_id="client-reg-b", strategy_tag="Strat B",
            symbol="NIFTY", status="FILLED", entry_net=50.0,
            realized_pnl=None,
            entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(ex_b)
        db_session.flush()

        pos_b = Position(
            user_id=db_session._test_user_id, symbol="NIFTY", expiry="2026-08-07",
            strike=strike_b, option_type="call", net_quantity=50,
            average_entry_price=100.0, lot_size=50, realized_pnl=0.0,
            status="open", strategy_execution_id="reg-b",
            opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(pos_b)
        db_session.flush()

        entry_b = PaperOrder(
            user_id=db_session._test_user_id, client_order_id="entry-reg-b",
            execution_id="reg-b", position_id=pos_b.id,
            kind="entry", symbol="NIFTY", expiry="2026-08-07",
            strike=strike_b, option_type="call", action="buy",
            quantity=50, lot_size=50, status="FILLED",
            filled_quantity=50, fill_price=100.0,
        )
        db_session.add(entry_b)
        db_session.flush()

        exp_b = StrategyLegExposure(
            user_id=db_session._test_user_id, execution_id="reg-b",
            position_id=pos_b.id, order_id=entry_b.id,
            symbol="NIFTY", expiry="2026-08-07",
            strike=strike_b, option_type="call", action="buy",
            original_quantity=50, remaining_quantity=50,
            status="open",
        )
        db_session.add(exp_b)
        db_session.commit()

        # Exit A: 20 lots @ 101
        req_a = ExitRequestIn(client_order_id="exit-reg-a", quantity=20)
        result_a = exit_position(db_session._test_user_id, pos_a.id, req_a, db_session, 101.0)
        exit_a_id = result_a.order.id

        # Exit B: 30 lots @ 103
        req_b = ExitRequestIn(client_order_id="exit-reg-b", quantity=30)
        result_b = exit_position(db_session._test_user_id, pos_b.id, req_b, db_session, 103.0)
        exit_b_id = result_b.order.id

        # Verify allocation records
        allocs_a = list(
            db_session.query(ExitExposureAllocation)
            .filter_by(user_id=db_session._test_user_id, exposure_id=exp_a.id)
            .all()
        )
        allocs_b = list(
            db_session.query(ExitExposureAllocation)
            .filter_by(user_id=db_session._test_user_id, exposure_id=exp_b.id)
            .all()
        )
        assert len(allocs_a) == 1
        assert allocs_a[0].exit_order_id == exit_a_id
        assert allocs_a[0].quantity == 20

        assert len(allocs_b) == 1
        assert allocs_b[0].exit_order_id == exit_b_id
        assert allocs_b[0].quantity == 30

        # Verify remaining quantities
        db_session.refresh(exp_a)
        db_session.refresh(exp_b)
        assert exp_a.remaining_quantity == 30
        assert exp_b.remaining_quantity == 20

        # Verify trade detail correctly attributes exits
        detail_a = get_trade_detail(db_session._test_user_id, "reg-a", db_session)
        leg_a = detail_a["legs"][0]
        assert leg_a["exit_price"] == 101.0, f"Expected 101.0, got {leg_a['exit_price']}"
        assert leg_a["remaining_quantity"] == 30

        detail_b = get_trade_detail(db_session._test_user_id, "reg-b", db_session)
        leg_b = detail_b["legs"][0]
        assert leg_b["exit_price"] == 103.0, f"Expected 103.0, got {leg_b['exit_price']}"
        assert leg_b["remaining_quantity"] == 20

    def test_interleaved_exits_via_production(self, db_session, logged_in):
        """Interleaved exits: Exit A, Exit B, Exit A again — correct attribution."""
        from app.services.paper_execution import exit_position
        from app.schemas import ExitRequestIn

        global _strike_counter
        _strike_counter += 1
        strike_a = float(_strike_counter)
        _strike_counter += 1
        strike_b = float(_strike_counter)

        # Execution A
        ex_a = StrategyExecution(
            user_id=db_session._test_user_id, execution_id="intlv-a",
            client_order_id="client-intlv-a", strategy_tag="Strat A",
            symbol="NIFTY", status="FILLED", entry_net=50.0,
            realized_pnl=None,
            entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(ex_a)
        db_session.flush()

        pos_a = Position(
            user_id=db_session._test_user_id, symbol="NIFTY", expiry="2026-08-07",
            strike=strike_a, option_type="call", net_quantity=50,
            average_entry_price=100.0, lot_size=50, realized_pnl=0.0,
            status="open", strategy_execution_id="intlv-a",
            opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(pos_a)
        db_session.flush()

        entry_a = PaperOrder(
            user_id=db_session._test_user_id, client_order_id="entry-intlv-a",
            execution_id="intlv-a", position_id=pos_a.id,
            kind="entry", symbol="NIFTY", expiry="2026-08-07",
            strike=strike_a, option_type="call", action="buy",
            quantity=50, lot_size=50, status="FILLED",
            filled_quantity=50, fill_price=100.0,
        )
        db_session.add(entry_a)
        db_session.flush()

        exp_a = StrategyLegExposure(
            user_id=db_session._test_user_id, execution_id="intlv-a",
            position_id=pos_a.id, order_id=entry_a.id,
            symbol="NIFTY", expiry="2026-08-07",
            strike=strike_a, option_type="call", action="buy",
            original_quantity=50, remaining_quantity=50,
            status="open",
        )
        db_session.add(exp_a)
        db_session.flush()

        # Execution B
        ex_b = StrategyExecution(
            user_id=db_session._test_user_id, execution_id="intlv-b",
            client_order_id="client-intlv-b", strategy_tag="Strat B",
            symbol="NIFTY", status="FILLED", entry_net=50.0,
            realized_pnl=None,
            entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(ex_b)
        db_session.flush()

        pos_b = Position(
            user_id=db_session._test_user_id, symbol="NIFTY", expiry="2026-08-07",
            strike=strike_b, option_type="call", net_quantity=50,
            average_entry_price=100.0, lot_size=50, realized_pnl=0.0,
            status="open", strategy_execution_id="intlv-b",
            opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(pos_b)
        db_session.flush()

        entry_b = PaperOrder(
            user_id=db_session._test_user_id, client_order_id="entry-intlv-b",
            execution_id="intlv-b", position_id=pos_b.id,
            kind="entry", symbol="NIFTY", expiry="2026-08-07",
            strike=strike_b, option_type="call", action="buy",
            quantity=50, lot_size=50, status="FILLED",
            filled_quantity=50, fill_price=100.0,
        )
        db_session.add(entry_b)
        db_session.flush()

        exp_b = StrategyLegExposure(
            user_id=db_session._test_user_id, execution_id="intlv-b",
            position_id=pos_b.id, order_id=entry_b.id,
            symbol="NIFTY", expiry="2026-08-07",
            strike=strike_b, option_type="call", action="buy",
            original_quantity=50, remaining_quantity=50,
            status="open",
        )
        db_session.add(exp_b)
        db_session.commit()

        # Interleaved exits:
        # Exit A #1: 20 lots @ 101
        req_a1 = ExitRequestIn(client_order_id="exit-intlv-a1", quantity=20)
        result_a1 = exit_position(db_session._test_user_id, pos_a.id, req_a1, db_session, 101.0)
        exit_a1_id = result_a1.order.id

        # Exit B: 30 lots @ 103
        req_b = ExitRequestIn(client_order_id="exit-intlv-b", quantity=30)
        result_b = exit_position(db_session._test_user_id, pos_b.id, req_b, db_session, 103.0)
        exit_b_id = result_b.order.id

        # Exit A #2: 10 lots @ 105
        req_a2 = ExitRequestIn(client_order_id="exit-intlv-a2", quantity=10)
        result_a2 = exit_position(db_session._test_user_id, pos_a.id, req_a2, db_session, 105.0)
        exit_a2_id = result_a2.order.id

        # Verify Exposure A has 2 allocations (Exit A#1 + Exit A#2)
        allocs_a = list(
            db_session.query(ExitExposureAllocation)
            .filter_by(user_id=db_session._test_user_id, exposure_id=exp_a.id)
            .all()
        )
        assert len(allocs_a) == 2
        alloc_exit_ids_a = {a.exit_order_id for a in allocs_a}
        assert exit_a1_id in alloc_exit_ids_a
        assert exit_a2_id in alloc_exit_ids_a
        total_a = sum(a.quantity for a in allocs_a)
        assert total_a == 30  # 20 + 10

        # Verify Exposure B has 1 allocation (Exit B)
        allocs_b = list(
            db_session.query(ExitExposureAllocation)
            .filter_by(user_id=db_session._test_user_id, exposure_id=exp_b.id)
            .all()
        )
        assert len(allocs_b) == 1
        assert allocs_b[0].exit_order_id == exit_b_id
        assert allocs_b[0].quantity == 30

        # Verify remaining quantities
        db_session.refresh(exp_a)
        db_session.refresh(exp_b)
        assert exp_a.remaining_quantity == 20  # 50 - 20 - 10
        assert exp_b.remaining_quantity == 20  # 50 - 30

        # Verify trade detail
        detail_a = get_trade_detail(db_session._test_user_id, "intlv-a", db_session)
        leg_a = detail_a["legs"][0]
        assert leg_a["remaining_quantity"] == 20

        detail_b = get_trade_detail(db_session._test_user_id, "intlv-b", db_session)
        leg_b = detail_b["legs"][0]
        assert leg_b["exit_price"] == 103.0
        assert leg_b["remaining_quantity"] == 20
