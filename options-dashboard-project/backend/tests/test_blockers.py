"""Blocker tests for identity hardening."""

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from app.brokers.domain.capabilities import BrokerCapabilities, BrokerCapability, CapabilityState
from app.brokers.adapters.upstox.adapter import upstox_capability_matrix
from app.identity import (
    get_analytics_token,
    remove_analytics_token,
    resolve_user_credentials,
    store_analytics_token,
)


from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import Base
from app.identity import User, BrokerConnection


@pytest.fixture(autouse=True)
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()
    engine.dispose()


@pytest.fixture()
def user_a(db_session):
    u = User(id="user-a", email="a@test.com", display_name="A")
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture()
def user_b(db_session):
    u = User(id="user-b", email="b@test.com", display_name="B")
    db_session.add(u)
    db_session.flush()
    return u



class TestCapabilityModelDataOnly:

    def _make_upstox_caps(self):
        items = [BrokerCapability(*m) for m in upstox_capability_matrix()]
        return BrokerCapabilities(items)

    def test_upstox_data_only_option_chain_available(self):
        caps = self._make_upstox_caps()
        result = caps.with_session_state(session_active=False, data_authorized=True)
        assert result.state("option_chain") == CapabilityState.AVAILABLE

    def test_upstox_data_only_quotes_if_wired(self):
        caps = self._make_upstox_caps()
        result = caps.with_session_state(session_active=False, data_authorized=True)
        assert result.state("quotes") in (CapabilityState.SUPPORTED, CapabilityState.AVAILABLE)

    def test_upstox_data_only_orders_unavailable(self):
        caps = self._make_upstox_caps()
        result = caps.with_session_state(session_active=False, data_authorized=True)
        assert result.state("orders") == CapabilityState.AUTH_REQUIRED

    def test_upstox_data_only_trading_unavailable(self):
        caps = self._make_upstox_caps()
        result = caps.with_session_state(session_active=False, data_authorized=True)
        assert result.state("market_orders") == CapabilityState.AUTH_REQUIRED
        assert result.state("modify_order") == CapabilityState.AUTH_REQUIRED

    def test_upstox_oauth_only_market_data(self):
        caps = self._make_upstox_caps()
        result = caps.with_session_state(session_active=True, data_authorized=False)
        assert result.state("option_chain") == CapabilityState.AVAILABLE

    def test_upstox_oauth_plus_analytics_data_available(self):
        caps = self._make_upstox_caps()
        result = caps.with_session_state(session_active=True, data_authorized=True)
        assert result.state("option_chain") == CapabilityState.AVAILABLE

    def test_inactive_data_status_market_data_unavailable(self):
        caps = self._make_upstox_caps()
        result = caps.with_session_state(session_active=False, data_authorized=False)
        assert result.state("option_chain") == CapabilityState.AUTH_REQUIRED

    def test_data_only_does_not_enable_trading(self):
        caps = self._make_upstox_caps()
        result = caps.with_session_state(session_active=False, data_authorized=True)
        for name in ["orders", "market_orders", "limit_orders", "modify_order",
                      "cancel_order", "positions", "trades"]:
            assert result.state(name) != CapabilityState.AVAILABLE, f"{name} leaked"

    def test_no_session_no_data_auth_required(self):
        caps = self._make_upstox_caps()
        result = caps.with_session_state(session_active=False, data_authorized=False)
        assert result.state("option_chain") == CapabilityState.AUTH_REQUIRED
        assert result.state("option_contracts") == CapabilityState.AUTH_REQUIRED


class TestGlobalGexTokenResolution:

    def test_get_analytics_token_requires_user_scope(self):
        sig = inspect.signature(get_analytics_token)
        assert "user_id" in sig.parameters

    def test_resolve_user_credentials_requires_user_scope(self):
        sig = inspect.signature(resolve_user_credentials)
        assert "user_id" in sig.parameters

    def test_analytics_token_removed_no_resolution(self, db_session, user_a):
        store_analytics_token(db_session, user_a.id, "UPSTOX", "tok")
        remove_analytics_token(db_session, user_a.id, "UPSTOX")
        assert get_analytics_token(db_session, user_a.id, "UPSTOX") is None
