"""Phase 6.0 tests — Capital & Margin Foundation.

Covers the phase's §23 test matrix: source classification, available vs
unavailable, premium vs capital separation, defined-debit estimated capital,
credit-strategy estimated capital unavailable, broker margin unavailable,
broker margin available via the provider abstraction, paper cash separate
from broker funds, user isolation, multi-leg strategy context, null vs zero,
no Infinity/NaN, source labels preserved, no accidental ROI aliasing, and no
Return-on-Capital calculation in Phase 6.0.

Pure helpers are tested directly; the summary goes through the router with
the same fixtures as test_performance.py (market gate open, mocked chain
data, in-memory SQLite).
"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.services import token_store
from app.services.upstox import UpstoxError
from app.services.capital import (
    BASIS_PREMIUM,
    SOURCE_BROKER_REPORTED,
    SOURCE_CALCULATED,
    SOURCE_ESTIMATED,
    STATUS_AVAILABLE,
    STATUS_PARTIAL,
    STATUS_UNAVAILABLE,
    UnavailableMarginProvider,
    StaticMarginProvider,
    aggregate_estimates,
    capital_efficiency_inputs,
    capital_value,
    estimate_capital_for_execution,
    get_capital_summary,
    is_valid_number,
    premium_outlay_for_orders,
)

LOT = 65
EXPIRY = "2026-08-27"

DEFAULT_CHAIN = {
    EXPIRY: {
        24350: {"call": 125.25, "put": 90.0},
        24550: {"call": 35.60, "put": 200.0},
        25000: {"call": 200.0, "put": 80.0},
    },
}


def chain_payload(expiry, quotes):
    data = []
    for strike, sides in quotes.items():
        item = {"strike_price": strike, "underlying_spot_price": 24000.0}
        item["call_options"] = {"market_data": {"ltp": sides["call"]}, "option_greeks": {}}
        item["put_options"] = {"market_data": {"ltp": sides["put"]}, "option_greeks": {}}
        data.append(item)
    return {"data": data}


@pytest.fixture(autouse=True)
def market_open_gate():
    status = SimpleNamespace(
        status="open", source="test", trade_date="2026-08-14",
        checked_at="2026-08-14T10:00:00+05:30", message="open", error=None,
    )
    with patch("app.routers.paper.get_market_status", new=AsyncMock(return_value=status)):
        yield


@pytest.fixture(autouse=True)
def chain_mock():
    async def fake(token, instrument_key, expiry):
        return chain_payload(expiry, DEFAULT_CHAIN.get(expiry, {}))

    with patch("app.services.upstox.get_option_chain", new=AsyncMock(side_effect=fake)):
        yield


@pytest.fixture(autouse=True)
def broker_api_unavailable():
    """Phase 6.1: the router now wires the real UpstoxMarginProvider whenever a
    session token exists. By default both broker APIs are UNAVAILABLE so these
    capital tests stay deterministic and never touch the network; the Phase 6.1
    tests in test_broker_margin.py patch them with canned responses.
    """

    async def _raise(*args, **kwargs):
        raise UpstoxError(502, "mock: broker API unavailable")

    with (
        patch("app.services.upstox.get_funds_and_margin", new=AsyncMock(side_effect=_raise)),
        patch("app.services.upstox.get_margin_details", new=AsyncMock(side_effect=_raise)),
    ):
        yield


@pytest.fixture
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


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def logged_in(client):
    return token_store.set_token("tok-phase60")


def headers(session_id):
    return {"X-Session-Id": session_id}


# ---- payload builders -------------------------------------------------------

_counter = {"n": 0}


def next_id(prefix):
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']:06d}"


def leg(expiry, strike, option_type, action):
    return {
        "symbol": "NIFTY", "expiration_date": expiry, "strike_price": strike,
        "option_type": option_type, "action": action, "quantity": 1, "lot_size": LOT,
    }


# Long call: buy 24350 CE @125.25 → net debit 8,141.25, premium outlay 8,141.25.
def long_call_payload(**overrides):
    payload = {
        "client_order_id": next_id("exec"),
        "symbol": "NIFTY",
        "strategy_tag": "Long Call",
        "starting_capital": 500000,
        "legs": [leg(EXPIRY, 24350, "call", "buy")],
    }
    payload.update(overrides)
    return payload


# Bull call spread: buy 24350 CE @125.25, sell 24550 CE @35.60
# → net debit 5,827.25; premium OUTLAY (gross long) 8,141.25 — the two are
# deliberately different so the premium-vs-capital separation is testable.
def bull_call_spread_payload(**overrides):
    payload = {
        "client_order_id": next_id("exec"),
        "symbol": "NIFTY",
        "strategy_tag": "Bull Call Spread",
        "starting_capital": 500000,
        "legs": [leg(EXPIRY, 24350, "call", "buy"), leg(EXPIRY, 24550, "call", "sell")],
    }
    payload.update(overrides)
    return payload


# Short put (naked credit): sell 24350 PE @90 → net credit 5,850.
def short_put_payload(**overrides):
    payload = {
        "client_order_id": next_id("exec"),
        "symbol": "NIFTY",
        "strategy_tag": "Short Put",
        "starting_capital": 500000,
        "legs": [leg(EXPIRY, 24350, "put", "sell")],
    }
    payload.update(overrides)
    return payload


def execute(client, session_id, payload):
    return client.post("/paper/executions", headers=headers(session_id), json=payload)


def get_capital(client, session_id):
    return client.get("/paper/capital", headers=headers(session_id))


def open_position_ids(db_session):
    from app.models import Position

    return [p.id for p in db_session.query(Position).filter(Position.status == "open").all()]


# =============================================================================
# §23-1 source classification
# =============================================================================


def test_source_classification_labels_preserved():
    assert capital_value(37503, SOURCE_BROKER_REPORTED)["source"] == "BROKER_REPORTED"
    assert capital_value(5827.25, SOURCE_ESTIMATED)["source"] == "ESTIMATED"
    assert capital_value(492000, SOURCE_CALCULATED)["source"] == "CALCULATED"
    assert capital_value(None, SOURCE_BROKER_REPORTED)["source"] == "BROKER_REPORTED"


# =============================================================================
# §23-2 available vs unavailable
# =============================================================================


def test_available_vs_unavailable():
    v = capital_value(5827.25, SOURCE_ESTIMATED)
    assert v["value"] == 5827.25 and v["status"] == STATUS_AVAILABLE
    u = capital_value(None, SOURCE_BROKER_REPORTED)
    assert u["value"] is None and u["status"] == STATUS_UNAVAILABLE


# =============================================================================
# §23-11 null vs zero + §23-12 no Infinity / NaN
# =============================================================================


def test_null_vs_zero_missing_is_never_zero():
    assert capital_value(None, SOURCE_ESTIMATED)["value"] is None
    assert capital_value(None, SOURCE_BROKER_REPORTED)["value"] is None
    # A real zero IS a valid figure (e.g. premium outlay of a pure-credit
    # strategy) — it must remain a zero, not be swallowed.
    assert capital_value(0.0, SOURCE_CALCULATED) == {
        "value": 0.0, "source": "CALCULATED", "status": "available",
    }


def test_no_nan_or_infinity_ever_becomes_valid():
    assert capital_value(float("nan"), SOURCE_ESTIMATED)["value"] is None
    assert capital_value(float("nan"), SOURCE_ESTIMATED)["status"] == STATUS_UNAVAILABLE
    assert capital_value(float("inf"), SOURCE_BROKER_REPORTED)["value"] is None
    assert capital_value(float("-inf"), SOURCE_BROKER_REPORTED)["value"] is None
    assert not is_valid_number(float("nan"))
    assert not is_valid_number(float("inf"))
    assert is_valid_number(0.0)
    assert not is_valid_number(None)


# =============================================================================
# §23-8 defined-debit estimated capital / §23-5 credit unavailable
# =============================================================================


def test_estimate_capital_for_defined_debit():
    est = estimate_capital_for_execution(5827.25)
    assert est == {"value": 5827.25, "basis": BASIS_PREMIUM}


def test_estimate_capital_for_credit_is_null():
    assert estimate_capital_for_execution(-5850.0) == {"value": None, "basis": None}
    assert estimate_capital_for_execution(0.0) == {"value": None, "basis": None}
    assert estimate_capital_for_execution(None) == {"value": None, "basis": None}


def test_aggregate_estimates_available_partial_unavailable():
    all_ok = [{"value": 5827.25, "basis": BASIS_PREMIUM}, {"value": 100.0, "basis": BASIS_PREMIUM}]
    agg = aggregate_estimates(all_ok)
    assert agg["status"] == STATUS_AVAILABLE and agg["value"] == 5927.25

    some = [{"value": 5827.25, "basis": BASIS_PREMIUM}, {"value": None, "basis": None}]
    agg = aggregate_estimates(some)
    assert agg["status"] == STATUS_PARTIAL and agg["value"] == 5827.25

    none = [{"value": None, "basis": None}, {"value": None, "basis": None}]
    agg = aggregate_estimates(none)
    assert agg["status"] == STATUS_UNAVAILABLE and agg["value"] is None

    assert aggregate_estimates([])["status"] == STATUS_UNAVAILABLE


# =============================================================================
# §23-15 no Return-on-Capital calculation (§15/§16)
# =============================================================================


def test_capital_efficiency_inputs_never_computes_metric():
    inputs = capital_efficiency_inputs(1200.0, None, 5827.25)
    assert inputs == {"pnl": 1200.0, "capital_used": 5827.25, "available": True}
    # The contract is EXACTLY {pnl, capital_used, available} — no ratio, no
    # return-on-capital key, no ROI alias.
    assert set(inputs.keys()) == {"pnl", "capital_used", "available"}
    assert "return_on_capital" not in inputs and "roc" not in inputs and "roi" not in inputs


def test_capital_efficiency_inputs_unavailable_when_capital_missing():
    inputs = capital_efficiency_inputs(1200.0, None, None)
    assert inputs == {"pnl": None, "capital_used": None, "available": False}
    # Missing P&L also disables the future metric.
    assert capital_efficiency_inputs(None, None, 5827.25)["available"] is False
    assert capital_efficiency_inputs(None, None, None)["available"] is False


# =============================================================================
# §23-3 premium vs capital separation (API-level, whole strategy)
# =============================================================================


def test_premium_outlay_and_estimated_capital_are_distinct(client, logged_in):
    assert execute(client, logged_in, bull_call_spread_payload()).status_code == 200
    body = get_capital(client, logged_in).json()

    # Gross long premium (only the bought leg) ≠ net debit (bought − sold).
    assert body["premium_outlay"]["value"] == pytest.approx(125.25 * LOT, abs=0.01)
    assert body["premium_outlay"]["source"] == SOURCE_CALCULATED
    assert body["estimated_capital"]["value"] == pytest.approx(89.65 * LOT, abs=0.01)
    assert body["estimated_capital"]["source"] == SOURCE_ESTIMATED
    assert body["estimated_capital_basis"] == BASIS_PREMIUM
    assert body["strategies"][0]["premium_outlay"] != body["strategies"][0]["estimated_capital"]


# =============================================================================
# §23-10 multi-leg strategy context (§17)
# =============================================================================


def test_multi_leg_strategy_is_one_capital_unit(client, logged_in):
    assert execute(client, logged_in, bull_call_spread_payload()).status_code == 200
    body = get_capital(client, logged_in).json()

    strategies = body["strategies"]
    assert len(strategies) == 1  # ONE whole-strategy row for both legs
    row = strategies[0]
    assert row["strategy_tag"] == "Bull Call Spread"
    assert row["entry_net"] == pytest.approx(89.65 * LOT, abs=0.01)  # +5,827.25 debit
    assert row["premium_outlay"] == pytest.approx(125.25 * LOT, abs=0.01)
    assert row["estimated_capital"] == pytest.approx(89.65 * LOT, abs=0.01)
    assert row["estimated_capital_basis"] == BASIS_PREMIUM


# =============================================================================
# §23-6 broker margin unavailable (default provider)
# =============================================================================


def test_broker_margin_unavailable_by_default(client, logged_in):
    assert execute(client, logged_in, bull_call_spread_payload()).status_code == 200
    body = get_capital(client, logged_in).json()

    assert body["broker_margin"]["value"] is None
    assert body["broker_margin"]["status"] == STATUS_UNAVAILABLE
    assert body["broker_margin"]["source"] == SOURCE_BROKER_REPORTED
    assert body["broker_available_funds"]["value"] is None
    assert body["broker_available_funds"]["status"] == STATUS_UNAVAILABLE
    # Overall is partial: estimated available, broker unavailable.
    assert body["status"] == STATUS_PARTIAL


# =============================================================================
# §23-7 broker margin available via provider abstraction
# =============================================================================


async def test_broker_margin_available_via_provider(db_session):
    provider = StaticMarginProvider(broker_margin=37503.0, broker_available_funds=492000.0,
                                    timestamp="2026-08-16T10:00:00+00:00")
    summary = await get_capital_summary("some-user", db_session, provider=provider)

    assert summary["broker_margin"]["value"] == 37503.0
    assert summary["broker_margin"]["source"] == SOURCE_BROKER_REPORTED
    assert summary["broker_margin"]["status"] == STATUS_AVAILABLE
    assert summary["broker_margin"]["timestamp"] == "2026-08-16T10:00:00+00:00"
    assert summary["broker_available_funds"]["value"] == 492000.0
    # Paper cash stays a separate CALCULATED value — never relabeled as broker.
    assert summary["paper_available_cash"]["source"] == SOURCE_CALCULATED
    assert summary["paper_available_cash"]["value"] == 500000.0


async def test_provider_receives_whole_strategy_context(db_session):
    seen = {}

    class CapturingProvider(UnavailableMarginProvider):
        async def get_capital_snapshot(self, context):
            seen.update(context)
            return await super().get_capital_snapshot(context)

    await get_capital_summary("ctx-user", db_session, provider=CapturingProvider())
    assert seen["user_id"] == "ctx-user"
    assert seen["broker"] == "upstox"
    assert isinstance(seen["strategies"], list)
    assert "paper_starting_capital" in seen["account"]
    assert "paper_available_cash" in seen["account"]


# =============================================================================
# §23-8/§23-9 estimated capital on debit vs credit via the API
# =============================================================================


def test_estimated_capital_for_debit_and_credit_strategies(client, logged_in, db_session):
    assert execute(client, logged_in, long_call_payload()).status_code == 200
    body = get_capital(client, logged_in).json()
    assert body["estimated_capital"]["value"] == pytest.approx(125.25 * LOT, abs=0.01)
    assert body["estimated_capital"]["status"] == STATUS_AVAILABLE
    assert body["capital_used"]["value"] == pytest.approx(125.25 * LOT, abs=0.01)
    assert body["roc_inputs"]["available"] is True

    # Fully exit -> the strategy no longer engages capital.
    for pid in open_position_ids(db_session):
        resp = client.post(
            f"/paper/positions/{pid}/exit", headers=headers(logged_in),
            json={"client_order_id": next_id("exit")},
        )
        assert resp.status_code == 200, resp.text

    body = get_capital(client, logged_in).json()
    assert body["strategies"] == []
    assert body["premium_outlay"]["value"] == 0.0  # 0 is a VALID outlay now
    assert body["estimated_capital"]["value"] is None
    assert body["estimated_capital"]["status"] == STATUS_UNAVAILABLE
    assert body["capital_used"]["value"] is None
    assert body["roc_inputs"]["available"] is False


def test_credit_strategy_estimated_capital_unavailable(client, logged_in):
    assert execute(client, logged_in, short_put_payload()).status_code == 200
    body = get_capital(client, logged_in).json()

    row = body["strategies"][0]
    assert row["strategy_tag"] == "Short Put"
    assert row["entry_net"] == pytest.approx(-90.0 * LOT, abs=0.01)  # credit received
    assert row["estimated_capital"] is None  # premium received ≠ capital required
    assert row["estimated_capital_basis"] is None
    assert body["estimated_capital"]["value"] is None
    assert body["estimated_capital"]["status"] == STATUS_UNAVAILABLE
    assert body["capital_used"]["value"] is None
    assert body["roc_inputs"]["available"] is False


# =============================================================================
# §23-8 paper cash separate from broker funds
# =============================================================================


def test_paper_cash_reflects_ledger_and_is_labeled_paper(client, logged_in):
    assert execute(client, logged_in, bull_call_spread_payload()).status_code == 200
    body = get_capital(client, logged_in).json()

    # Paper starting capital stays the account value…
    assert body["paper_starting_capital"]["value"] == 500000.0
    assert body["paper_starting_capital"]["source"] == SOURCE_CALCULATED
    # …and paper available cash follows the cash ledger (debit paid + credit
    # received at entry): 500000 + (−8,141.25 + 2,314) = 494,172.75.
    assert body["paper_available_cash"]["value"] == pytest.approx(
        500000 - 125.25 * LOT + 35.60 * LOT, abs=0.01
    )
    assert body["paper_available_cash"]["source"] == SOURCE_CALCULATED
    # Broker funds stay unavailable — paper cash is never renamed broker funds.
    assert body["broker_available_funds"]["value"] is None
    assert body["remaining_capital"]["value"] == body["paper_available_cash"]["value"]


# =============================================================================
# §23-9 user isolation
# =============================================================================


def test_user_isolation(client, db_session):
    session_a = token_store.set_token("tok-cap-a")
    assert execute(client, session_a, bull_call_spread_payload()).status_code == 200

    session_b = token_store.set_token("tok-cap-b")
    body = get_capital(client, session_b).json()

    assert body["strategies"] == []  # user B never sees user A's strategies
    assert body["premium_outlay"]["value"] == 0.0
    assert body["estimated_capital"]["value"] is None
    assert body["paper_starting_capital"]["value"] == 500000.0
    assert body["paper_available_cash"]["value"] == 500000.0
    assert body["status"] == STATUS_UNAVAILABLE


# =============================================================================
# Endpoint contract + §23-13/14 (labels, no ROI aliasing)
# =============================================================================


def test_capital_requires_login(client):
    assert get_capital(client, "nope").status_code == 401


def test_capital_empty_portfolio_contract(client, logged_in):
    body = get_capital(client, logged_in).json()

    assert body["premium_outlay"]["value"] == 0.0
    assert body["premium_outlay"]["status"] == STATUS_AVAILABLE
    assert body["broker_margin"]["value"] is None
    assert body["estimated_capital"]["value"] is None
    assert body["broker_available_funds"]["value"] is None
    assert body["paper_starting_capital"]["value"] == 500000.0
    assert body["paper_available_cash"]["value"] == 500000.0
    assert body["capital_used"]["value"] is None
    assert body["roc_inputs"]["available"] is False
    assert body["generated_at"]
    assert body["status"] == STATUS_UNAVAILABLE

    # §23-14: no accidental ROI aliasing anywhere in the capital contract.
    raw = deepcopy(body)
    assert "roi" not in raw and "ROI" not in raw
    assert "return_on_capital" not in raw and "returnOnCapital" not in raw
    assert "broker_margin_available" not in raw  # paper cash is not broker margin
    for key, value in raw.items():
        if isinstance(value, dict) and "source" in value:
            assert value["source"] in {
                "BROKER_REPORTED", "ESTIMATED", "CALCULATED", "UNAVAILABLE",
            }
            assert value["status"] in {"available", "partial", "unavailable"}
