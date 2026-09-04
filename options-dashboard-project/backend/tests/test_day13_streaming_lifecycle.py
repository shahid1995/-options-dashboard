"""Day 13 — Source-neutral Streaming Lifecycle, Recovery & Stale-Data tests.

RED-phase contract for ``app/market_data/streaming.py``:

    Broker streaming source (SDK/transport)
        → StreamingSource protocol (source-neutral)
        → StreamingLifecycleManager
            connection / disconnect / reconnect / bounded exponential backoff /
            resubscription / liveness / stale detection / sequence tracking /
            gap detection / recovery / intentional shutdown / auth failure
        → canonical Day-9 observations (provenance preserved, BROKER_LIVE)
        → Day-12 quality layer (via StreamQualityContext metadata)

Rules locked by these tests
---------------------------
1. Deterministic: injectable clock + RNG + sleeper; no wall clock, no network.
2. No fabrication: never invent sequence numbers, timestamps, or market values;
   stale state never emits observations; missing LTP → no quote.
3. Unresolved sequence gaps are never reported as healthy continuous data.
4. Intentional shutdown never reconnects; auth failure never endlessly retries.
5. Reconnect uses bounded exponential backoff; jitter never exceeds the bound.
6. After reconnect, the EXACT subscription set is restored (resubscription).
7. Non-canonical observations are refused at the boundary (never crash the
   stream); one consumer callback failure cannot kill the feed.
8. No credentials/tokens ever appear in lifecycle events, status, or repr.
9. The Day-12 Data Quality Engine remains the authoritative quality layer.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Callable

import pytest

from app.brokers.domain.errors import BrokerError, BrokerErrorCode
from app.market_data.contracts import (
    ContractVersion,
    DataMode,
    MarketObservation,
    NormalizedInstrument,
    OptionChainObservation,
    OptionChainRow,
    PriceQuote,
    Provenance,
    QuoteObservation,
    Side,
)
from app.market_data.streaming import (
    BackoffPolicy,
    LifecycleEvent,
    LifecycleEventType,
    SequenceEvent,
    SequenceState,
    SequenceTracker,
    StreamLifecycleState,
    StreamQualityContext,
    StreamingLifecycleManager,
    StreamingSource,
)

# ---------------------------------------------------------------------------
# Factories / helpers
# ---------------------------------------------------------------------------

# Sentinel: distinguishes "not supplied" from an explicit None (a missing
# provenance / timestamp is a real test case).
_UNSET = object()


def _inst(
    symbol: str = "NIFTY 26SEP2424200CE",
    underlying: str = "NIFTY",
    strike: float | None = 24200,
    side: Side | None = Side.CALL,
    instrument_type: str = "OPTION",
) -> NormalizedInstrument:
    return NormalizedInstrument(
        exchange="NSE",
        segment="FO",
        underlying=underlying,
        symbol=symbol,
        instrument_type=instrument_type,
        expiry="2026-09-24",
        strike=strike,
        option_type=side,
    )


def _prov(source: str = "UPSTOX", mode: DataMode = DataMode.BROKER_LIVE) -> Provenance:
    return Provenance(
        source=source,
        collection_mode=mode.value,
        received_at=datetime(2026, 9, 3, 10, 0, 1, tzinfo=timezone.utc),
        normalization_version="1.0.0",
        contract_version="1.0.0",
        transformation_id=None,
    )


def _quote(
    ltp: float = 250.5,
    *,
    market: datetime | None = _UNSET,
    received: datetime | None = _UNSET,
    prov: Provenance | None = _UNSET,
    mode: DataMode = DataMode.BROKER_LIVE,
    source: str = "UPSTOX",
    instrument: NormalizedInstrument | None = None,
    oi: float | None = 10000,
    volume: float | None = 5000,
) -> QuoteObservation:
    if prov is _UNSET:
        prov = _prov(source=source, mode=mode)
    if market is _UNSET:
        market = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
    if received is _UNSET:
        received = datetime(2026, 9, 3, 10, 0, 1, tzinfo=timezone.utc)
    return QuoteObservation(
        instrument=instrument or _inst(),
        quote=PriceQuote(
            ltp=ltp,
            oi=oi,
            volume=volume,
            bid=250.2,
            ask=250.8,
            bid_quantity=75,
            ask_quantity=150,
            source="BROKER",
        ),
        market_timestamp=market,
        received_timestamp=received,
        source=source,
        data_mode=mode,
        provenance=prov,
        contract_version=ContractVersion.v1_0_0,
    )


def _market_obs(
    sequence_id: int | None = None,
    *,
    prov: Provenance | None = None,
    mode: DataMode = DataMode.BROKER_LIVE,
    source: str = "FAKE",
) -> MarketObservation:
    return MarketObservation(
        instrument=_inst(),
        market_timestamp=datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc),
        received_timestamp=datetime(2026, 9, 3, 10, 0, 1, tzinfo=timezone.utc),
        source=source,
        data_mode=mode,
        sequence_id=sequence_id,
        provenance=prov if prov is not None else _prov(source=source, mode=mode),
        contract_version=ContractVersion.v1_0_0,
    )


def _chain_obs(*, mode: DataMode = DataMode.BROKER_LIVE, source: str = "UPSTOX") -> OptionChainObservation:
    return OptionChainObservation(
        symbol="NIFTY",
        expiry_date="2026-09-24",
        underlying_spot_price=24230.5,
        chain=[
            OptionChainRow(strike=24200, call=PriceQuote(ltp=250.5, oi=10000), put=PriceQuote(ltp=180.2, oi=8000)),
        ],
        market_timestamp=datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc),
        received_timestamp=datetime(2026, 9, 3, 10, 0, 1, tzinfo=timezone.utc),
        source=source,
        data_mode=mode,
        contract_version=ContractVersion.v1_0_0,
    )


class Clock:
    """Injectable monotonic clock for deterministic lifecycle tests."""

    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class RecordingSleeper:
    """Injected asyncio.sleep replacement that records calls and returns."""

    def __init__(self):
        self.calls: list[tuple[float, int]] = []

    async def __call__(self, delay: float, *args, **kwargs):
        self.calls.append((delay, len(self.calls)))


async def _pump(rounds: int = 25) -> None:
    """Yield to the event loop so scheduled reconnect tasks make progress."""
    for _ in range(rounds):
        await asyncio.sleep(0)


class FakeStreamingSource:
    """Deterministic, scripted StreamingSource — no network, no SDK."""

    def __init__(self, source_id: str = "FAKE", *, supports_sequence: bool = False):
        self.source_id = source_id
        self.supports_sequence = supports_sequence
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.resubscribe_calls = 0
        self.subscribe_sets: list[list[str]] = []
        self._instruments: list[str] | None = None
        self._connected = False
        self._connect_errors: list[BaseException] = []
        self._subscribe_errors: list[BaseException] = []
        self._resubscribe_errors: list[BaseException] = []
        self._poll_actions: list[str | Callable[[], None]] = []
        self._is_connected_override: bool | None = None
        self._observation_handlers: list[Callable] = []
        self._error_handlers: list[Callable] = []
        self._disconnect_handlers: list[Callable] = []

    # ---- StreamingSource protocol ----------------------------------------
    def register_observation_handler(self, handler: Callable) -> None:
        self._observation_handlers.append(handler)

    def register_error_handler(self, handler: Callable) -> None:
        self._error_handlers.append(handler)

    def register_disconnect_handler(self, handler: Callable) -> None:
        self._disconnect_handlers.append(handler)

    async def connect(self) -> None:
        self.connect_calls += 1
        if self._connect_errors:
            raise self._connect_errors.pop(0)
        self._connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    async def subscribe(self, instruments) -> None:
        self._instruments = list(instruments)
        self.subscribe_sets.append(list(instruments))
        if self._subscribe_errors:
            raise self._subscribe_errors.pop(0)

    async def resubscribe(self) -> None:
        self.resubscribe_calls += 1
        if self._resubscribe_errors:
            raise self._resubscribe_errors.pop(0)
        await self.connect()
        await self.subscribe(self._instruments or [])

    def is_connected(self) -> bool:
        if self._is_connected_override is not None:
            return self._is_connected_override
        return self._connected

    def poll(self) -> None:
        while self._poll_actions:
            action = self._poll_actions.pop(0)
            if action == "auth_failed":
                self._emit_error(BrokerError(BrokerErrorCode.AUTH_REQUIRED, "401 Unauthorized: invalid token"))
            elif action == "disconnect":
                self._emit_disconnect()
            elif callable(action):
                action()

    # ---- test helpers -----------------------------------------------------
    def emit(self, obs) -> None:
        for h in self._observation_handlers:
            h(obs)

    def emit_disconnect(self) -> None:
        self._connected = False
        for h in self._disconnect_handlers:
            h()

    def emit_error(self, exc: BaseException) -> None:
        for h in self._error_handlers:
            h(exc)

    def queue_error(self, exc: BaseException) -> None:
        self._connect_errors.append(exc)

    def queue_subscribe_error(self, exc: BaseException) -> None:
        self._subscribe_errors.append(exc)

    def queue_resubscribe_error(self, exc: BaseException) -> None:
        self._resubscribe_errors.append(exc)

    def queue_poll(self, action: str | Callable[[], None]) -> None:
        self._poll_actions.append(action)


@pytest.fixture
def source():
    return FakeStreamingSource()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def sleeper():
    return RecordingSleeper()


def _manager(
    src: StreamingSource,
    *,
    clock: Clock | None = None,
    sleeper: RecordingSleeper | None = None,
    **config_kwargs,
) -> StreamingLifecycleManager:
    return StreamingLifecycleManager(
        src,
        clock=clock or Clock(),
        sleep=sleeper or RecordingSleeper(),
        rng=random.Random(7),
        **config_kwargs,
    )


async def _started(manager: StreamingLifecycleManager, instruments=None):
    await manager.start(instruments or ["NSE_FO|45450", "NSE_FO|45451"])
    return manager


# ---------------------------------------------------------------------------
# 1. Lifecycle state machine
# ---------------------------------------------------------------------------


class TestLifecycleStateMachine:
    async def test_initial_state_disconnected(self, source, clock):
        m = _manager(source, clock=clock)
        assert m.state is StreamLifecycleState.DISCONNECTED
        assert m.status().live is False

    async def test_start_transitions_through_states(self, source, clock):
        m = _manager(source, clock=clock)
        events = []
        m.register_lifecycle_handler(events.append)
        await m.start(["A", "B"])
        assert source.connect_calls == 1
        assert source.subscribe_sets == [["A", "B"]]
        assert m.state is StreamLifecycleState.LIVE
        assert m.status().live is True
        kinds = [e.type for e in events]
        assert LifecycleEventType.CONNECTING in kinds
        assert LifecycleEventType.CONNECTED in kinds
        assert LifecycleEventType.SUBSCRIBING in kinds
        assert LifecycleEventType.LIVE in kinds

    async def test_start_raises_when_already_started(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        with pytest.raises(ValueError):
            await m.start(["C"])

    async def test_stop_transitions_to_stopped(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        events = []
        m.register_lifecycle_handler(events.append)
        await m.stop()
        assert m.state is StreamLifecycleState.STOPPED
        assert source.disconnect_calls == 1
        assert any(e.type is LifecycleEventType.STOPPED for e in events)

    async def test_intentional_shutdown_never_reconnects(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        await m.stop()
        connect_before = source.connect_calls
        source.emit_disconnect()  # transport flaps after shutdown — must be ignored
        await _pump()
        assert m.state is StreamLifecycleState.STOPPED
        assert source.connect_calls == connect_before
        assert source.resubscribe_calls == 0

    async def test_auth_failure_transitions_and_does_not_reconnect(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        source.emit_error(BrokerError(BrokerErrorCode.AUTH_REQUIRED, "401 Unauthorized"))
        await _pump()
        assert m.state is StreamLifecycleState.AUTH_FAILED
        assert m.status().live is False
        assert source.connect_calls == 1  # no reconnect attempt
        assert any(e.type is LifecycleEventType.AUTH_FAILED for e in m.events)

    async def test_auth_failure_during_connect(self, source, clock):
        source.queue_error(BrokerError(BrokerErrorCode.AUTH_REQUIRED, "invalid token"))
        m = _manager(source, clock=clock)
        await m.start(["A"])
        assert m.state is StreamLifecycleState.AUTH_FAILED

    async def test_source_failure_after_live_goes_error_when_code_unknown(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        source.emit_error(BrokerError(BrokerErrorCode.INVALID_INSTRUMENT, "bad instrument"))
        await _pump()
        assert m.state is StreamLifecycleState.ERROR
        assert m.status().last_error_code == BrokerErrorCode.INVALID_INSTRUMENT.value


# ---------------------------------------------------------------------------
# 2. Reconnection & bounded backoff
# ---------------------------------------------------------------------------


class TestReconnection:
    async def test_transient_disconnect_triggers_reconnect(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        source.emit_disconnect()
        await _pump()
        assert m.state is StreamLifecycleState.LIVE
        # manager reconnect connect() + resubscribe()'s own connect()
        assert source.connect_calls >= 2
        assert source.resubscribe_calls == 1
        kinds = [e.type for e in m.events]
        assert LifecycleEventType.RECONNECTING in kinds
        assert LifecycleEventType.RECONNECTED in kinds

    async def test_reconnect_resets_retry_state(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        for _ in range(3):
            source.emit_disconnect()
            await _pump()
        assert m.state is StreamLifecycleState.LIVE
        assert m.status().reconnect_attempts == 0

    async def test_network_error_triggers_reconnect(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        source.emit_error(BrokerError(BrokerErrorCode.NETWORK_ERROR, "connection lost"))
        await _pump()
        assert m.state is StreamLifecycleState.LIVE
        assert source.resubscribe_calls == 1

    async def test_rate_limited_retries_with_backoff(self, source, clock, sleeper):
        m = _manager(source, clock=clock, sleeper=sleeper)
        await m.start(["A"])
        source.emit_error(BrokerError(BrokerErrorCode.RATE_LIMITED, "429 too many requests"))
        await _pump()
        assert m.state is StreamLifecycleState.LIVE
        assert len(sleeper.calls) >= 1

    async def test_max_attempts_exhausted_goes_error(self, source, clock):
        m = _manager(source, clock=clock, max_attempts=3, base_seconds=0.001, max_seconds=0.01)
        await m.start(["A"])
        for _ in range(4):
            source.queue_error(BrokerError(BrokerErrorCode.NETWORK_ERROR, "down"))
        source.emit_disconnect()
        await _pump()
        assert m.state is StreamLifecycleState.ERROR
        assert any(e.type is LifecycleEventType.ERROR for e in m.events)

    async def test_reconnect_uses_exponential_backoff_delays(self, source, clock, sleeper):
        m = _manager(source, clock=clock, sleeper=sleeper, base_seconds=1.0, max_seconds=100.0)
        await m.start(["A"])
        for _ in range(3):
            source.queue_resubscribe_error(BrokerError(BrokerErrorCode.UPSTREAM_ERROR, "boom"))
        source.emit_disconnect()
        await _pump()
        delays = [d for d, _ in sleeper.calls]
        assert len(delays) >= 3
        # exponential: attempt 0 → ~1s, attempt 1 → ~2s, attempt 2 → ~4s (plus jitter)
        assert delays[1] > delays[0]
        assert delays[2] > delays[1]
        assert all(d <= 100.0 for d in delays)

    async def test_connect_failure_during_reconnect_keeps_retrying_then_error(self, source, clock):
        m = _manager(source, clock=clock, max_attempts=2, base_seconds=0.001, max_seconds=0.01)
        await m.start(["A"])
        source.queue_error(BrokerError(BrokerErrorCode.NETWORK_ERROR, "down"))
        source.queue_error(BrokerError(BrokerErrorCode.NETWORK_ERROR, "still down"))
        source.emit_disconnect()
        await _pump()
        assert m.state is StreamLifecycleState.ERROR


class TestBackoffPolicy:
    def test_delays_are_bounded_by_max(self):
        policy = BackoffPolicy(base_seconds=1.0, max_seconds=5.0, max_attempts=10, jitter_fraction=0.25)
        rng = random.Random(1)
        for attempt in range(15):
            for _ in range(50):
                delay = policy.delay(attempt, rng)
                assert delay <= 5.0 * 1.25  # max + jitter bound
                assert delay >= 1.0

    def test_jitter_never_exceeds_configured_fraction(self):
        policy = BackoffPolicy(base_seconds=2.0, max_seconds=100.0, max_attempts=10, jitter_fraction=0.25)
        rng = random.Random(2)
        for attempt in range(10):
            base = min(2.0 * (2 ** attempt), 100.0)
            for _ in range(200):
                delay = policy.delay(attempt, rng)
                assert delay >= base
                assert delay <= base * 1.25

    def test_deterministic_with_same_seed(self):
        policy = BackoffPolicy()
        rng_a, rng_b = random.Random(42), random.Random(42)
        assert [policy.delay(i, rng_a) for i in range(5)] == [policy.delay(i, rng_b) for i in range(5)]

    def test_validation_rejects_bad_config(self):
        with pytest.raises(ValueError):
            BackoffPolicy(base_seconds=0)
        with pytest.raises(ValueError):
            BackoffPolicy(max_attempts=0)
        with pytest.raises(ValueError):
            BackoffPolicy(jitter_fraction=-0.1)


# ---------------------------------------------------------------------------
# 3. Resubscription
# ---------------------------------------------------------------------------


class TestResubscription:
    async def test_exact_subscription_set_restored_after_reconnect(self, source, clock):
        instruments = ["NSE_FO|45450", "NSE_FO|45451", "NSE_FO|45452"]
        m = await _started(_manager(source, clock=clock), instruments)
        source.emit_disconnect()
        await _pump()
        assert source.resubscribe_calls == 1
        assert source.subscribe_sets[0] == instruments
        assert source.subscribe_sets[-1] == instruments

    async def test_subscription_set_preserved_across_multiple_reconnects(self, source, clock):
        instruments = ["A", "B", "C"]
        m = await _started(_manager(source, clock=clock), instruments)
        for _ in range(3):
            source.emit_disconnect()
            await _pump()
        assert source.resubscribe_calls == 3
        for subset in source.subscribe_sets:
            assert subset == instruments


# ---------------------------------------------------------------------------
# 4. Liveness / stale data
# ---------------------------------------------------------------------------


class TestStaleDetection:
    async def test_heartbeat_marks_stale_when_no_activity(self, source, clock):
        m = _manager(source, clock=clock, stale_after_seconds=10)
        await m.start(["A"])
        clock.advance(60)
        m.heartbeat()
        assert m.state is StreamLifecycleState.STALE
        assert m.status().stale is True
        assert any(e.type is LifecycleEventType.STALE for e in m.events)

    async def test_fresh_data_clears_stale(self, source, clock):
        m = _manager(source, clock=clock, stale_after_seconds=10)
        await m.start(["A"])
        clock.advance(60)
        m.heartbeat()
        assert m.state is StreamLifecycleState.STALE
        source.emit(_quote())
        assert m.state is StreamLifecycleState.LIVE
        assert m.status().stale is False
        assert any(e.type is LifecycleEventType.FRESH for e in m.events)

    async def test_not_stale_within_threshold(self, source, clock):
        m = _manager(source, clock=clock, stale_after_seconds=10)
        await m.start(["A"])
        clock.advance(5)
        m.heartbeat()
        assert m.state is StreamLifecycleState.LIVE
        assert m.status().stale is False

    async def test_stale_state_never_fabricates_observations(self, source, clock):
        m = _manager(source, clock=clock, stale_after_seconds=10)
        received = []
        m.register_observation_handler(received.append)
        await m.start(["A"])
        clock.advance(60)
        m.heartbeat()
        assert m.status().stale is True
        # no observations were produced or synthesized by the manager
        assert received == []
        assert m.status().last_activity_age_seconds is not None

    async def test_status_exposes_activity_age(self, source, clock):
        m = _manager(source, clock=clock)
        await m.start(["A"])
        clock.advance(3)
        m.heartbeat()
        status = m.status()
        assert status.last_activity_age_seconds == pytest.approx(3.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 5. Sequence handling
# ---------------------------------------------------------------------------


class TestSequenceHandling:
    async def test_monotonic_sequence_accepted(self, source, clock):
        source = FakeStreamingSource(supports_sequence=True)
        m = _manager(source, clock=clock)
        await m.start(["A"])
        for seq in (1, 2, 3, 4):
            source.emit(_market_obs(sequence_id=seq))
        assert m.status().sequence_state is SequenceState.HEALTHY
        assert m.status().gap is False

    async def test_duplicate_sequence_handled_safely(self, source, clock):
        source = FakeStreamingSource(supports_sequence=True)
        m = _manager(source, clock=clock)
        await m.start(["A"])
        source.emit(_market_obs(sequence_id=7))
        source.emit(_market_obs(sequence_id=7))
        assert m.state is StreamLifecycleState.LIVE
        assert m.status().sequence_state is SequenceState.HEALTHY
        assert any(e.type is LifecycleEventType.DUPLICATE for e in m.events)

    async def test_out_of_order_sequence_flagged(self, source, clock):
        source = FakeStreamingSource(supports_sequence=True)
        m = _manager(source, clock=clock)
        await m.start(["A"])
        source.emit(_market_obs(sequence_id=10))
        source.emit(_market_obs(sequence_id=8))  # older than last
        assert any(e.type is LifecycleEventType.OUT_OF_ORDER for e in m.events)
        assert m.status().gap is False  # out-of-order is NOT a gap

    async def test_sequence_gap_detected_and_recovery_state(self, source, clock):
        source = FakeStreamingSource(supports_sequence=True)
        m = _manager(source, clock=clock)
        await m.start(["A"])
        source.emit(_market_obs(sequence_id=100))
        source.emit(_market_obs(sequence_id=105))  # 101-104 missing
        assert m.status().sequence_state is SequenceState.GAP_DETECTED
        assert m.status().gap is True
        assert any(e.type is LifecycleEventType.GAP_DETECTED for e in m.events)

    async def test_unresolved_gap_never_reported_healthy(self, source, clock):
        source = FakeStreamingSource(supports_sequence=True)
        m = _manager(source, clock=clock)
        await m.start(["A"])
        source.emit(_market_obs(sequence_id=100))
        source.emit(_market_obs(sequence_id=120))
        assert m.status().gap is True
        m.heartbeat()
        assert m.status().gap is True  # still flagged — not silently healthy
        assert m.status().live is False or m.status().sequence_state is SequenceState.GAP_DETECTED

    async def test_recovered_sequence_restores_healthy_state(self, source, clock):
        source = FakeStreamingSource(supports_sequence=True)
        m = _manager(source, clock=clock)
        await m.start(["A"])
        source.emit(_market_obs(sequence_id=100))
        source.emit(_market_obs(sequence_id=105))  # GAP
        assert m.status().gap is True
        source.emit(_market_obs(sequence_id=106))  # contiguous after gap
        assert m.status().sequence_state is SequenceState.HEALTHY
        assert m.status().gap is False
        assert any(e.type is LifecycleEventType.RECOVERED for e in m.events)

    async def test_sequence_unsupported_is_not_invented(self, source, clock):
        # FakeStreamingSource defaults supports_sequence=False
        m = _manager(source, clock=clock)
        await m.start(["A"])
        source.emit(_market_obs(sequence_id=1))
        assert m.status().sequence_state is SequenceState.UNSUPPORTED
        assert m.status().gap is False  # never a fabricated gap
        assert any(e.type is LifecycleEventType.UNSUPPORTED_SEQUENCE for e in m.events)

    async def test_none_sequence_never_invented(self, source, clock):
        source = FakeStreamingSource(supports_sequence=True)
        m = _manager(source, clock=clock)
        await m.start(["A"])
        source.emit(_market_obs(sequence_id=None))
        # a None sequence is never treated as a gap and never invented
        assert m.status().gap is False
        assert any(e.type is LifecycleEventType.UNSUPPORTED_SEQUENCE for e in m.events)


class TestSequenceTrackerUnit:
    def test_unsupported(self):
        t = SequenceTracker(supported=False)
        assert t.state is SequenceState.UNSUPPORTED
        assert t.observe(1) is SequenceEvent.UNSUPPORTED
        assert t.observe(None) is SequenceEvent.UNSUPPORTED

    def test_first_sequence_ok(self):
        t = SequenceTracker(supported=True)
        assert t.observe(1) is SequenceEvent.OK
        assert t.state is SequenceState.HEALTHY

    def test_duplicate(self):
        t = SequenceTracker(supported=True)
        t.observe(5)
        assert t.observe(5) is SequenceEvent.DUPLICATE

    def test_out_of_order(self):
        t = SequenceTracker(supported=True)
        t.observe(5)
        assert t.observe(3) is SequenceEvent.OUT_OF_ORDER
        assert t.state is SequenceState.HEALTHY

    def test_gap(self):
        t = SequenceTracker(supported=True)
        t.observe(10)
        assert t.observe(15) is SequenceEvent.GAP
        assert t.state is SequenceState.GAP_DETECTED

    def test_recovery_via_contiguity(self):
        t = SequenceTracker(supported=True)
        t.observe(10)
        t.observe(15)
        assert t.observe(16) is SequenceEvent.RECOVERED
        assert t.state is SequenceState.HEALTHY

    def test_mark_recovered(self):
        t = SequenceTracker(supported=True)
        t.observe(10)
        t.observe(15)
        assert t.mark_recovered() is SequenceEvent.RECOVERED
        assert t.state is SequenceState.HEALTHY

    def test_non_int_sequence_unsupported(self):
        t = SequenceTracker(supported=True)
        assert t.observe("abc") is SequenceEvent.UNSUPPORTED


# ---------------------------------------------------------------------------
# 6. Event integrity / robustness
# ---------------------------------------------------------------------------


class TestEventIntegrity:
    async def test_malformed_observation_does_not_crash(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        source.emit({"last_price": 250.5, "instrument_token": "45450"})  # raw payload
        assert m.state is StreamLifecycleState.LIVE  # still alive
        assert any(e.type is LifecycleEventType.OBSERVATION_REFUSED for e in m.events)

    async def test_unknown_event_type_not_crashing_via_protocol(self, source, clock):
        # the manager's boundary only accepts canonical observations
        m = await _started(_manager(source, clock=clock))
        source.emit("some-unknown-event")
        assert m.state is StreamLifecycleState.LIVE

    async def test_callback_failure_does_not_kill_feed(self, source, clock):
        m = await _started(_manager(source, clock=clock))

        def bad(obs):
            raise RuntimeError("consumer crashed")

        m.register_observation_handler(bad)
        source.emit(_quote())
        assert m.state is StreamLifecycleState.LIVE
        assert any(e.type is LifecycleEventType.CALLBACK_FAILURE for e in m.events)

    async def test_source_error_with_token_does_not_leak(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        secret = "upstox_secret_abc123"
        source.emit_error(BrokerError(BrokerErrorCode.NETWORK_ERROR, f"connection failed token={secret}"))
        await _pump()
        serialized = " ".join(
            [str(m.status()), str([(e.type.value, e.message) for e in m.events])]
        )
        assert secret not in serialized


# ---------------------------------------------------------------------------
# 7. Canonical boundary
# ---------------------------------------------------------------------------


class TestCanonicalBoundary:
    async def test_canonical_quote_passes_through_with_provenance(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        received = []
        m.register_observation_handler(received.append)
        obs = _quote()
        source.emit(obs)
        assert received == [obs]  # provenance + BROKER_LIVE preserved untouched

    async def test_observation_without_provenance_refused(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        source.emit(_quote(prov=None))
        assert any(e.type is LifecycleEventType.OBSERVATION_REFUSED for e in m.events)

    async def test_snapshot_mode_observation_refused_on_live_stream(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        source.emit(_quote(mode=DataMode.BROKER_SNAPSHOT))
        assert any(e.type is LifecycleEventType.OBSERVATION_REFUSED for e in m.events)
        assert m.status().live is True  # stream itself not poisoned

    async def test_chain_observation_accepted_when_live(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        received = []
        m.register_observation_handler(received.append)
        obs = _chain_obs()
        source.emit(obs)
        assert received == [obs]

    async def test_chain_observation_without_mode_refused(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        source.emit(_chain_obs(mode=None))
        assert any(e.type is LifecycleEventType.OBSERVATION_REFUSED for e in m.events)

    async def test_observation_without_received_timestamp_refused(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        source.emit(_quote(received=None))
        assert any(e.type is LifecycleEventType.OBSERVATION_REFUSED for e in m.events)


# ---------------------------------------------------------------------------
# 8. Security / isolation
# ---------------------------------------------------------------------------


class TestSecurityIsolation:
    async def test_manager_holds_no_credentials(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        assert "token" not in str(m.status()).lower()
        assert "secret" not in str(m.status()).lower()
        assert "access_token" not in str([e.type.value for e in m.events])

    async def test_tenant_sources_never_share_state(self, clock):
        src_a = FakeStreamingSource("A")
        src_b = FakeStreamingSource("B")
        m_a = _manager(src_a, clock=clock)
        m_b = _manager(src_b, clock=clock)
        await m_a.start(["X"])
        await m_b.start(["Y"])
        seen_a, seen_b = [], []
        m_a.register_observation_handler(seen_a.append)
        m_b.register_observation_handler(seen_b.append)
        src_a.emit(_quote(source="A"))
        src_b.emit(_quote(source="B"))
        assert [o.source for o in seen_a] == ["A"]
        assert [o.source for o in seen_b] == ["B"]
        # independent lifecycle state
        src_a.emit_disconnect()
        await _pump()
        assert m_a.state is StreamLifecycleState.LIVE  # reconnected
        assert m_b.state is StreamLifecycleState.LIVE  # untouched by A's flap

    async def test_repr_excludes_credentials(self, source, clock):
        m = await _started(_manager(source, clock=clock))
        assert "token" not in repr(m).lower()
        assert "secret" not in repr(m).lower()


# ---------------------------------------------------------------------------
# 9. Day 12 quality integration
# ---------------------------------------------------------------------------


class TestDay12Integration:
    async def test_quality_context_exposes_lifecycle_metadata(self, source, clock):
        m = await _started(_manager(source, clock=clock, stale_after_seconds=10))
        ctx = m.quality_context()
        assert isinstance(ctx, StreamQualityContext)
        assert ctx.live is True
        assert ctx.stale is False
        assert ctx.gap is False
        assert ctx.sequence_state is SequenceState.UNSUPPORTED
        assert ctx.reconnect_attempts == 0

    async def test_quality_context_reflects_stale_and_gap(self, source, clock):
        source = FakeStreamingSource(supports_sequence=True)
        m = _manager(source, clock=clock, stale_after_seconds=10)
        await m.start(["A"])
        source.emit(_market_obs(sequence_id=1))
        source.emit(_market_obs(sequence_id=5))  # gap
        clock.advance(60)
        m.heartbeat()
        ctx = m.quality_context()
        assert ctx.gap is True
        assert ctx.stale is True

    async def test_day12_engine_remains_authoritative(self, source, clock):
        from app.market_data.quality import MarketDataQualityEngine

        m = await _started(_manager(source, clock=clock))
        source.emit(_quote())
        engine = MarketDataQualityEngine()
        obs = _quote(received=datetime(2026, 9, 3, 10, 0, 1, tzinfo=timezone.utc))
        result = engine.evaluate(
            obs,
            reference_time=datetime(2026, 9, 3, 10, 0, 30, tzinfo=timezone.utc),
        )
        assert result.quality_score >= 90  # fresh, complete, valid observation
        # lifecycle metadata is separate from quality scoring
        assert m.quality_context().live is True


# ---------------------------------------------------------------------------
# 10. Upstox streaming source bridge
# ---------------------------------------------------------------------------


class TestUpstoxStreamingSourceBridge:
    def _bridge(self, feed, **kwargs):
        from app.brokers.adapters.upstox.streaming_source import UpstoxStreamingSource

        return UpstoxStreamingSource(
            feed,
            symbol="NIFTY",
            expiry_date="2026-09-24",
            contract_specs={"NSE_FO|45450": {"strike": 24200, "option_type": "CE"}},
            **kwargs,
        )

    def test_source_id_and_sequence_capability(self):
        from unittest.mock import MagicMock

        from app.brokers.adapters.upstox.streaming_source import UpstoxStreamingSource

        bridge = self._bridge(MagicMock())
        assert bridge.source_id == "UPSTOX"
        assert bridge.supports_sequence is False  # Upstox V3 has no per-message sequence

    def test_tick_maps_to_canonical_quote_observation(self):
        from unittest.mock import MagicMock

        from app.services.upstox_market_feed import InstrumentTick

        feed = MagicMock()
        tick = InstrumentTick("NSE_FO|45450")
        tick.ltp = 250.5
        tick.oi = 10000
        tick.volume = 5678
        tick.bid_p = 250.2
        tick.ask_p = 250.8
        tick.bid_q = "75"
        tick.ask_q = "150"
        tick.ltt = "1740729552723"
        feed.get_tick.return_value = tick

        bridge = self._bridge(feed, now_utc=lambda: datetime(2026, 9, 3, 10, 5, 0, tzinfo=timezone.utc))
        obs = bridge._tick_to_observation("NSE_FO|45450", tick)
        assert isinstance(obs, QuoteObservation)
        assert obs.quote.ltp == 250.5
        assert obs.quote.oi == 10000
        assert obs.quote.volume == 5678
        assert obs.quote.bid == 250.2
        assert obs.quote.ask == 250.8
        assert obs.quote.bid_quantity == 75
        assert obs.quote.ask_quantity == 150
        assert obs.source == "UPSTOX"
        assert obs.data_mode is DataMode.BROKER_LIVE
        assert obs.provenance is not None
        assert obs.provenance.source == "UPSTOX"
        assert obs.instrument.underlying == "NIFTY"
        assert obs.instrument.option_type is Side.CALL
        assert obs.instrument.strike == 24200
        assert obs.instrument.expiry == "2026-09-24"

    def test_missing_ltp_never_fabricates_quote(self):
        from unittest.mock import MagicMock

        from app.services.upstox_market_feed import InstrumentTick

        feed = MagicMock()
        tick = InstrumentTick("NSE_FO|45450")  # ltp stays None
        bridge = self._bridge(feed)
        assert bridge._tick_to_observation("NSE_FO|45450", tick) is None

    def test_market_and_received_timestamps_distinct(self):
        from unittest.mock import MagicMock

        from app.services.upstox_market_feed import InstrumentTick

        feed = MagicMock()
        tick = InstrumentTick("NSE_FO|45450")
        tick.ltp = 250.5
        tick.ltt = "1740729552723"  # epoch-ms
        received = datetime(2026, 9, 3, 10, 5, 0, tzinfo=timezone.utc)
        bridge = self._bridge(feed, now_utc=lambda: received)
        obs = bridge._tick_to_observation("NSE_FO|45450", tick)
        assert obs.market_timestamp is not None
        assert obs.market_timestamp == datetime.fromtimestamp(1740729552.723, tz=timezone.utc)
        assert obs.received_timestamp == received
        assert obs.market_timestamp != obs.received_timestamp

    def test_feed_tick_event_emits_observations_to_handlers(self):
        from unittest.mock import MagicMock

        from app.services.upstox_market_feed import InstrumentTick

        feed = MagicMock()
        tick = InstrumentTick("NSE_FO|45450")
        tick.ltp = 250.5
        feed.get_tick.return_value = tick
        bridge = self._bridge(feed)
        seen = []
        bridge.register_observation_handler(seen.append)
        bridge._on_feed_tick({"NSE_FO|45450": {}})
        assert len(seen) == 1
        assert isinstance(seen[0], QuoteObservation)
        assert seen[0].quote.ltp == 250.5

    def test_feed_connect_delegation(self):
        from unittest.mock import AsyncMock, MagicMock

        feed = MagicMock()
        feed.connect = AsyncMock()
        feed.disconnect = AsyncMock()
        bridge = self._bridge(feed)

        async def run():
            await bridge.connect()
            await bridge.subscribe(["NSE_FO|45450"])
            await bridge.disconnect()

        asyncio.run(run())
        feed.connect.assert_called_once_with("NIFTY", "2026-09-24", ["NSE_FO|45450"], bridge._specs)
        feed.disconnect.assert_called_once()

    def test_auth_failure_maps_to_auth_required(self):
        from unittest.mock import MagicMock

        from app.services.upstox_market_feed import FeedState

        feed = MagicMock()
        feed.state = FeedState.AUTH_FAILED
        bridge = self._bridge(feed)
        errors = []
        bridge.register_error_handler(errors.append)
        bridge.poll()
        assert len(errors) == 1
        assert isinstance(errors[0], BrokerError)
        assert errors[0].code is BrokerErrorCode.AUTH_REQUIRED

    def test_is_connected_reflects_feed_state(self):
        from unittest.mock import MagicMock

        from app.services.upstox_market_feed import FeedState

        feed = MagicMock()
        bridge = self._bridge(feed)
        for state, expected in [
            (FeedState.LIVE, True),
            (FeedState.CONNECTED, True),
            (FeedState.DISCONNECTED, False),
            (FeedState.ERROR, False),
            (FeedState.AUTH_FAILED, False),
        ]:
            feed.state = state
            assert bridge.is_connected() is expected

    def test_repr_and_status_exclude_token(self):
        from unittest.mock import MagicMock

        bridge = self._bridge(MagicMock())
        bridge._access_token = "super-secret-token-xyz"  # defensive: never surfaced
        assert "super-secret-token-xyz" not in repr(bridge)
        assert "super-secret-token-xyz" not in str(bridge.source_id)