"""Streaming Lifecycle Manager (Day 13) — the source-neutral streaming boundary.

The lifecycle layer governs the *life* of a streaming source: connection,
disconnection, reconnect with bounded exponential backoff, resubscription,
liveness / stale detection, optional sequence tracking (duplicate, out-of-order,
gap, recovery), intentional shutdown, authentication failure and source
failure — and emits canonical Day-9 observations with provenance preserved.

    Broker streaming source (SDK / transport)
        → StreamingSource protocol (source-neutral)
        → StreamingLifecycleManager
            connection / disconnect / reconnect / bounded backoff /
            resubscription / liveness / stale / sequence / gap / recovery
        → canonical Day-9 observations (provenance preserved, BROKER_LIVE)
        → Day-12 quality layer (StreamQualityContext metadata)

Design rules
------------
1. **Source-neutral.** The manager knows the :class:`StreamingSource`
   protocol surface only — never broker payload structures, tokens or
   credentials.  Sources translate broker events into canonical observations
   and manager events.
2. **Determinism.** Clock, RNG and sleeper are injectable.  No hidden wall
   clock in state transitions; backoff is reproducible for a fixed RNG seed.
3. **No fabrication.**  Sequence numbers are never invented (``supports_sequence
   == False`` ⇒ ``UNSUPPORTED``).  Timestamps are never synthesized.  Stale
   state never emits observations.
4. **Honest continuity.**  An unresolved sequence gap is never reported as
   healthy continuous data: the manager transitions to ``RECOVERY`` and
   ``StreamStatus.gap`` stays ``True`` until contiguity is restored or the
   source marks recovery explicitly.
5. **Intentional shutdown never reconnects.**  Auth failure never retries.
   The reconnect budget is bounded; exhaustion → ``ERROR``.
6. **Boundary integrity.**  Non-canonical observations (raw broker payloads,
   provenance-less quotes, non-``BROKER_LIVE`` modes) are refused at the
   boundary with an ``OBSERVATION_REFUSED`` lifecycle event — the stream is
   never crashed by malformed input, and one consumer callback failure cannot
   kill the feed.
7. **No credentials.**  Lifecycle events, status and repr carry only safe
   fields; error *codes* are recorded, never raw exception text.

No database, no Redis, no workers: this is a deterministic orchestration
layer.  Quality assessment stays with the Day-12 ``MarketDataQualityEngine``;
lifecycle metadata is exposed separately via :meth:`quality_context`.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Sequence

from app.brokers.domain.errors import BrokerError, BrokerErrorCode
from app.market_data.contracts import (
    DataMode,
    MarketObservation,
    OptionChainObservation,
    QuoteObservation,
)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class StreamLifecycleState(str, Enum):
    """Lifecycle states of a streaming source under management."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    SUBSCRIBING = "subscribing"
    LIVE = "live"
    RECONNECTING = "reconnecting"
    STALE = "stale"
    RECOVERY = "recovery"          # unresolved sequence gap — data is degraded
    AUTH_FAILED = "auth_failed"
    STOPPED = "stopped"
    ERROR = "error"


class LifecycleEventType(str, Enum):
    """Structured lifecycle/recovery events emitted by the manager."""

    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    SUBSCRIBING = "SUBSCRIBING"
    LIVE = "LIVE"
    RECONNECTING = "RECONNECTING"
    RECONNECTED = "RECONNECTED"
    RESUBSCRIBED = "RESUBSCRIBED"
    STALE = "STALE"
    FRESH = "FRESH"                        # stale cleared by fresh observation
    GAP_DETECTED = "GAP_DETECTED"
    RECOVERED = "RECOVERED"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    UNSUPPORTED_SEQUENCE = "UNSUPPORTED_SEQUENCE"
    AUTH_FAILED = "AUTH_FAILED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
    OBSERVATION_REFUSED = "OBSERVATION_REFUSED"
    CALLBACK_FAILURE = "CALLBACK_FAILURE"


class SequenceState(str, Enum):
    """Sequence continuity state for sources that expose sequence info."""

    HEALTHY = "HEALTHY"
    GAP_DETECTED = "GAP_DETECTED"
    UNSUPPORTED = "UNSUPPORTED"   # source provides no sequence numbers


class SequenceEvent(str, Enum):
    """Outcome of observing one sequence id."""

    OK = "OK"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    GAP = "GAP"
    RECOVERED = "RECOVERED"
    UNSUPPORTED = "UNSUPPORTED"


# ---------------------------------------------------------------------------
# Configuration / backoff
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackoffPolicy:
    """Bounded exponential backoff with jitter.

    delay(attempt) = min(base * 2**attempt, max) * (1 + jitter_fraction * rng()).

    The jitter is strictly additive and never exceeds the configured
    fraction of the exponential term, so delays are always inside
    ``[exponential, exponential * (1 + jitter_fraction)]``.
    """

    base_seconds: float = 1.0
    max_seconds: float = 30.0
    max_attempts: int = 10
    jitter_fraction: float = 0.25

    def __post_init__(self) -> None:
        if self.base_seconds <= 0:
            raise ValueError("base_seconds must be positive")
        if self.max_seconds < self.base_seconds:
            raise ValueError("max_seconds must be >= base_seconds")
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if not 0.0 <= self.jitter_fraction <= 1.0:
            raise ValueError("jitter_fraction must be in [0, 1]")

    def delay(self, attempt: int, rng) -> float:
        """Deterministic-for-a-seed backoff delay for a zero-based attempt."""
        exponential = min(self.base_seconds * (2 ** max(attempt, 0)), self.max_seconds)
        jitter = exponential * self.jitter_fraction * rng.random()
        return exponential + jitter


@dataclass(frozen=True)
class StreamingConfig:
    """Deterministic streaming thresholds (documented defaults)."""

    stale_after_seconds: float = 10.0
    backoff: BackoffPolicy = field(default_factory=BackoffPolicy)

    def __post_init__(self) -> None:
        if self.stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")


# ---------------------------------------------------------------------------
# Source protocol
# ---------------------------------------------------------------------------


class StreamingSource:
    """Source-neutral streaming-source contract (structural protocol).

    Implementations bridge a concrete broker/transport (e.g. the Upstox V3
    SDK feed) into this boundary.  The lifecycle manager drives connection /
    subscription / resubscription through these methods and receives
    canonical observations and failures through the registered handlers.

    Sources MUST NOT leak broker payloads, tokens or credentials through the
    protocol: observations are Day-9 canonical contracts; errors are raised
    as :class:`~app.brokers.domain.errors.BrokerError` (or classified by an
    optional ``classify_error`` hook).
    """

    source_id: str
    supports_sequence: bool = False

    def register_observation_handler(self, handler: Callable[[Any], None]) -> None: ...
    def register_error_handler(self, handler: Callable[[BaseException], None]) -> None: ...
    def register_disconnect_handler(self, handler: Callable[[], None]) -> None: ...

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def subscribe(self, instruments: Sequence[str]) -> None: ...
    async def resubscribe(self) -> None: ...

    def poll(self) -> None:
        """Called periodically; translate internal source state into manager
        events (e.g. an auth failure observed out-of-band).  Default no-op."""

    def is_connected(self) -> bool:
        """Transport-level connectivity as reported by the source."""
        return True


# ---------------------------------------------------------------------------
# Sequence tracking
# ---------------------------------------------------------------------------


class SequenceTracker:
    """Deterministic sequence-continuity tracker.

    Handles duplicate / out-of-order / gap / recovery semantics for sources
    that expose per-message sequence numbers.  When the source does not
    support sequences (``supported=False``) every observation is
    ``UNSUPPORTED`` — sequence numbers are never invented.
    """

    def __init__(self, supported: bool):
        self._supported = supported
        self._last: int | None = None
        self._state = SequenceState.HEALTHY if supported else SequenceState.UNSUPPORTED

    @property
    def state(self) -> SequenceState:
        return self._state

    @property
    def last_sequence(self) -> int | None:
        return self._last

    @property
    def supported(self) -> bool:
        return self._supported

    def observe(self, sequence_id: int | None) -> SequenceEvent:
        """Record one sequence id and return the continuity outcome."""
        if not self._supported or sequence_id is None or not isinstance(sequence_id, int):
            return SequenceEvent.UNSUPPORTED
        if self._last is None:
            self._last = sequence_id
            self._state = SequenceState.HEALTHY
            return SequenceEvent.OK
        if sequence_id == self._last:
            return SequenceEvent.DUPLICATE
        if sequence_id < self._last:
            return SequenceEvent.OUT_OF_ORDER
        if sequence_id == self._last + 1:
            was_gap = self._state is SequenceState.GAP_DETECTED
            self._last = sequence_id
            self._state = SequenceState.HEALTHY
            return SequenceEvent.RECOVERED if was_gap else SequenceEvent.OK
        # sequence_id > last + 1 → at least one message is missing
        self._last = sequence_id
        self._state = SequenceState.GAP_DETECTED
        return SequenceEvent.GAP

    def mark_recovered(self) -> SequenceEvent:
        """Explicitly mark continuity restored (e.g. after a resubscription
        boundary).  Returns RECOVERED when a gap was open."""
        if not self._supported:
            return SequenceEvent.UNSUPPORTED
        if self._state is SequenceState.GAP_DETECTED:
            self._state = SequenceState.HEALTHY
            return SequenceEvent.RECOVERED
        return SequenceEvent.OK


# ---------------------------------------------------------------------------
# Lifecycle events / status
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LifecycleEvent:
    """A structured, credential-free lifecycle/recovery event."""

    type: LifecycleEventType
    state: StreamLifecycleState
    at: float          # clock seconds (injected clock — not wall clock)
    attempt: int | None = None
    message: str | None = None

    def __repr__(self) -> str:  # never include credentials
        return (
            f"LifecycleEvent(type={self.type.value!r}, state={self.state.value!r}, "
            f"attempt={self.attempt!r})"
        )


@dataclass(frozen=True)
class StreamStatus:
    """Full lifecycle status of a managed stream."""

    state: StreamLifecycleState
    live: bool
    stale: bool
    gap: bool
    sequence_state: SequenceState
    reconnect_attempts: int
    subscription_count: int
    last_activity_age_seconds: float | None
    last_error_code: str | None


@dataclass(frozen=True)
class StreamQualityContext:
    """Lifecycle/recovery metadata for the Day-12 quality layer.

    This is deliberately SEPARATE from quality scoring: the Day-12
    ``MarketDataQualityEngine`` remains the authoritative quality assessment
    over canonical observations.  Consumers combine this context with quality
    results to decide how to act (e.g. never trade on a stream whose gap is
    unresolved or whose data is stale).
    """

    state: StreamLifecycleState
    live: bool
    stale: bool
    gap: bool
    sequence_state: SequenceState
    reconnect_attempts: int
    last_activity_age_seconds: float | None
    last_error_code: str | None


# Codes that are transient transport/upstream conditions — the manager
# reconnects with bounded backoff.  Everything else is terminal for the stream.
_TRANSIENT_CODES = frozenset(
    {
        BrokerErrorCode.RATE_LIMITED,
        BrokerErrorCode.NETWORK_ERROR,
        BrokerErrorCode.UPSTREAM_ERROR,
        BrokerErrorCode.MAINTENANCE,
    }
)
_AUTH_CODES = frozenset({BrokerErrorCode.AUTH_REQUIRED, BrokerErrorCode.TOKEN_EXPIRED})


class StreamingLifecycleManager:
    """Source-neutral streaming lifecycle orchestration boundary."""

    def __init__(
        self,
        source: StreamingSource,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[..., Any] | None = None,
        rng=None,
        config: StreamingConfig | None = None,
        **overrides,
    ):
        self._source = source
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._rng = rng if rng is not None else random

        backoff_kwargs = {
            key: overrides[key]
            for key in ("base_seconds", "max_seconds", "max_attempts", "jitter_fraction")
            if key in overrides
        }
        self._config = config or StreamingConfig(
            stale_after_seconds=overrides.get("stale_after_seconds", 10.0),
            backoff=BackoffPolicy(**backoff_kwargs),
        )

        self._state = StreamLifecycleState.DISCONNECTED
        self._events: deque[LifecycleEvent] = deque(maxlen=1000)
        self._lifecycle_handlers: list[Callable[[LifecycleEvent], None]] = []
        self._observation_handlers: list[Callable[[Any], None]] = []

        self._sequence = SequenceTracker(supported=bool(getattr(source, "supports_sequence", False)))
        self._sequence_unsupported_reported = False
        self._last_activity: float | None = None
        self._reconnect_attempts = 0
        self._last_error_code: str | None = None
        self._subscription_count = 0
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_pending = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> StreamLifecycleState:
        return self._state

    @property
    def events(self) -> list[LifecycleEvent]:
        return list(self._events)

    def register_lifecycle_handler(self, handler: Callable[[LifecycleEvent], None]) -> None:
        self._lifecycle_handlers.append(handler)

    def register_observation_handler(self, handler: Callable[[Any], None]) -> None:
        self._observation_handlers.append(handler)

    async def start(self, instruments: Sequence[str]) -> None:
        """Connect, subscribe and drive the stream to LIVE.

        Fails deterministically: an authentication failure lands in
        ``AUTH_FAILED`` (no retry); a transient connect/subscribe failure
        enters the bounded reconnect flow.
        """
        if self._state not in (
            StreamLifecycleState.DISCONNECTED,
            StreamLifecycleState.AUTH_FAILED,
            StreamLifecycleState.ERROR,
            StreamLifecycleState.STOPPED,
        ):
            raise ValueError("Stream already started; stop() before restarting.")

        self._reconnect_attempts = 0
        self._last_error_code = None
        self._subscription_count = len(instruments)
        self._sequence_unsupported_reported = False
        self._last_activity = self._clock()

        self._source.register_observation_handler(self._on_observation)
        self._source.register_error_handler(self._on_source_error)
        self._source.register_disconnect_handler(self._on_source_disconnect)

        self._set_state(StreamLifecycleState.CONNECTING)
        self._emit(LifecycleEventType.CONNECTING)
        try:
            await self._source.connect()
        except Exception as exc:  # noqa: BLE001 — source failures are classified, never fatal here
            code = self._classify(exc)
            self._last_error_code = code.value
            if code in _AUTH_CODES:
                self._fail_auth()
                return
            self._schedule_reconnect()
            await self._await_reconnect()
            return

        self._set_state(StreamLifecycleState.CONNECTED)
        self._emit(LifecycleEventType.CONNECTED)
        try:
            await self._source.subscribe(instruments)
        except Exception as exc:  # noqa: BLE001
            code = self._classify(exc)
            self._last_error_code = code.value
            if code in _AUTH_CODES:
                self._fail_auth()
                return
            self._schedule_reconnect()
            await self._await_reconnect()
            return

        self._set_state(StreamLifecycleState.SUBSCRIBING)
        self._emit(LifecycleEventType.SUBSCRIBING)
        self._set_state(StreamLifecycleState.LIVE)
        self._emit(LifecycleEventType.LIVE)

    async def stop(self) -> None:
        """Intentional shutdown — the stream NEVER reconnects afterwards."""
        if self._state is StreamLifecycleState.STOPPED:
            return
        self._set_state(StreamLifecycleState.STOPPED)
        self._emit(LifecycleEventType.STOPPED, message="Intentional shutdown.")
        if self._reconnect_task is not None and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._reconnect_task = None
        await self._source.disconnect()

    def heartbeat(self, now: float | None = None) -> None:
        """Periodic liveness check: stale detection + connectivity backstop.

        Deterministic: pass ``now`` (clock seconds) explicitly for tests.
        """
        now = now if now is not None else self._clock()
        if self._reconnect_pending:
            self._schedule_reconnect()
        try:
            self._source.poll()
        except Exception as exc:  # noqa: BLE001
            self._on_source_error(exc)
        self._check_stale(now)
        if self._state in (StreamLifecycleState.LIVE, StreamLifecycleState.RECOVERY):
            try:
                connected = self._source.is_connected()
            except Exception:  # noqa: BLE001
                connected = True
            if not connected:
                self._schedule_reconnect()

    def submit(self, observation: Any) -> None:
        """Submit one source observation into the boundary (sync callback).

        Sources normally reach this through the handler registered by
        ``start()``; exposing it directly keeps the boundary explicit and
        testable.  Non-canonical observations are refused with an
        ``OBSERVATION_REFUSED`` event — never crash, never forward.
        """
        self._on_observation(observation)

    def status(self) -> StreamStatus:
        now = self._clock()
        age = (now - self._last_activity) if self._last_activity is not None else None
        return StreamStatus(
            state=self._state,
            live=self._state is StreamLifecycleState.LIVE,
            stale=self._state is StreamLifecycleState.STALE,
            gap=self._sequence.state is SequenceState.GAP_DETECTED,
            sequence_state=self._sequence.state,
            reconnect_attempts=self._reconnect_attempts,
            subscription_count=self._subscription_count,
            last_activity_age_seconds=round(age, 6) if age is not None else None,
            last_error_code=self._last_error_code,
        )

    def quality_context(self) -> StreamQualityContext:
        """Lifecycle/recovery metadata for Day-12 quality consumers."""
        now = self._clock()
        age = (now - self._last_activity) if self._last_activity is not None else None
        return StreamQualityContext(
            state=self._state,
            live=self._state is StreamLifecycleState.LIVE,
            stale=self._state is StreamLifecycleState.STALE,
            gap=self._sequence.state is SequenceState.GAP_DETECTED,
            sequence_state=self._sequence.state,
            reconnect_attempts=self._reconnect_attempts,
            last_activity_age_seconds=round(age, 6) if age is not None else None,
            last_error_code=self._last_error_code,
        )

    def __repr__(self) -> str:
        source_id = getattr(self._source, "source_id", "?")
        return f"StreamingLifecycleManager(state={self._state.value!r}, source_id={source_id!r})"

    # ------------------------------------------------------------------
    # Source callbacks (registered by start())
    # ------------------------------------------------------------------

    def _on_observation(self, observation: Any) -> None:
        try:
            self._guard_observation(observation)
        except BrokerError as e:
            self._emit(
                LifecycleEventType.OBSERVATION_REFUSED,
                message=e.message,
            )
            return

        now = self._clock()
        self._last_activity = now
        if self._state is StreamLifecycleState.STALE:
            self._set_state(StreamLifecycleState.LIVE)
            self._emit(LifecycleEventType.FRESH, message="Fresh observation received; stale state cleared.")
        elif self._state in (StreamLifecycleState.CONNECTED, StreamLifecycleState.SUBSCRIBING):
            self._set_state(StreamLifecycleState.LIVE)
            self._emit(LifecycleEventType.LIVE)

        self._observe_sequence(observation)

        for cb in list(self._observation_handlers):
            try:
                cb(observation)
            except Exception:  # noqa: BLE001 — one consumer failure never kills the feed
                self._emit(
                    LifecycleEventType.CALLBACK_FAILURE,
                    message="Consumer observation handler raised.",
                )

    def _on_source_error(self, exc: BaseException) -> None:
        code = self._classify(exc)
        self._last_error_code = code.value
        if code in _AUTH_CODES:
            self._fail_auth()
            return
        if code in _TRANSIENT_CODES:
            self._schedule_reconnect()
            return
        self._set_state(StreamLifecycleState.ERROR)
        self._emit(
            LifecycleEventType.ERROR,
            message=f"Source failure ({code.value}); stream stopped.",
        )

    def _on_source_disconnect(self) -> None:
        if self._state in (
            StreamLifecycleState.STOPPED,
            StreamLifecycleState.AUTH_FAILED,
            StreamLifecycleState.ERROR,
        ):
            return
        self._schedule_reconnect()

    # ------------------------------------------------------------------
    # Reconnection
    # ------------------------------------------------------------------

    def _schedule_reconnect(self) -> None:
        if self._state in (
            StreamLifecycleState.STOPPED,
            StreamLifecycleState.AUTH_FAILED,
            StreamLifecycleState.ERROR,
        ):
            return
        if self._state is not StreamLifecycleState.RECONNECTING:
            self._set_state(StreamLifecycleState.RECONNECTING)
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return  # a reconnect flow is already in flight
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._reconnect_pending = True
            return
        self._reconnect_pending = False
        self._reconnect_task = loop.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Bounded exponential-backoff reconnect + resubscription flow."""
        while True:
            if self._state in (
                StreamLifecycleState.STOPPED,
                StreamLifecycleState.AUTH_FAILED,
                StreamLifecycleState.ERROR,
            ):
                return
            attempt = self._reconnect_attempts
            if attempt >= self._config.backoff.max_attempts:
                self._set_state(StreamLifecycleState.ERROR)
                self._emit(
                    LifecycleEventType.ERROR,
                    message="Reconnect budget exhausted; stream stopped.",
                    attempt=attempt,
                )
                return

            delay = self._config.backoff.delay(attempt, self._rng)
            self._set_state(StreamLifecycleState.RECONNECTING)
            self._emit(
                LifecycleEventType.RECONNECTING,
                message=f"Reconnecting (attempt {attempt + 1}); backoff {delay:.2f}s.",
                attempt=attempt,
            )
            await self._sleep(delay)

            self._set_state(StreamLifecycleState.CONNECTING)
            try:
                await self._source.connect()
            except Exception as exc:  # noqa: BLE001
                code = self._classify(exc)
                self._last_error_code = code.value
                if code in _AUTH_CODES:
                    self._fail_auth()
                    return
                self._reconnect_attempts += 1
                continue

            try:
                await self._source.resubscribe()
            except Exception as exc:  # noqa: BLE001
                code = self._classify(exc)
                self._last_error_code = code.value
                if code in _AUTH_CODES:
                    self._fail_auth()
                    return
                self._reconnect_attempts += 1
                continue

            self._reconnect_attempts = 0
            self._set_state(StreamLifecycleState.LIVE)
            self._emit(LifecycleEventType.RECONNECTED, message="Reconnected.")
            self._emit(LifecycleEventType.RESUBSCRIBED, message="Subscription set restored.")
            self._sequence.mark_recovered()
            return

    async def _await_reconnect(self) -> None:
        task = self._reconnect_task
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _set_state(self, state: StreamLifecycleState) -> None:
        self._state = state

    def _emit(
        self,
        event_type: LifecycleEventType,
        *,
        message: str | None = None,
        attempt: int | None = None,
    ) -> None:
        event = LifecycleEvent(
            type=event_type,
            state=self._state,
            at=self._clock(),
            attempt=attempt,
            message=message,
        )
        self._events.append(event)
        for cb in list(self._lifecycle_handlers):
            try:
                cb(event)
            except Exception:  # noqa: BLE001
                pass

    def _fail_auth(self) -> None:
        self._reconnect_attempts = 0
        self._set_state(StreamLifecycleState.AUTH_FAILED)
        self._emit(
            LifecycleEventType.AUTH_FAILED,
            message="Authentication failed; the stream will not reconnect.",
        )

    def _check_stale(self, now: float) -> None:
        if self._state in (
            StreamLifecycleState.LIVE,
            StreamLifecycleState.RECOVERY,
            StreamLifecycleState.SUBSCRIBING,
            StreamLifecycleState.CONNECTED,
        ):
            if (
                self._last_activity is not None
                and now - self._last_activity > self._config.stale_after_seconds
            ):
                self._set_state(StreamLifecycleState.STALE)
                self._emit(
                    LifecycleEventType.STALE,
                    message=f"No data for > {self._config.stale_after_seconds:g}s.",
                )

    def _observe_sequence(self, observation: Any) -> SequenceEvent:
        sequence_id = None
        if isinstance(observation, MarketObservation):
            sequence_id = observation.sequence_id
        event = self._sequence.observe(sequence_id)
        if event is SequenceEvent.GAP:
            if self._state is not StreamLifecycleState.RECOVERY:
                self._set_state(StreamLifecycleState.RECOVERY)
            self._emit(
                LifecycleEventType.GAP_DETECTED,
                message="Sequence gap detected — stream is degraded until recovery.",
            )
        elif event is SequenceEvent.RECOVERED:
            if self._state is StreamLifecycleState.RECOVERY:
                self._set_state(StreamLifecycleState.LIVE)
            self._emit(LifecycleEventType.RECOVERED, message="Sequence continuity restored.")
        elif event is SequenceEvent.DUPLICATE:
            self._emit(LifecycleEventType.DUPLICATE, message="Duplicate sequence id received.")
        elif event is SequenceEvent.OUT_OF_ORDER:
            self._emit(LifecycleEventType.OUT_OF_ORDER, message="Out-of-order sequence id received.")
        elif event is SequenceEvent.UNSUPPORTED:
            if not self._sequence_unsupported_reported:
                self._sequence_unsupported_reported = True
                self._emit(
                    LifecycleEventType.UNSUPPORTED_SEQUENCE,
                    message="Source provides no sequence numbers — continuity is not tracked.",
                )
        return event

    @staticmethod
    def _guard_observation(observation: Any) -> None:
        """Canonical boundary guard — raw payloads never cross this line.

        Raises :class:`BrokerError` with ``INVALID_MARKET_DATA`` for
        non-canonical observations; the caller converts that into an
        ``OBSERVATION_REFUSED`` lifecycle event.
        """
        if not isinstance(
            observation,
            (QuoteObservation, OptionChainObservation, MarketObservation),
        ):
            raise BrokerError(
                BrokerErrorCode.INVALID_MARKET_DATA,
                "Non-canonical observation refused at the streaming boundary — raw broker "
                "payloads never reach downstream consumers.",
            )
        if isinstance(observation, (QuoteObservation, MarketObservation)):
            if observation.provenance is None:
                raise BrokerError(
                    BrokerErrorCode.INVALID_MARKET_DATA,
                    "Canonical observation carries no provenance — refused at the streaming "
                    "boundary (where/when/how the data was produced is unknown).",
                )
            if not observation.provenance.source:
                raise BrokerError(
                    BrokerErrorCode.INVALID_MARKET_DATA,
                    "Canonical observation carries empty provenance.source.",
                )
        if observation.data_mode is not DataMode.BROKER_LIVE:
            raise BrokerError(
                BrokerErrorCode.INVALID_MARKET_DATA,
                "Live-stream observations must be BROKER_LIVE — delayed/snapshot data is "
                "never relabelled real-time.",
            )
        if getattr(observation, "received_timestamp", None) is None:
            raise BrokerError(
                BrokerErrorCode.INVALID_MARKET_DATA,
                "Canonical observation carries no received timestamp — never fabricated.",
            )

    def _classify(self, exc: BaseException) -> BrokerErrorCode:
        """Map a source exception to the canonical broker taxonomy.

        BrokerError passes through with its code.  Otherwise the source's
        optional ``classify_error`` hook is consulted; a hook returning an
        unrecognized value falls back to the honest ``UPSTREAM_ERROR``.
        """
        if isinstance(exc, BrokerError):
            return exc.code
        classify = getattr(self._source, "classify_error", None)
        if callable(classify):
            try:
                return BrokerErrorCode(classify(exc))
            except (ValueError, TypeError):
                pass
        text = str(exc).lower()
        if "401" in text or "unauthorized" in text or "invalid token" in text or "token expired" in text:
            return BrokerErrorCode.AUTH_REQUIRED
        if "429" in text or "rate limit" in text or "rate_limit" in text:
            return BrokerErrorCode.RATE_LIMITED
        return BrokerErrorCode.UPSTREAM_ERROR