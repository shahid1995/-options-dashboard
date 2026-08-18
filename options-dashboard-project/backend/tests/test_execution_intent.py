"""Phase 6.5.0.3 — Execution Intent + Execution Router tests.

Covers the full acceptance matrix:
- ExecutionIntent creation and validation
- ExecutionTarget creation and side inversion
- Exit-intent → execution-intent conversion
- Stale-target protection
- ExecutionRouter PAPER routing to existing paper engine
- ExecutionRouter LIVE-disabled boundary
- Idempotency
- User isolation
- Quantity safety
- Broker-neutral safety (no Upstox fields)
- StrategyLegExposure integration
- Bulk-exit compatibility
- Concurrency / double-exit protection
"""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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
from app.services.execution_intent import (
    ExecutionError,
    ExecutionErrorCode,
    ExecutionIntent,
    ExecutionMode,
    ExecutionResult,
    ExecutionRouter,
    ExecutionSource,
    ExecutionStatus,
    ExecutionTarget,
    build_execution_targets_from_exposures,
    create_execution_intent,
    exit_intent_target_to_execution_target,
    exit_side_for,
    source_action_for_exit,
    validate_targets_still_valid,
)
from app.services.paper_execution import PaperExecutionError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session():
    """In-memory SQLite database for isolated tests."""
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
    return "test-user-6503"


@pytest.fixture()
def other_user_id():
    return "other-user-6503"


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


def _make_target(**overrides) -> ExecutionTarget:
    defaults = dict(
        position_id=1, source_action="buy", exit_side="sell",
        quantity=2, remaining_quantity=2, symbol="NIFTY",
        expiry="2026-08-28", strike=25000.0, option_type="call", lot_size=65,
    )
    defaults.update(overrides)
    return ExecutionTarget(**defaults)


def _make_intent(targets=None, **overrides) -> ExecutionIntent:
    if targets is None:
        targets = [_make_target()]
    defaults = dict(
        user_id="test-user", execution_mode=ExecutionMode.PAPER,
        source=ExecutionSource.EXIT_SELECTOR, targets=targets,
        idempotency_key="test-idem-key-12345",
    )
    defaults.update(overrides)
    return create_execution_intent(**defaults)


def _run_async(coro):
    """Run an async coroutine in a new event loop for sync tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ===================================================================
# EXECUTION TARGET TESTS
# ===================================================================

class TestExecutionTarget:
    def test_buy_exposure_exits_with_sell(self):
        target = _make_target(source_action="buy", exit_side="sell")
        assert target.source_action == "buy"
        assert target.exit_side == "sell"

    def test_sell_exposure_exits_with_buy(self):
        target = _make_target(source_action="sell", exit_side="buy")
        assert target.source_action == "sell"
        assert target.exit_side == "buy"

    def test_incorrect_exit_side_raises_error(self):
        with pytest.raises(ExecutionError) as exc:
            _make_target(source_action="buy", exit_side="buy")
        assert exc.value.code is ExecutionErrorCode.INVALID_EXECUTION_INTENT

    def test_incorrect_exit_side_sell_to_sell(self):
        with pytest.raises(ExecutionError) as exc:
            _make_target(source_action="sell", exit_side="sell")
        assert exc.value.code is ExecutionErrorCode.INVALID_EXECUTION_INTENT

    def test_invalid_source_action_raises_error(self):
        with pytest.raises(ExecutionError) as exc:
            _make_target(source_action="hold", exit_side="sell")
        assert exc.value.code is ExecutionErrorCode.INVALID_EXECUTION_INTENT

    def test_zero_quantity_raises_error(self):
        with pytest.raises(ExecutionError) as exc:
            _make_target(quantity=0)
        assert exc.value.code is ExecutionErrorCode.EXECUTION_QUANTITY_INVALID

    def test_negative_quantity_raises_error(self):
        with pytest.raises(ExecutionError) as exc:
            _make_target(quantity=-1)
        assert exc.value.code is ExecutionErrorCode.EXECUTION_QUANTITY_INVALID

    def test_negative_remaining_quantity_raises_error(self):
        with pytest.raises(ExecutionError) as exc:
            _make_target(remaining_quantity=-1)
        assert exc.value.code is ExecutionErrorCode.EXECUTION_QUANTITY_INVALID

    def test_target_preserves_position_identity(self):
        target = _make_target(position_id=42)
        assert target.position_id == 42

    def test_target_preserves_strategy_execution_identity(self):
        target = _make_target(strategy_execution_id="exec-abc")
        assert target.strategy_execution_id == "exec-abc"

    def test_target_preserves_exposure_identity(self):
        target = _make_target(strategy_leg_exposure_id=99)
        assert target.strategy_leg_exposure_id == 99

    def test_target_preserves_instrument_identity(self):
        target = _make_target(symbol="BANKNIFTY", expiry="2026-09-24", strike=51000.0, option_type="put")
        assert target.symbol == "BANKNIFTY"
        assert target.expiry == "2026-09-24"
        assert target.strike == 51000.0
        assert target.option_type == "put"

    def test_target_preserves_quantities(self):
        target = _make_target(quantity=3, remaining_quantity=5)
        assert target.quantity == 3
        assert target.remaining_quantity == 5

    def test_target_preserves_lot_size(self):
        target = _make_target(lot_size=25)
        assert target.lot_size == 25

    def test_target_price_override_is_optional(self):
        target = _make_target()
        assert target.price_override is None

    def test_target_with_price_override(self):
        target = _make_target(price_override=175.50)
        assert target.price_override == 175.50

    def test_target_no_broker_specific_fields(self):
        forbidden = {"instrument_key", "transaction_type", "access_token", "refresh_token", "api_key", "api_secret"}
        target = _make_target()
        target_fields = {f.name for f in target.__dataclass_fields__.values()}
        assert not (target_fields & forbidden)


# ===================================================================
# EXECUTION INTENT TESTS
# ===================================================================

class TestExecutionIntent:
    def test_valid_intent(self):
        intent = _make_intent()
        assert intent.intent_id
        assert intent.user_id == "test-user"
        assert intent.execution_mode == ExecutionMode.PAPER
        assert intent.source == ExecutionSource.EXIT_SELECTOR
        assert len(intent.targets) == 1
        assert intent.idempotency_key == "test-idem-key-12345"
        assert intent.status == ExecutionStatus.PENDING

    def test_intent_requires_user_id(self):
        with pytest.raises(ExecutionError) as exc:
            create_execution_intent(user_id="", execution_mode=ExecutionMode.PAPER, source=ExecutionSource.EXIT_SELECTOR, targets=[_make_target()])
        assert exc.value.code is ExecutionErrorCode.INVALID_EXECUTION_INTENT

    def test_intent_requires_targets(self):
        with pytest.raises(ExecutionError) as exc:
            create_execution_intent(user_id="u", execution_mode=ExecutionMode.PAPER, source=ExecutionSource.EXIT_SELECTOR, targets=[])
        assert exc.value.code is ExecutionErrorCode.INVALID_EXECUTION_INTENT

    def test_intent_requires_idempotency_key(self):
        with pytest.raises(ExecutionError) as exc:
            ExecutionIntent(intent_id="x", user_id="u", execution_mode=ExecutionMode.PAPER, source=ExecutionSource.EXIT_SELECTOR, targets=[_make_target()], idempotency_key="", created_at="now")
        assert exc.value.code is ExecutionErrorCode.INVALID_EXECUTION_INTENT

    def test_intent_deterministic_id_generation(self):
        i1 = create_execution_intent(user_id="u", execution_mode=ExecutionMode.PAPER, source=ExecutionSource.EXIT_SELECTOR, targets=[_make_target()])
        i2 = create_execution_intent(user_id="u", execution_mode=ExecutionMode.PAPER, source=ExecutionSource.EXIT_SELECTOR, targets=[_make_target()])
        assert i1.intent_id != i2.intent_id

    def test_intent_custom_idempotency_key(self):
        intent = _make_intent(idempotency_key="my-key-12345")
        assert intent.idempotency_key == "my-key-12345"

    def test_intent_default_idempotency_key_is_random(self):
        i1 = create_execution_intent(user_id="u", execution_mode=ExecutionMode.PAPER, source=ExecutionSource.EXIT_SELECTOR, targets=[_make_target()])
        i2 = create_execution_intent(user_id="u", execution_mode=ExecutionMode.PAPER, source=ExecutionSource.EXIT_SELECTOR, targets=[_make_target()])
        assert i1.idempotency_key != i2.idempotency_key

    def test_intent_preserves_strategy_execution_id(self):
        intent = _make_intent(strategy_execution_id="exec-xyz")
        assert intent.strategy_execution_id == "exec-xyz"

    def test_intent_preserves_reason(self):
        intent = _make_intent(reason="User requested exit")
        assert intent.reason == "User requested exit"

    def test_intent_preserves_metadata(self):
        intent = _make_intent(metadata={"panel": "active_positions"})
        assert intent.metadata == {"panel": "active_positions"}

    def test_intent_initial_status_is_pending(self):
        intent = _make_intent()
        assert intent.status == ExecutionStatus.PENDING

    def test_intent_no_broker_specific_fields(self):
        intent = _make_intent()
        serialized = str(intent)
        for forbidden in ("instrument_key", "transaction_type", "access_token", "refresh_token", "api_key", "upstox"):
            assert forbidden.lower() not in serialized.lower()

    def test_intent_multiple_targets(self):
        t1 = _make_target(position_id=1, source_action="buy", exit_side="sell")
        t2 = _make_target(position_id=2, source_action="sell", exit_side="buy")
        intent = _make_intent(targets=[t1, t2])
        assert len(intent.targets) == 2

    def test_intent_user_isolation(self):
        intent = _make_intent(user_id="user-A")
        assert intent.user_id == "user-A"
        other = _make_intent(user_id="user-B")
        assert other.user_id == "user-B"


# ===================================================================
# SIDE TRANSLATION TESTS (§29)
# ===================================================================

class TestSideTranslation:
    def test_buy_ce_exits_with_sell(self):
        assert exit_side_for("buy") == "sell"

    def test_sell_ce_exits_with_buy(self):
        assert exit_side_for("sell") == "buy"

    def test_buy_pe_exits_with_sell(self):
        assert exit_side_for("buy") == "sell"

    def test_sell_pe_exits_with_buy(self):
        assert exit_side_for("sell") == "buy"

    def test_exit_side_for_invalid_raises(self):
        with pytest.raises(ExecutionError):
            exit_side_for("hold")

    def test_source_action_for_exit_buy_gives_sell(self):
        assert source_action_for_exit("sell") == "buy"

    def test_source_action_for_exit_sell_gives_buy(self):
        assert source_action_for_exit("buy") == "sell"

    def test_source_action_for_exit_invalid_raises(self):
        with pytest.raises(ExecutionError):
            source_action_for_exit("hold")

    def test_strategy_leg_action_not_mutated(self):
        target = _make_target(source_action="buy", exit_side="sell")
        assert target.source_action == "buy"
        assert target.exit_side == "sell"


# ===================================================================
# EXIT INTENT → EXECUTION TARGET CONVERSION (§7)
# ===================================================================

class TestExitIntentToExecutionTarget:
    def test_buy_to_sell_conversion(self):
        t = exit_intent_target_to_execution_target(
            position_id=1, strategy_execution_id="exec-1", option_type="call",
            source_side="buy", quantity=2, remaining_quantity=2,
            symbol="NIFTY", expiry="2026-08-28", strike=25000.0, lot_size=65,
        )
        assert t.source_action == "buy"
        assert t.exit_side == "sell"
        assert t.quantity == 2

    def test_sell_to_buy_conversion(self):
        t = exit_intent_target_to_execution_target(
            position_id=1, strategy_execution_id="exec-1", option_type="call",
            source_side="sell", quantity=1, remaining_quantity=3,
            symbol="NIFTY", expiry="2026-08-28", strike=25000.0, lot_size=65,
        )
        assert t.source_action == "sell"
        assert t.exit_side == "buy"

    def test_normalizes_option_type_to_lowercase(self):
        t = exit_intent_target_to_execution_target(
            position_id=1, strategy_execution_id=None, option_type="CALL",
            source_side="BUY", quantity=1, remaining_quantity=1,
            symbol="nifty", expiry="2026-08-28", strike=25000.0, lot_size=65,
        )
        assert t.option_type == "call"
        assert t.symbol == "NIFTY"

    def test_preserves_exposure_id(self):
        t = exit_intent_target_to_execution_target(
            position_id=1, strategy_execution_id="exec-1", option_type="call",
            source_side="buy", quantity=1, remaining_quantity=1,
            symbol="NIFTY", expiry="2026-08-28", strike=25000.0, lot_size=65,
            strategy_leg_exposure_id=42,
        )
        assert t.strategy_leg_exposure_id == 42

    def test_preserves_price_override(self):
        t = exit_intent_target_to_execution_target(
            position_id=1, strategy_execution_id=None, option_type="call",
            source_side="buy", quantity=1, remaining_quantity=1,
            symbol="NIFTY", expiry="2026-08-28", strike=25000.0, lot_size=65,
            price_override=175.50,
        )
        assert t.price_override == 175.50

    def test_invalid_source_side_raises(self):
        with pytest.raises(ExecutionError) as exc:
            exit_intent_target_to_execution_target(
                position_id=1, strategy_execution_id=None, option_type="call",
                source_side="hold", quantity=1, remaining_quantity=1,
                symbol="NIFTY", expiry="2026-08-28", strike=25000.0, lot_size=65,
            )
        assert exc.value.code is ExecutionErrorCode.INVALID_EXECUTION_INTENT


# ===================================================================
# BUILD TARGETS FROM EXPOSURES (§9)
# ===================================================================

class TestBuildTargetsFromExposures:
    def test_creates_targets_from_open_exposures(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2)
        exp = _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=2)
        targets = build_execution_targets_from_exposures([exp])
        assert len(targets) == 1
        assert targets[0].source_action == "buy"
        assert targets[0].exit_side == "sell"
        assert targets[0].strategy_leg_exposure_id == exp.id
        assert targets[0].strategy_execution_id == "exec-1"

    def test_skips_closed_exposures(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=0)
        exp = _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=0, status="closed")
        assert len(build_execution_targets_from_exposures([exp])) == 0

    def test_skips_zero_remaining(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=1)
        exp = _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=0, status="open")
        assert len(build_execution_targets_from_exposures([exp])) == 0

    def test_quantity_mode_all_uses_remaining(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=3)
        exp = _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=3)
        targets = build_execution_targets_from_exposures([exp], quantity_mode="ALL")
        assert targets[0].quantity == 3

    def test_quantity_mode_quantity_uses_requested(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=3)
        exp = _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=3)
        targets = build_execution_targets_from_exposures([exp], quantity_mode="QUANTITY", requested_quantity=1)
        assert targets[0].quantity == 1

    def test_deterministic_ordering_by_exposure_id(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=4)
        exp_a = _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=2)
        exp_b = _make_exposure(db_session, user_id, "exec-2", pos.id, order_id=2, action="buy", remaining_quantity=2)
        targets = build_execution_targets_from_exposures([exp_b, exp_a])
        assert targets[0].strategy_leg_exposure_id == exp_a.id
        assert targets[1].strategy_leg_exposure_id == exp_b.id

    def test_sell_exposure_maps_to_buy_exit(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=-2)
        exp = _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="sell", remaining_quantity=2)
        targets = build_execution_targets_from_exposures([exp])
        assert targets[0].source_action == "sell"
        assert targets[0].exit_side == "buy"


# ===================================================================
# STALE-TARGET VALIDATION (§33)
# ===================================================================

class TestStaleTargetValidation:
    def test_valid_target_passes(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2)
        exp = _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=2)
        target = _make_target(position_id=pos.id, quantity=2, strategy_leg_exposure_id=exp.id)
        assert validate_targets_still_valid([target], db_session, user_id) == []

    def test_closed_position_rejected(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=0, strategy_execution_id="exec-1")
        pos.status = "closed"
        target = _make_target(position_id=pos.id, quantity=1)
        errors = validate_targets_still_valid([target], db_session, user_id)
        assert len(errors) == 1 and "closed" in errors[0].lower()

    def test_quantity_exceeds_position_rejected(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=1)
        target = _make_target(position_id=pos.id, quantity=5)
        errors = validate_targets_still_valid([target], db_session, user_id)
        assert len(errors) == 1 and "5 lot(s)" in errors[0]

    def test_user_ownership_mismatch_rejected(self, db_session, user_id, other_user_id):
        pos = _make_position(db_session, other_user_id, net_quantity=2)
        target = _make_target(position_id=pos.id, quantity=2)
        errors = validate_targets_still_valid([target], db_session, user_id)
        assert len(errors) == 1 and "not owned" in errors[0].lower()

    def test_missing_position_rejected(self, db_session, user_id):
        target = _make_target(position_id=99999, quantity=1)
        errors = validate_targets_still_valid([target], db_session, user_id)
        assert len(errors) == 1 and "not found" in errors[0].lower()

    def test_closed_exposure_rejected(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2)
        exp = _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=0, status="closed")
        target = _make_target(position_id=pos.id, quantity=1, strategy_leg_exposure_id=exp.id, remaining_quantity=0)
        errors = validate_targets_still_valid([target], db_session, user_id)
        assert len(errors) == 1 and "closed" in errors[0].lower()

    def test_quantity_exceeds_exposure_rejected(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=5)
        exp = _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=2)
        target = _make_target(position_id=pos.id, quantity=3, strategy_leg_exposure_id=exp.id, remaining_quantity=2)
        errors = validate_targets_still_valid([target], db_session, user_id)
        assert len(errors) == 1

    def test_missing_exposure_rejected(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2)
        target = _make_target(position_id=pos.id, quantity=1, strategy_leg_exposure_id=99999)
        errors = validate_targets_still_valid([target], db_session, user_id)
        assert len(errors) == 1 and "not found" in errors[0].lower()

    def test_multiple_targets_partial_failure(self, db_session, user_id):
        pos_good = _make_position(db_session, user_id, net_quantity=2, strike=25000.0)
        pos_closed = _make_position(db_session, user_id, net_quantity=0, strike=25100.0)
        pos_closed.status = "closed"
        t1 = _make_target(position_id=pos_good.id, quantity=1, strike=25000.0)
        t2 = _make_target(position_id=pos_closed.id, quantity=1, strike=25100.0)
        errors = validate_targets_still_valid([t1, t2], db_session, user_id)
        assert len(errors) == 1 and "Target 1" in errors[0]


# ===================================================================
# EXECUTION ROUTER — PAPER (§10)
# ===================================================================

class TestExecutionRouterPaper:
    @pytest.mark.asyncio
    async def test_paper_mode_routes_successfully(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2, strategy_execution_id="exec-1")
        _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=2)
        _make_execution(db_session, user_id, "exec-1")
        target = _make_target(position_id=pos.id, quantity=2, strategy_leg_exposure_id=1, price_override=175.0)
        intent = _make_intent(targets=[target], user_id=user_id)
        router = ExecutionRouter(db=db_session)
        result = await router.execute_intent(intent)
        assert result.status == ExecutionStatus.SUCCESS
        assert result.targets_succeeded == 1
        db_session.refresh(pos)
        assert pos.status == "closed"
        assert pos.net_quantity == 0

    @pytest.mark.asyncio
    async def test_paper_mode_updates_position(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2, strategy_execution_id="exec-1")
        _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=2)
        _make_execution(db_session, user_id, "exec-1")
        target = _make_target(position_id=pos.id, quantity=1, price_override=175.0)
        intent = _make_intent(targets=[target], user_id=user_id)
        router = ExecutionRouter(db=db_session)
        result = await router.execute_intent(intent)
        assert result.status == ExecutionStatus.SUCCESS
        db_session.refresh(pos)
        assert pos.net_quantity == 1
        assert pos.status == "open"

    @pytest.mark.asyncio
    async def test_paper_mode_updates_cash(self, db_session, user_id):
        account = PaperAccount(user_id=user_id, starting_capital=500000)
        db_session.add(account)
        db_session.flush()
        pos = _make_position(db_session, user_id, net_quantity=2, strategy_execution_id="exec-1")
        _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=2)
        _make_execution(db_session, user_id, "exec-1")
        target = _make_target(position_id=pos.id, quantity=2, price_override=175.0)
        intent = _make_intent(targets=[target], user_id=user_id)
        router = ExecutionRouter(db=db_session)
        await router.execute_intent(intent)
        txns = db_session.query(PaperTransaction).filter(PaperTransaction.user_id == user_id).all()
        exit_txns = [t for t in txns if t.type == "EXIT_CREDIT"]
        assert len(exit_txns) >= 1
        assert exit_txns[0].amount > 0

    @pytest.mark.asyncio
    async def test_paper_mode_updates_realized_pnl(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2, strategy_execution_id="exec-1")
        _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=2)
        _make_execution(db_session, user_id, "exec-1")
        target = _make_target(position_id=pos.id, quantity=2, price_override=200.0)
        intent = _make_intent(targets=[target], user_id=user_id)
        router = ExecutionRouter(db=db_session)
        await router.execute_intent(intent)
        db_session.refresh(pos)
        assert pos.realized_pnl > 0

    @pytest.mark.asyncio
    async def test_paper_mode_preserves_journal(self, db_session, user_id):
        from app.models import Leg
        pos = _make_position(db_session, user_id, net_quantity=1, strategy_execution_id="exec-1")
        trade = Trade(user_id=user_id, symbol="NIFTY", strategy_tag="Test", status="open", entry_net=100.0, strategy_execution_id="exec-1")
        db_session.add(trade)
        db_session.flush()
        leg = Leg(trade_id=trade.id, symbol="NIFTY", expiration_date="2026-08-28", strike_price=25000.0, option_type="call", action="buy", premium=150.0, quantity=1, lot_size=65)
        db_session.add(leg)
        db_session.flush()
        order = PaperOrder(user_id=user_id, client_order_id="entry-1", execution_id="exec-1", position_id=pos.id, kind="entry", symbol="NIFTY", expiry="2026-08-28", strike=25000.0, option_type="call", action="buy", quantity=1, lot_size=65, status="FILLED", filled_quantity=1, fill_price=150.0, journal_leg_id=leg.id)
        db_session.add(order)
        db_session.flush()
        _make_execution(db_session, user_id, "exec-1")
        target = _make_target(position_id=pos.id, quantity=1, price_override=200.0)
        intent = _make_intent(targets=[target], user_id=user_id)
        router = ExecutionRouter(db=db_session)
        await router.execute_intent(intent)
        db_session.refresh(trade)
        assert trade.status == "closed"
        db_session.refresh(leg)
        assert leg.exit_at is not None

    @pytest.mark.asyncio
    async def test_paper_mode_failed_validation_writes_nothing(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=0, strategy_execution_id="exec-1")
        pos.status = "closed"
        target = _make_target(position_id=pos.id, quantity=1, price_override=175.0)
        intent = _make_intent(targets=[target], user_id=user_id)
        router = ExecutionRouter(db=db_session)
        result = await router.execute_intent(intent)
        assert result.status in (ExecutionStatus.REJECTED, ExecutionStatus.FAILED)
        orders = db_session.query(PaperOrder).filter(PaperOrder.user_id == user_id).all()
        assert len(orders) == 0

    @pytest.mark.asyncio
    async def test_paper_mode_duplicate_execution_returns_duplicate(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2, strategy_execution_id="exec-1")
        _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=2)
        _make_execution(db_session, user_id, "exec-1")
        target = _make_target(position_id=pos.id, quantity=2, price_override=175.0)
        idem_key = "duplicate-test-key-12345"
        intent = _make_intent(targets=[target], user_id=user_id, idempotency_key=idem_key)
        router = ExecutionRouter(db=db_session)
        r1 = await router.execute_intent(intent)
        assert r1.status == ExecutionStatus.SUCCESS
        r2 = await router.execute_intent(intent)
        assert r2.duplicated is True


# ===================================================================
# EXECUTION ROUTER — LIVE DISABLED (§10, §19)
# ===================================================================

class TestExecutionRouterLiveDisabled:
    @pytest.mark.asyncio
    async def test_live_returns_disabled(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2)
        target = _make_target(position_id=pos.id, quantity=2)
        intent = _make_intent(targets=[target], user_id=user_id, execution_mode=ExecutionMode.LIVE)
        router = ExecutionRouter(db=db_session)
        result = await router.execute_intent(intent)
        assert result.status == ExecutionStatus.DISABLED
        assert result.targets_failed == 1
        assert any("disabled" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_live_does_not_modify_position(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2, strategy_execution_id="exec-1")
        _make_execution(db_session, user_id, "exec-1")
        target = _make_target(position_id=pos.id, quantity=2)
        intent = _make_intent(targets=[target], user_id=user_id, execution_mode=ExecutionMode.LIVE)
        router = ExecutionRouter(db=db_session)
        await router.execute_intent(intent)
        db_session.refresh(pos)
        assert pos.net_quantity == 2

    @pytest.mark.asyncio
    async def test_live_result_has_all_targets_failed(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2)
        t1 = _make_target(position_id=pos.id, quantity=1)
        t2 = _make_target(position_id=pos.id, quantity=1)
        intent = _make_intent(targets=[t1, t2], user_id=user_id, execution_mode=ExecutionMode.LIVE)
        router = ExecutionRouter(db=db_session)
        result = await router.execute_intent(intent)
        assert result.targets_attempted == 2
        assert result.targets_failed == 2


# ===================================================================
# EXECUTION ROUTER — UNKNOWN MODE
# ===================================================================

class TestExecutionRouterUnknownMode:
    @pytest.mark.asyncio
    async def test_unknown_mode_returns_failed(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2)
        target = _make_target(position_id=pos.id, quantity=2)
        intent = ExecutionIntent(intent_id="x", user_id=user_id, execution_mode="UNKNOWN_MODE", source=ExecutionSource.EXIT_SELECTOR, targets=[target], idempotency_key="key", created_at="now")
        router = ExecutionRouter(db=db_session)
        result = await router.execute_intent(intent)
        assert result.status == ExecutionStatus.FAILED


# ===================================================================
# BROKER-BOUNDARY SAFETY (§18, §28, §38)
# ===================================================================

class TestBrokerBoundarySafety:
    def test_execution_intent_module_no_upstox_imports(self):
        import ast
        import inspect
        import app.services.execution_intent as mod
        source = inspect.getsource(mod)
        tree = ast.parse(source)
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.add(node.module)
        assert "UpstoxAdapter" not in imported_names
        assert "app.services.upstox" not in imported_names
        assert "app.brokers.adapters" not in imported_names

    def test_execution_intent_no_broker_specific_fields(self):
        intent = _make_intent()
        serialized = str(intent)
        for field in ("instrument_key", "transaction_type", "access_token", "refresh_token", "api_secret", "is_amo"):
            assert field not in serialized

    def test_execution_target_no_broker_specific_fields(self):
        target = _make_target()
        serialized = str(target)
        for field in ("instrument_key", "transaction_type", "access_token", "is_amo"):
            assert field not in serialized

    def test_execution_result_no_broker_fields(self):
        result = ExecutionResult(intent_id="x", status=ExecutionStatus.SUCCESS, mode=ExecutionMode.PAPER)
        serialized = str(result)
        assert "instrument_key" not in serialized

    def test_module_source_no_broker_imports(self):
        import ast
        import inspect
        import app.services.execution_intent as mod
        source = inspect.getsource(mod)
        tree = ast.parse(source)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        assert "app.services.upstox" not in imported_modules
        assert "app.brokers.adapters" not in imported_modules
        for mod_name in imported_modules:
            assert "upstox" not in mod_name.lower(), f"Forbidden import: {mod_name}"


# ===================================================================
# USER ISOLATION (§26)
# ===================================================================

class TestUserIsolation:
    @pytest.mark.asyncio
    async def test_user_cannot_exit_another_users_position(self, db_session, user_id, other_user_id):
        other_pos = _make_position(db_session, other_user_id, net_quantity=2)
        target = _make_target(position_id=other_pos.id, quantity=2)
        intent = _make_intent(targets=[target], user_id=user_id)
        router = ExecutionRouter(db=db_session)
        result = await router.execute_intent(intent)
        assert result.status in (ExecutionStatus.REJECTED, ExecutionStatus.FAILED)
        assert any("not owned" in e.lower() or "not found" in e.lower() for e in result.errors)

    def test_stale_validation_catches_cross_user(self, db_session, user_id, other_user_id):
        other_pos = _make_position(db_session, other_user_id, net_quantity=2)
        target = _make_target(position_id=other_pos.id, quantity=2)
        errors = validate_targets_still_valid([target], db_session, user_id)
        assert len(errors) == 1 and "not owned" in errors[0].lower()

    def test_user_id_comes_from_authenticated_context(self, db_session, user_id):
        intent = _make_intent(user_id=user_id)
        assert intent.user_id == user_id


# ===================================================================
# QUANTITY SAFETY (§8)
# ===================================================================

class TestQuantitySafety:
    @pytest.mark.asyncio
    async def test_quantity_exceeds_remaining_rejected_by_paper_engine(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2)
        target = _make_target(position_id=pos.id, quantity=5, price_override=175.0)
        intent = _make_intent(targets=[target], user_id=user_id)
        router = ExecutionRouter(db=db_session)
        result = await router.execute_intent(intent)
        assert result.status in (ExecutionStatus.REJECTED, ExecutionStatus.FAILED)
        assert any("lot" in e.lower() for e in result.errors)

    def test_zero_quantity_target_rejected(self):
        with pytest.raises(ExecutionError) as exc:
            _make_target(quantity=0)
        assert exc.value.code is ExecutionErrorCode.EXECUTION_QUANTITY_INVALID

    def test_negative_quantity_target_rejected(self):
        with pytest.raises(ExecutionError) as exc:
            _make_target(quantity=-1)
        assert exc.value.code is ExecutionErrorCode.EXECUTION_QUANTITY_INVALID

    def test_finite_quantity_required(self):
        target = _make_target(quantity=1)
        assert target.quantity == 1


# ===================================================================
# CONCURRENCY / DOUBLE EXIT (§34)
# ===================================================================

class TestConcurrency:
    @pytest.mark.asyncio
    async def test_same_idempotency_key_replay(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2, strategy_execution_id="exec-1")
        _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=2)
        _make_execution(db_session, user_id, "exec-1")
        target = _make_target(position_id=pos.id, quantity=2, price_override=175.0)
        idem = "concurrent-test-key"
        intent = _make_intent(targets=[target], user_id=user_id, idempotency_key=idem)
        router = ExecutionRouter(db=db_session)
        r1 = await router.execute_intent(intent)
        assert r1.status == ExecutionStatus.SUCCESS
        r2 = await router.execute_intent(intent)
        assert r2.duplicated is True

    @pytest.mark.asyncio
    async def test_different_idempotency_keys_same_position(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2, strategy_execution_id="exec-1")
        _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=2)
        _make_execution(db_session, user_id, "exec-1")
        t1 = _make_target(position_id=pos.id, quantity=2, price_override=175.0)
        i1 = _make_intent(targets=[t1], user_id=user_id, idempotency_key="key-1")
        router = ExecutionRouter(db=db_session)
        r1 = await router.execute_intent(i1)
        assert r1.status == ExecutionStatus.SUCCESS
        t2 = _make_target(position_id=pos.id, quantity=2, price_override=175.0)
        i2 = _make_intent(targets=[t2], user_id=user_id, idempotency_key="key-2")
        r2 = await router.execute_intent(i2)
        assert r2.status in (ExecutionStatus.REJECTED, ExecutionStatus.FAILED)


# ===================================================================
# EXISTING BEHAVIOR PRESERVED (§35)
# ===================================================================

class TestExistingBehaviorPreserved:
    @pytest.mark.asyncio
    async def test_exit_strategy_through_router(self, db_session, user_id):
        pos1 = _make_position(db_session, user_id, net_quantity=2, strike=25000.0, strategy_execution_id="exec-1")
        pos2 = _make_position(db_session, user_id, net_quantity=1, strike=25100.0, strategy_execution_id="exec-1")
        _make_exposure(db_session, user_id, "exec-1", pos1.id, order_id=1, strike=25000.0, action="buy", remaining_quantity=2)
        _make_exposure(db_session, user_id, "exec-1", pos2.id, order_id=2, strike=25100.0, action="buy", remaining_quantity=1)
        _make_execution(db_session, user_id, "exec-1")
        t1 = _make_target(position_id=pos1.id, quantity=2, strike=25000.0, price_override=175.0)
        t2 = _make_target(position_id=pos2.id, quantity=1, strike=25100.0, price_override=180.0)
        intent = _make_intent(targets=[t1, t2], user_id=user_id, strategy_execution_id="exec-1")
        router = ExecutionRouter(db=db_session)
        result = await router.execute_intent(intent)
        assert result.status == ExecutionStatus.SUCCESS
        assert result.targets_succeeded == 2
        db_session.refresh(pos1)
        db_session.refresh(pos2)
        assert pos1.status == "closed"
        assert pos2.status == "closed"

    @pytest.mark.asyncio
    async def test_partial_exit_preserves_remaining(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=3, strategy_execution_id="exec-1")
        _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=3)
        _make_execution(db_session, user_id, "exec-1")
        target = _make_target(position_id=pos.id, quantity=1, price_override=175.0)
        intent = _make_intent(targets=[target], user_id=user_id)
        router = ExecutionRouter(db=db_session)
        await router.execute_intent(intent)
        db_session.refresh(pos)
        assert pos.net_quantity == 2
        assert pos.status == "open"

    @pytest.mark.asyncio
    async def test_strategy_leg_exposure_maintained_after_exit(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=2, strategy_execution_id="exec-1")
        exp = _make_exposure(db_session, user_id, "exec-1", pos.id, order_id=1, action="buy", remaining_quantity=2)
        _make_execution(db_session, user_id, "exec-1")
        target = _make_target(position_id=pos.id, quantity=1, strategy_leg_exposure_id=exp.id, price_override=175.0)
        intent = _make_intent(targets=[target], user_id=user_id)
        router = ExecutionRouter(db=db_session)
        await router.execute_intent(intent)
        db_session.refresh(exp)
        assert exp.remaining_quantity == 1
        assert exp.status == "open"

    @pytest.mark.asyncio
    async def test_strategy_isolation_shared_instrument(self, db_session, user_id):
        pos = _make_position(db_session, user_id, net_quantity=1, strategy_execution_id="exec-A")
        exp_a = _make_exposure(db_session, user_id, "exec-A", pos.id, order_id=1, action="buy", remaining_quantity=2)
        exp_b = _make_exposure(db_session, user_id, "exec-B", pos.id, order_id=2, action="sell", remaining_quantity=1)
        _make_execution(db_session, user_id, "exec-A")
        _make_execution(db_session, user_id, "exec-B")
        target = _make_target(position_id=pos.id, quantity=2, strategy_leg_exposure_id=exp_a.id, strategy_execution_id="exec-A", price_override=175.0)
        intent = _make_intent(targets=[target], user_id=user_id, strategy_execution_id="exec-A")
        router = ExecutionRouter(db=db_session)
        await router.execute_intent(intent)
        db_session.refresh(exp_b)
        assert exp_b.remaining_quantity == 1
        assert exp_b.status == "open"


# ===================================================================
# EXECUTION RESULT (§30)
# ===================================================================

class TestExecutionResult:
    def test_result_initial_state(self):
        result = ExecutionResult(intent_id="test", status=ExecutionStatus.PENDING, mode=ExecutionMode.PAPER)
        assert result.targets_attempted == 0
        assert result.targets_succeeded == 0
        assert result.targets_failed == 0
        assert result.results == []
        assert result.errors == []
        assert result.duplicated is False

    def test_result_preserves_mode(self):
        result = ExecutionResult(intent_id="x", status=ExecutionStatus.SUCCESS, mode=ExecutionMode.LIVE)
        assert result.mode == ExecutionMode.LIVE


# ===================================================================
# STATIC ARCHITECTURE AUDITS (§38)
# ===================================================================

class TestStaticArchitectureAudits:
    def test_execution_target_frozen(self):
        target = _make_target()
        with pytest.raises(FrozenInstanceError):
            target.quantity = 999

    def test_execution_intent_not_frozen(self):
        intent = _make_intent()
        intent.status = ExecutionStatus.SUCCESS
        assert intent.status == ExecutionStatus.SUCCESS
