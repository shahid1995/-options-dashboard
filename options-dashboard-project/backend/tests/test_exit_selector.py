"""Phase 6.5.0.4 — Server-Side Exit Intent Resolution tests.

Covers:
- Selector normalization (CE→CALL, PE→PUT, action normalization)
- Server-side resolution with scope tests (POSITION, STRATEGY, PORTFOLIO)
- Quantity safety (exceeds remaining, zero, negative)
- Ambiguous quantity handling
- No matching targets
- Deterministic ordering
- Side inversion (BUY→SELL, SELL→BUY)
- Strategy isolation
- User isolation
- Individual exposure targeting
- Stale/closed exposure rejection
- Edge cases
"""

from __future__ import annotations

import math
from datetime import datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import (
    PaperAccount,
    PaperOrder,
    PaperTransaction,
    Position,
    StrategyExecution,
    StrategyLegExposure,
    Trade,
)
from app.services.exit_selector import (
    ExitSelectorError,
    normalize_action,
    normalize_option_type,
    normalize_quantity_mode,
    normalize_scope,
    resolve_server_exit_targets,
)
from app.services.execution_intent import ExecutionTarget, exit_side_for


# -------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------

@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()


@pytest.fixture()
def user_id():
    return "exit-selector-user-6504"


@pytest.fixture()
def other_user_id():
    return "other-exit-selector-user-6504"


# -------------------------------------------------------------------
# Helper: create test data
# -------------------------------------------------------------------

def _make_execution(db, user_id, execution_id, strategy_tag="Test Strategy",
                    symbol="NIFTY", status="FILLED"):
    ex = StrategyExecution(
        user_id=user_id, execution_id=execution_id,
        client_order_id=f"exec-{execution_id}", strategy_tag=strategy_tag,
        symbol=symbol, status=status,
    )
    db.add(ex)
    db.flush()
    return ex


def _make_position(db, user_id, symbol="NIFTY", expiry="2026-08-28",
                   strike=25000.0, option_type="call", net_quantity=2,
                   lot_size=65, strategy_execution_id=None):
    pos = Position(
        user_id=user_id, symbol=symbol, expiry=expiry, strike=strike,
        option_type=option_type, net_quantity=net_quantity,
        average_entry_price=150.0, lot_size=lot_size, realized_pnl=0.0,
        status="open", strategy_execution_id=strategy_execution_id,
    )
    db.add(pos)
    db.flush()
    return pos


def _make_exposure(db, user_id, execution_id, position_id, order_id,
                   symbol="NIFTY", expiry="2026-08-28", strike=25000.0,
                   option_type="call", action="buy", original_quantity=2,
                   remaining_quantity=2, status="open"):
    exp = StrategyLegExposure(
        user_id=user_id, execution_id=execution_id, position_id=position_id,
        order_id=order_id, symbol=symbol, expiry=expiry, strike=strike,
        option_type=option_type, action=action,
        original_quantity=original_quantity, remaining_quantity=remaining_quantity,
        status=status,
    )
    db.add(exp)
    db.flush()
    return exp


# -------------------------------------------------------------------
# NORMALIZATION TESTS
# -------------------------------------------------------------------

class TestSelectorNormalization:
    def test_normalize_option_type_call(self):
        assert normalize_option_type("CALL") == "call"

    def test_normalize_option_type_ce(self):
        assert normalize_option_type("CE") == "call"

    def test_normalize_option_type_put(self):
        assert normalize_option_type("PUT") == "put"

    def test_normalize_option_type_pe(self):
        assert normalize_option_type("PE") == "put"

    def test_normalize_option_type_lowercase(self):
        assert normalize_option_type("call") == "call"
        assert normalize_option_type("put") == "put"

    def test_normalize_option_type_none(self):
        assert normalize_option_type(None) is None

    def test_normalize_option_type_invalid(self):
        assert normalize_option_type("INVALID") is None

    def test_normalize_action_buy(self):
        assert normalize_action("BUY") == "buy"

    def test_normalize_action_sell(self):
        assert normalize_action("SELL") == "sell"

    def test_normalize_action_lowercase(self):
        assert normalize_action("buy") == "buy"
        assert normalize_action("sell") == "sell"

    def test_normalize_action_none(self):
        assert normalize_action(None) is None

    def test_normalize_action_invalid(self):
        assert normalize_action("HOLD") is None

    def test_normalize_scope_position(self):
        assert normalize_scope("POSITION") == "POSITION"

    def test_normalize_scope_strategy(self):
        assert normalize_scope("STRATEGY") == "STRATEGY"

    def test_normalize_scope_portfolio(self):
        assert normalize_scope("PORTFOLIO") == "PORTFOLIO"

    def test_normalize_scope_none(self):
        assert normalize_scope(None) is None

    def test_normalize_scope_invalid(self):
        assert normalize_scope("INVALID") is None

    def test_normalize_quantity_mode_all(self):
        assert normalize_quantity_mode("ALL") == "ALL"

    def test_normalize_quantity_mode_quantity(self):
        assert normalize_quantity_mode("QUANTITY") == "QUANTITY"

    def test_normalize_quantity_mode_none(self):
        assert normalize_quantity_mode(None) is None

    def test_normalize_quantity_mode_invalid(self):
        assert normalize_quantity_mode("INVALID") is None


# -------------------------------------------------------------------
# SIDE INVERSION TESTS
# -------------------------------------------------------------------

class TestSideInversion:
    def test_buy_exposure_exits_with_sell(self):
        assert exit_side_for("buy") == "sell"

    def test_sell_exposure_exits_with_buy(self):
        assert exit_side_for("sell") == "buy"

    def test_buy_uppercase_exits_with_sell(self):
        assert exit_side_for("BUY") == "sell"

    def test_sell_uppercase_exits_with_buy(self):
        assert exit_side_for("SELL") == "buy"


# -------------------------------------------------------------------
# INPUT VALIDATION TESTS
# -------------------------------------------------------------------

class TestInputValidation:
    def test_missing_scope(self, db_session, user_id):
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(db=db_session, user_id=user_id, scope="INVALID")
        assert exc.value.code == "INVALID_INTENT"

    def test_position_scope_requires_position_id(self, db_session, user_id):
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(db=db_session, user_id=user_id, scope="POSITION")
        assert exc.value.code == "INVALID_INTENT"

    def test_strategy_scope_requires_execution_id(self, db_session, user_id):
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(db=db_session, user_id=user_id, scope="STRATEGY")
        assert exc.value.code == "INVALID_INTENT"

    def test_quantity_mode_requires_quantity(self, db_session, user_id):
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(
                db=db_session, user_id=user_id, scope="PORTFOLIO",
                quantity_mode="QUANTITY",
            )
        assert exc.value.code == "MISSING_QUANTITY"

    def test_invalid_quantity_zero(self, db_session, user_id):
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(
                db=db_session, user_id=user_id, scope="PORTFOLIO",
                quantity_mode="QUANTITY", quantity=0,
            )
        assert exc.value.code == "INVALID_QUANTITY"

    def test_invalid_quantity_negative(self, db_session, user_id):
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(
                db=db_session, user_id=user_id, scope="PORTFOLIO",
                quantity_mode="QUANTITY", quantity=-1,
            )
        assert exc.value.code == "INVALID_QUANTITY"


# -------------------------------------------------------------------
# NO MATCHING TARGETS TESTS
# -------------------------------------------------------------------

class TestNoMatchingTargets:
    def test_no_exposures_at_all(self, db_session, user_id):
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(
                db=db_session, user_id=user_id, scope="PORTFOLIO",
            )
        assert exc.value.code == "NO_MATCHING_TARGETS"

    def test_no_call_exposures_when_filtering_call(self, db_session, user_id):
        pos = _make_position(db_session, user_id, option_type="call")
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            option_type="call",
        )
        # Filter for PUT when only CALL exists
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(
                db=db_session, user_id=user_id, scope="POSITION",
                position_id=pos.id, option_type="PUT",
            )
        assert exc.value.code == "NO_MATCHING_TARGETS"

    def test_no_buy_exposures_when_filtering_buy(self, db_session, user_id):
        pos = _make_position(db_session, user_id, option_type="call")
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            option_type="call", action="sell",
        )
        # Filter for BUY when only SELL exists
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(
                db=db_session, user_id=user_id, scope="POSITION",
                position_id=pos.id, action="BUY",
            )
        assert exc.value.code == "NO_MATCHING_TARGETS"

    def test_closed_exposure_excluded(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2)
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            remaining_quantity=0, status="closed",
        )
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(
                db=db_session, user_id=user_id, scope="POSITION",
                position_id=pos.id,
            )
        assert exc.value.code == "NO_MATCHING_TARGETS"

    def test_zero_remaining_quantity_excluded(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2)
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            remaining_quantity=0, status="open",
        )
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(
                db=db_session, user_id=user_id, scope="POSITION",
                position_id=pos.id,
            )
        assert exc.value.code == "NO_MATCHING_TARGETS"

    def test_nonexistent_strategy(self, db_session, user_id):
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(
                db=db_session, user_id=user_id, scope="STRATEGY",
                strategy_execution_id="nonexistent-exec",
            )
        assert exc.value.code == "TARGET_NOT_FOUND"

    def test_nonexistent_position(self, db_session, user_id):
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(
                db=db_session, user_id=user_id, scope="POSITION",
                position_id=99999,
            )
        assert exc.value.code == "TARGET_NOT_FOUND"

    def test_closed_position(self, db_session, user_id):
        # Closed position is caught by position validation → TARGET_NOT_FOUND
        pos = _make_position(db_session, user_id, net_quantity=2)
        pos.status = "closed"
        db_session.flush()
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(
                db=db_session, user_id=user_id, scope="POSITION",
                position_id=pos.id,
            )
        assert exc.value.code == "TARGET_NOT_FOUND"


# -------------------------------------------------------------------
# POSITION SCOPE TESTS
# -------------------------------------------------------------------

class TestPositionScope:
    def test_single_exposure(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2)
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            remaining_quantity=2,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id,
        )
        assert len(targets) == 1
        assert targets[0].position_id == pos.id
        assert targets[0].strategy_leg_exposure_id == exp.id
        assert targets[0].source_action == "buy"
        assert targets[0].exit_side == "sell"
        assert targets[0].quantity == 2

    def test_multiple_exposures_in_position(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=3)
        exp1 = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            remaining_quantity=2,
        )
        exp2 = _make_exposure(
            db_session, user_id, "exec-2", pos.id, order_id=2,
            remaining_quantity=1,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id,
        )
        assert len(targets) == 2
        quantities = sorted([t.quantity for t in targets])
        assert quantities == [1, 2]

    def test_position_with_option_type_filter(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=3)
        exp_call = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            option_type="call", remaining_quantity=2,
        )
        exp_put = _make_exposure(
            db_session, user_id, "exec-2", pos.id, order_id=2,
            option_type="put", remaining_quantity=1,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id, option_type="CALL",
        )
        assert len(targets) == 1
        assert targets[0].option_type == "call"
        assert targets[0].strategy_leg_exposure_id == exp_call.id

    def test_position_with_action_filter(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=3)
        exp_buy = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            action="buy", remaining_quantity=2,
        )
        exp_sell = _make_exposure(
            db_session, user_id, "exec-2", pos.id, order_id=2,
            action="sell", remaining_quantity=1,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id, action="BUY",
        )
        assert len(targets) == 1
        assert targets[0].source_action == "buy"


# -------------------------------------------------------------------
# STRATEGY SCOPE TESTS
# -------------------------------------------------------------------

class TestStrategyScope:
    def test_strategy_isolation(self, db_session, user_id):
        """Exit Strategy A must NOT touch Strategy B."""
        pos = _make_position(db_session, user_id, net_quantity=7)
        _make_execution(db_session, user_id, "exec-A", strategy_tag="Strategy A")
        _make_execution(db_session, user_id, "exec-B", strategy_tag="Strategy B")
        exp_a = _make_exposure(
            db_session, user_id, "exec-A", pos.id, order_id=1,
            remaining_quantity=2,
        )
        exp_b = _make_exposure(
            db_session, user_id, "exec-B", pos.id, order_id=2,
            remaining_quantity=5,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="STRATEGY",
            strategy_execution_id="exec-A",
        )
        assert len(targets) == 1
        assert targets[0].strategy_execution_id == "exec-A"
        assert targets[0].quantity == 2

    def test_strategy_with_selector_filter(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=7)
        _make_execution(db_session, user_id, "exec-A", strategy_tag="Strategy A")
        exp_a_call = _make_exposure(
            db_session, user_id, "exec-A", pos.id, order_id=1,
            option_type="call", action="buy", remaining_quantity=2,
        )
        exp_a_put = _make_exposure(
            db_session, user_id, "exec-A", pos.id, order_id=2,
            option_type="put", action="sell", remaining_quantity=5,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="STRATEGY",
            strategy_execution_id="exec-A", option_type="CALL", action="BUY",
        )
        assert len(targets) == 1
        assert targets[0].option_type == "call"
        assert targets[0].source_action == "buy"


# -------------------------------------------------------------------
# PORTFOLIO SCOPE TESTS
# -------------------------------------------------------------------

class TestPortfolioScope:
    def test_portfolio_resolves_all_exposures(self, db_session, user_id):
        pos1 = _make_position(
            db_session, user_id, symbol="NIFTY", expiry="2026-08-28",
            strike=25000.0, option_type="call", net_quantity=2,
        )
        pos2 = _make_position(
            db_session, user_id, symbol="NIFTY", expiry="2026-08-28",
            strike=25100.0, option_type="put", net_quantity=-1,
        )
        exp1 = _make_exposure(
            db_session, user_id, "exec-1", pos1.id, order_id=1,
            option_type="call", action="buy", remaining_quantity=2,
        )
        exp2 = _make_exposure(
            db_session, user_id, "exec-2", pos2.id, order_id=2,
            option_type="put", action="sell", remaining_quantity=1,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="PORTFOLIO",
        )
        assert len(targets) == 2
        target_ids = {t.strategy_leg_exposure_id for t in targets}
        assert target_ids == {exp1.id, exp2.id}

    def test_portfolio_with_option_type_filter(self, db_session, user_id):
        pos1 = _make_position(
            db_session, user_id, symbol="NIFTY", expiry="2026-08-28",
            strike=25000.0, option_type="call", net_quantity=2,
        )
        pos2 = _make_position(
            db_session, user_id, symbol="NIFTY", expiry="2026-08-28",
            strike=25100.0, option_type="put", net_quantity=-1,
        )
        exp1 = _make_exposure(
            db_session, user_id, "exec-1", pos1.id, order_id=1,
            option_type="call", action="buy", remaining_quantity=2,
        )
        exp2 = _make_exposure(
            db_session, user_id, "exec-2", pos2.id, order_id=2,
            option_type="put", action="sell", remaining_quantity=1,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="PORTFOLIO",
            option_type="CALL",
        )
        assert len(targets) == 1
        assert targets[0].option_type == "call"


# -------------------------------------------------------------------
# INDIVIDUAL EXPOSURE TARGETING
# -------------------------------------------------------------------

class TestIndividualExposureTargeting:
    def test_target_specific_exposure(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=7)
        _make_execution(db_session, user_id, "exec-A")
        _make_execution(db_session, user_id, "exec-B")
        exp_a = _make_exposure(
            db_session, user_id, "exec-A", pos.id, order_id=1,
            remaining_quantity=2,
        )
        exp_b = _make_exposure(
            db_session, user_id, "exec-B", pos.id, order_id=2,
            remaining_quantity=5,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id, exposure_id=exp_a.id,
        )
        assert len(targets) == 1
        assert targets[0].strategy_leg_exposure_id == exp_a.id
        assert targets[0].quantity == 2


# -------------------------------------------------------------------
# QUANTITY MODE TESTS
# -------------------------------------------------------------------

class TestQuantityMode:
    def test_quantity_all_resolves_remaining(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=3)
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            remaining_quantity=3,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id, quantity_mode="ALL",
        )
        assert len(targets) == 1
        assert targets[0].quantity == 3

    def test_quantity_partial(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=3)
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            remaining_quantity=3,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id, quantity_mode="QUANTITY", quantity=1,
        )
        assert len(targets) == 1
        assert targets[0].quantity == 1
        assert targets[0].remaining_quantity == 3

    def test_quantity_exceeds_remaining_rejected(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=3)
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            remaining_quantity=3,
        )
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(
                db=db_session, user_id=user_id, scope="POSITION",
                position_id=pos.id, quantity_mode="QUANTITY", quantity=5,
            )
        assert exc.value.code == "EXIT_QUANTITY_EXCEEDS_REMAINING"

    def test_quantity_ambiguous_multiple_targets(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=7)
        _make_execution(db_session, user_id, "exec-A")
        _make_execution(db_session, user_id, "exec-B")
        exp_a = _make_exposure(
            db_session, user_id, "exec-A", pos.id, order_id=1,
            remaining_quantity=2,
        )
        exp_b = _make_exposure(
            db_session, user_id, "exec-B", pos.id, order_id=2,
            remaining_quantity=5,
        )
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(
                db=db_session, user_id=user_id, scope="POSITION",
                position_id=pos.id, quantity_mode="QUANTITY", quantity=1,
            )
        assert exc.value.code == "AMBIGUOUS_EXIT_QUANTITY"

    def test_quantity_unambiguous_single_target(self, db_session, user_id):
        """QUANTITY mode with exactly one matching target succeeds."""
        pos = _make_position(db_session, user_id, net_quantity=2)
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            option_type="call", action="buy", remaining_quantity=2,
        )
        _make_exposure(
            db_session, user_id, "exec-2", pos.id, order_id=2,
            option_type="put", action="sell", remaining_quantity=5,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id, option_type="CALL", action="BUY",
            quantity_mode="QUANTITY", quantity=1,
        )
        assert len(targets) == 1
        assert targets[0].quantity == 1


# -------------------------------------------------------------------
# USER ISOLATION TESTS
# -------------------------------------------------------------------

class TestUserIsolation:
    def test_cannot_target_other_user_position(self, db_session, user_id, other_user_id):
        pos = _make_position(db_session, other_user_id, net_quantity=2)
        exp = _make_exposure(
            db_session, other_user_id, "exec-other", pos.id, order_id=1,
            remaining_quantity=2,
        )
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(
                db=db_session, user_id=user_id, scope="POSITION",
                position_id=pos.id,
            )
        assert exc.value.code == "TARGET_NOT_FOUND"

    def test_cannot_target_other_user_strategy(self, db_session, user_id, other_user_id):
        _make_execution(db_session, other_user_id, "exec-other", strategy_tag="Other Strategy")
        with pytest.raises(ExitSelectorError) as exc:
            resolve_server_exit_targets(
                db=db_session, user_id=user_id, scope="STRATEGY",
                strategy_execution_id="exec-other",
            )
        assert exc.value.code == "TARGET_NOT_FOUND"

    def test_portfolio_scope_excludes_other_user(self, db_session, user_id, other_user_id):
        pos_user = _make_position(db_session, user_id, net_quantity=2)
        pos_other = _make_position(db_session, other_user_id, net_quantity=3)
        exp_user = _make_exposure(
            db_session, user_id, "exec-1", pos_user.id, order_id=1,
            remaining_quantity=2,
        )
        exp_other = _make_exposure(
            db_session, other_user_id, "exec-2", pos_other.id, order_id=2,
            remaining_quantity=3,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="PORTFOLIO",
        )
        assert len(targets) == 1
        assert targets[0].user_id == user_id if hasattr(targets[0], 'user_id') else True
        assert targets[0].strategy_leg_exposure_id == exp_user.id


# -------------------------------------------------------------------
# DETERMINISTIC ORDERING
# -------------------------------------------------------------------

class TestDeterministicOrdering:
    def test_ordering_by_option_type_action_exposure_id(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=10)
        _make_execution(db_session, user_id, "exec-1")
        _make_execution(db_session, user_id, "exec-2")
        _make_execution(db_session, user_id, "exec-3")
        exp_put_sell = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            option_type="put", action="sell", remaining_quantity=3,
        )
        exp_call_buy = _make_exposure(
            db_session, user_id, "exec-2", pos.id, order_id=2,
            option_type="call", action="buy", remaining_quantity=2,
        )
        exp_call_sell = _make_exposure(
            db_session, user_id, "exec-3", pos.id, order_id=3,
            option_type="call", action="sell", remaining_quantity=5,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id,
        )
        assert len(targets) == 3
        # Sorted by [option_type, source_action, exposure_id]
        assert targets[0].option_type == "call" and targets[0].source_action == "buy"
        assert targets[1].option_type == "call" and targets[1].source_action == "sell"
        assert targets[2].option_type == "put" and targets[2].source_action == "sell"

    def test_same_instrument_different_strategies_ordering(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=7)
        _make_execution(db_session, user_id, "exec-A")
        _make_execution(db_session, user_id, "exec-B")
        exp_a = _make_exposure(
            db_session, user_id, "exec-A", pos.id, order_id=1,
            option_type="call", action="buy", remaining_quantity=2,
        )
        exp_b = _make_exposure(
            db_session, user_id, "exec-B", pos.id, order_id=2,
            option_type="call", action="buy", remaining_quantity=5,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="PORTFOLIO",
            option_type="CALL", action="BUY",
        )
        assert len(targets) == 2
        assert targets[0].strategy_leg_exposure_id == exp_a.id
        assert targets[1].strategy_leg_exposure_id == exp_b.id


# -------------------------------------------------------------------
# SIDE INVERSION INTEGRATION
# -------------------------------------------------------------------

class TestSideInversionIntegration:
    def test_buy_call_exits_with_sell(self, db_session, user_id):
        pos = _make_position(db_session, user_id, option_type="call", net_quantity=2)
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            option_type="call", action="buy", remaining_quantity=2,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id,
        )
        assert targets[0].source_action == "buy"
        assert targets[0].exit_side == "sell"

    def test_sell_call_exits_with_buy(self, db_session, user_id):
        pos = _make_position(db_session, user_id, option_type="call", net_quantity=-2)
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            option_type="call", action="sell", remaining_quantity=2,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id,
        )
        assert targets[0].source_action == "sell"
        assert targets[0].exit_side == "buy"

    def test_buy_put_exits_with_sell(self, db_session, user_id):
        pos = _make_position(db_session, user_id, option_type="put", net_quantity=3)
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            option_type="put", action="buy", remaining_quantity=3,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id,
        )
        assert targets[0].source_action == "buy"
        assert targets[0].exit_side == "sell"

    def test_sell_put_exits_with_buy(self, db_session, user_id):
        pos = _make_position(db_session, user_id, option_type="put", net_quantity=-4)
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            option_type="put", action="sell", remaining_quantity=4,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id,
        )
        assert targets[0].source_action == "sell"
        assert targets[0].exit_side == "buy"


# -------------------------------------------------------------------
# INSTRUMENT IDENTITY
# -------------------------------------------------------------------

class TestInstrumentIdentity:
    def test_target_preserves_instrument_identity(self, db_session, user_id):
        pos = _make_position(
            db_session, user_id, symbol="NIFTY", expiry="2026-08-28",
            strike=25000.0, option_type="call", net_quantity=2, lot_size=65,
        )
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            symbol="NIFTY", expiry="2026-08-28", strike=25000.0,
            option_type="call", action="buy", remaining_quantity=2,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id,
        )
        assert targets[0].symbol == "NIFTY"
        assert targets[0].expiry == "2026-08-28"
        assert targets[0].strike == 25000.0
        assert targets[0].option_type == "call"
        assert targets[0].lot_size == 65


# -------------------------------------------------------------------
# EXPOSURE IDENTITY
# -------------------------------------------------------------------

class TestExposureIdentity:
    def test_target_preserves_exposure_id(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2)
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            remaining_quantity=2,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id,
        )
        assert targets[0].strategy_leg_exposure_id == exp.id
        assert targets[0].strategy_execution_id == "exec-1"
        assert targets[0].position_id == pos.id

    def test_target_preserves_execution_id(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2)
        exp = _make_exposure(
            db_session, user_id, "exec-A", pos.id, order_id=1,
            remaining_quantity=2,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id,
        )
        assert targets[0].strategy_execution_id == "exec-A"


# -------------------------------------------------------------------
# EDGE CASES
# -------------------------------------------------------------------

class TestEdgeCases:
    def test_partial_remaining_quantity(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2)
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            original_quantity=3, remaining_quantity=2,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id,
        )
        assert targets[0].quantity == 2
        assert targets[0].remaining_quantity == 2

    def test_all_selector_multiple_strategies_same_instrument(self, db_session, user_id):
        """Two strategies share same instrument — each gets independent target."""
        pos = _make_position(db_session, user_id, net_quantity=7)
        _make_execution(db_session, user_id, "exec-A")
        _make_execution(db_session, user_id, "exec-B")
        exp_a = _make_exposure(
            db_session, user_id, "exec-A", pos.id, order_id=1,
            option_type="call", action="buy", remaining_quantity=2,
        )
        exp_b = _make_exposure(
            db_session, user_id, "exec-B", pos.id, order_id=2,
            option_type="call", action="buy", remaining_quantity=5,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="PORTFOLIO",
            option_type="CALL", action="BUY",
        )
        assert len(targets) == 2
        quantities = sorted([t.quantity for t in targets])
        assert quantities == [2, 5]

    def test_no_broker_specific_fields_in_target(self, db_session, user_id):
        """Targets must NOT contain broker-specific fields."""
        pos = _make_position(db_session, user_id, net_quantity=2)
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            remaining_quantity=2,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id,
        )
        target_dict = vars(targets[0])
        # Must NOT have Upstox-specific fields
        assert "instrument_key" not in target_dict
        assert "transaction_type" not in target_dict
        assert "product" not in target_dict
        assert "access_token" not in target_dict
        assert "refresh_token" not in target_dict

    def test_only_one_matching_target_allows_quantity(self, db_session, user_id):
        """Exactly one target allows QUANTITY mode."""
        pos = _make_position(db_session, user_id, net_quantity=3)
        exp = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            option_type="call", action="buy", remaining_quantity=3,
        )
        _make_exposure(
            db_session, user_id, "exec-2", pos.id, order_id=2,
            option_type="put", action="sell", remaining_quantity=5,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id, option_type="CALL", action="BUY",
            quantity_mode="QUANTITY", quantity=1,
        )
        assert len(targets) == 1
        assert targets[0].quantity == 1

    def test_selector_with_ce_filter(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=5)
        exp_ce = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            option_type="call", action="buy", remaining_quantity=2,
        )
        exp_pe = _make_exposure(
            db_session, user_id, "exec-2", pos.id, order_id=2,
            option_type="put", action="sell", remaining_quantity=3,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id, option_type="CE",
        )
        assert len(targets) == 1
        assert targets[0].option_type == "call"
        assert targets[0].strategy_leg_exposure_id == exp_ce.id

    def test_selector_with_pe_filter(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=5)
        exp_ce = _make_exposure(
            db_session, user_id, "exec-1", pos.id, order_id=1,
            option_type="call", action="buy", remaining_quantity=2,
        )
        exp_pe = _make_exposure(
            db_session, user_id, "exec-2", pos.id, order_id=2,
            option_type="put", action="sell", remaining_quantity=3,
        )
        targets = resolve_server_exit_targets(
            db=db_session, user_id=user_id, scope="POSITION",
            position_id=pos.id, option_type="PE",
        )
        assert len(targets) == 1
        assert targets[0].option_type == "put"
        assert targets[0].strategy_leg_exposure_id == exp_pe.id


# -------------------------------------------------------------------
# STATIC ARCHITECTURE AUDIT
# -------------------------------------------------------------------

class TestStaticArchitectureAudit:
    def test_exit_selector_does_not_import_broker_modules(self):
        """exit_selector.py must not import broker-specific modules."""
        import inspect
        import app.services.exit_selector as mod
        source = inspect.getsource(mod)
        # Must NOT import UpstoxAdapter or Upstox services
        assert "UpstoxAdapter" not in source
        assert "app.services.upstox" not in source
        assert "app.brokers.adapters" not in source

    def test_exit_selector_no_broker_specific_fields_in_target(self):
        """ExecutionTarget must not have broker-specific fields."""
        from app.services.execution_intent import ExecutionTarget
        fields = {f.name for f in ExecutionTarget.__dataclass_fields__.values()}
        assert "instrument_key" not in fields
        assert "transaction_type" not in fields
        assert "product" not in fields
        assert "access_token" not in fields
        assert "refresh_token" not in fields
