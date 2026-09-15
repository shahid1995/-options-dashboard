"""Market Data Gateway (Day 11) — the broker-neutral routing boundary.

The gateway sits ABOVE source adapters and BELOW downstream market-data
consumers:

    Source adapter (session-bound, BrokerAdapter protocol surface)
        → Market Data Gateway
            source selection      (per-request adapter / provider — never
                                   a global credential-holding source)
            capability pre-flight (quotes / option_chain wired?)
            data-mode semantics   (REST = BROKER_SNAPSHOT; BROKER_LIVE
                                   requests need a live-capable source;
                                   delayed data is never relabelled live)
            provenance            (adapter provenance preserved — never
                                   overwritten; mandatory on quotes)
            canonical guard       (raw broker payloads are refused — they
                                   never reach downstream consumers)
        → Day 9 canonical contracts
            (QuoteObservation / OptionChainObservation)
        → downstream consumer

Architecture rules honoured here:

* The gateway understands the Day 9 canonical contracts and the adapter
  protocol surface ONLY — never broker-specific payload fields
  (``last_price``, ``instrument_token``, ``depth``, ``ohlc``, envelopes).
* Consumers request normalized data (canonical identity / symbol + expiry)
  without handling broker keys or tokens.
* The gateway holds NO credentials and no global adapter state: every
  request routes through the session-bound adapter supplied for THAT
  request (or through the caller's source provider).  User-scoped broker
  sessions can never mix through this layer.
* Data-mode semantics are explicit: snapshot sources satisfy
  ``BROKER_SNAPSHOT`` requests only; a ``BROKER_LIVE`` request fails
  deterministically when the source is not live-capable, and an adapter
  observation whose mode contradicts the request is rejected.  Historical /
  imported / replay modes are serviced by separate data-source adapters
  that are not registered yet — the gateway never pretends a broker source
  satisfies them.
* Timestamp/freshness helpers here are pure arithmetic (age in seconds with
  ``None`` semantics) — there is no scoring and no quality classification;
  that is the Day 12 Data Quality engine's job.

No database, no Redis, no caches: this is lightweight orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from app.brokers.domain.capabilities import BrokerCapabilities, CapabilityState
from app.brokers.domain.errors import BrokerError, BrokerErrorCode
from app.market_data.contracts import (
    ContractVersion,
    DataMode,
    OptionChainObservation,
    OptionChainRow,
    PriceQuote,
    QuoteObservation,
)

# Capability names used for gateway pre-flight (canonical broker capability
# matrix names — the same names the broker capability model uses).
_CAP_QUOTES = "quotes"
_CAP_CHAIN = "option_chain"
_CAP_LIVE = "websocket_market_data"

# Canonical chain-dict keys the adapter protocol documents (mapper
# transform_chain contract). The gateway reads ONLY these canonical keys —
# never broker payload keys.
_CHAIN_REQUIRED_KEYS = frozenset({"symbol", "expiry_date", "chain"})


class MarketDataGateway:
    """Source-neutral market-data orchestration boundary.

    Typical use (per user request):

        adapter = broker_gateway.for_connection(user_connection, ...)  # session layer
        gateway = MarketDataGateway()
        obs = await gateway.get_quote(identity, source=adapter)

    The session layer owns adapter construction (credentials); the gateway
    owns canonical routing, mode semantics and boundary integrity.
    """

    def __init__(self, now: Callable[[], datetime] | None = None):
        self._now = now or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------

    async def get_quote(
        self,
        instrument,
        *,
        source=None,
        source_provider: Callable[[], Any] | None = None,
        data_mode: DataMode = DataMode.BROKER_SNAPSHOT,
    ) -> QuoteObservation:
        """One canonical quote observation.

        ``instrument`` is the canonical broker-neutral identity
        (:class:`app.brokers.domain.models.InstrumentIdentity` — see also
        the Day-9 :class:`~app.market_data.contracts.NormalizedInstrument`
        twin).  The observation comes back as the Day-9
        :class:`QuoteObservation` — never a raw broker payload.
        """
        adapter = self._resolve_source(source, source_provider)
        self._preflight(adapter, _CAP_QUOTES, data_mode)
        result = await self._call(adapter, "get_quote", instrument)
        self._guard_quote(result, data_mode)
        self._guard_quote_provenance(result)
        return result

    async def get_quotes(
        self,
        instruments: list,
        *,
        source=None,
        source_provider: Callable[[], Any] | None = None,
        data_mode: DataMode = DataMode.BROKER_SNAPSHOT,
    ) -> list[QuoteObservation]:
        """One canonical quote observation per requested instrument, in
        request order."""
        adapter = self._resolve_source(source, source_provider)
        self._preflight(adapter, _CAP_QUOTES, data_mode)
        result = await self._call(adapter, "get_quotes", instruments)
        if not isinstance(result, list):
            raise self._non_canonical(_CAP_QUOTES)
        for obs in result:
            self._guard_quote(obs, data_mode)
            self._guard_quote_provenance(obs)
        return result

    async def get_option_chain(
        self,
        symbol: str,
        expiry_date: str,
        *,
        source=None,
        source_provider: Callable[[], Any] | None = None,
        data_mode: DataMode = DataMode.BROKER_SNAPSHOT,
    ) -> OptionChainObservation:
        """One canonical option-chain observation for an expiry.

        Consumes the adapter's canonical chain response and returns the
        Day-9 :class:`OptionChainObservation`.  The observation carries the
        gateway collection timestamp, the source label and the snapshot
        mode — chain data today is a point-in-time REST fetch, never
        labelled live.
        """
        adapter = self._resolve_source(source, source_provider)
        self._preflight(adapter, _CAP_CHAIN, data_mode)
        if data_mode is not DataMode.BROKER_SNAPSHOT:
            raise BrokerError(
                BrokerErrorCode.CAPABILITY_UNSUPPORTED,
                "Option-chain data is only available as BROKER_SNAPSHOT — "
                f"requested mode {data_mode.value} cannot be satisfied.",
            )
        result = await self._call(adapter, "get_option_chain", symbol, expiry_date)
        return self._to_chain_observation(result, adapter, symbol, expiry_date)

    # ------------------------------------------------------------------
    # Source selection
    # ------------------------------------------------------------------

    def _resolve_source(self, source, source_provider):
        """Deterministic source selection: an explicitly supplied adapter
        wins; otherwise the caller's provider is invoked.  No source and no
        provider → a clean SOURCE_UNAVAILABLE error — the gateway never
        fabricates or substitutes a source."""
        if source is not None:
            return source
        if source_provider is not None:
            adapter = source_provider()
            if adapter is not None:
                return adapter
        raise BrokerError(
            BrokerErrorCode.SOURCE_UNAVAILABLE,
            "No market-data source is available for this request: supply the "
            "authorized broker adapter (or a source provider) for the current "
            "session.",
        )

    # ------------------------------------------------------------------
    # Capability / data-mode pre-flight
    # ------------------------------------------------------------------

    def _preflight(self, adapter, capability: str, data_mode: DataMode) -> None:
        caps = self._capabilities(adapter)
        if data_mode is DataMode.BROKER_LIVE:
            live = caps.get(_CAP_LIVE)
            if live is None or not live.wired:
                raise BrokerError(
                    BrokerErrorCode.CAPABILITY_UNSUPPORTED,
                    "BROKER_LIVE market data is not available: no live-capable "
                    "source is registered. Snapshot (BROKER_SNAPSHOT) data is "
                    "never relabelled real-time.",
                )
        elif data_mode not in (DataMode.BROKER_SNAPSHOT,):
            raise BrokerError(
                BrokerErrorCode.CAPABILITY_UNSUPPORTED,
                f"Data mode {data_mode.value} is not serviced by broker "
                "source adapters — historical/imported/replay data has its "
                "own (unregistered) data-source adapters.",
            )
        item = caps.get(capability)
        if item is None or not item.wired or item.state is CapabilityState.UNSUPPORTED:
            raise BrokerError(
                BrokerErrorCode.CAPABILITY_UNSUPPORTED,
                f"Source capability '{capability}' is not wired/available for "
                "this request.",
            )
        if item.state is not CapabilityState.SUPPORTED and item.state is not CapabilityState.AVAILABLE:
            raise self._capability_state_error(item.state, capability)

    @staticmethod
    def _capabilities(adapter) -> BrokerCapabilities:
        get_caps = getattr(adapter, "get_capabilities", None)
        if not callable(get_caps):
            raise BrokerError(
                BrokerErrorCode.CAPABILITY_UNSUPPORTED,
                "Source adapter exposes no capability model.",
            )
        return get_caps()

    @staticmethod
    def _capability_state_error(state: CapabilityState, capability: str) -> BrokerError:
        mapping = {
            CapabilityState.AUTH_REQUIRED: BrokerErrorCode.AUTH_REQUIRED,
            CapabilityState.ACCOUNT_DISABLED: BrokerErrorCode.ACCOUNT_RESTRICTED,
            # UNAVAILABLE / TEMPORARILY_UNAVAILABLE are upstream-adjacent
            # conditions with no more specific taxonomy entry — the honest
            # fallback per the taxonomy docs.
            CapabilityState.UNAVAILABLE: BrokerErrorCode.UPSTREAM_ERROR,
            CapabilityState.TEMPORARILY_UNAVAILABLE: BrokerErrorCode.UPSTREAM_ERROR,
        }
        code = mapping.get(state, BrokerErrorCode.CAPABILITY_UNSUPPORTED)
        return BrokerError(
            code,
            f"Source capability '{capability}' is {state.value} for this request.",
        )

    # ------------------------------------------------------------------
    # Boundary guards
    # ------------------------------------------------------------------

    @staticmethod
    async def _call(adapter, method: str, *args):
        fn = getattr(adapter, method, None)
        if not callable(fn):
            raise BrokerError(
                BrokerErrorCode.CAPABILITY_UNSUPPORTED,
                f"Source adapter does not implement '{method}'.",
            )
        return await fn(*args)

    @staticmethod
    def _guard_quote(obs, data_mode: DataMode) -> None:
        if not isinstance(obs, QuoteObservation):
            raise BrokerError(
                BrokerErrorCode.INVALID_MARKET_DATA,
                "Source adapter returned a non-canonical quote payload — raw "
                "broker data is refused at the gateway boundary.",
            )
        if obs.data_mode is not None and obs.data_mode is not data_mode:
            raise BrokerError(
                BrokerErrorCode.INVALID_MARKET_DATA,
                f"Source observation is labelled {obs.data_mode.value} but the "
                f"request asked for {data_mode.value} — data-mode mismatch "
                "rejected (delayed data is never relabelled real-time).",
            )

    @staticmethod
    def _guard_quote_provenance(obs: QuoteObservation) -> None:
        if obs.provenance is None:
            raise BrokerError(
                BrokerErrorCode.INVALID_MARKET_DATA,
                "Canonical quote observation carries no provenance — it cannot "
                "answer where/when/how the data was produced and is refused at "
                "the gateway boundary.",
            )
        if not obs.provenance.source:
            raise BrokerError(
                BrokerErrorCode.INVALID_MARKET_DATA,
                "Canonical quote observation carries empty provenance.source.",
            )

    def _to_chain_observation(
        self,
        result,
        adapter,
        symbol: str,
        expiry_date: str,
    ) -> OptionChainObservation:
        # A future source adapter may already return the canonical
        # observation directly — accept it after validating its metadata.
        if isinstance(result, OptionChainObservation):
            return result

        if not isinstance(result, dict):
            raise self._non_canonical(_CAP_CHAIN)
        if not _CHAIN_REQUIRED_KEYS.issubset(result.keys()):
            raise BrokerError(
                BrokerErrorCode.INVALID_MARKET_DATA,
                "Source adapter returned a chain payload that is not the "
                "canonical chain contract — raw broker data is refused at the "
                "gateway boundary.",
            )

        rows = []
        for raw_row in result.get("chain", []):
            if not isinstance(raw_row, dict) or raw_row.get("strike") is None:
                continue  # malformed row, not fatal — mirror adapter semantics
            rows.append(
                OptionChainRow(
                    strike=float(raw_row["strike"]),
                    call=self._chain_leg(raw_row.get("call")),
                    put=self._chain_leg(raw_row.get("put")),
                )
            )
        rows.sort(key=lambda row: row.strike)

        source_label = getattr(adapter, "broker_id", None)
        return OptionChainObservation(
            symbol=result.get("symbol", symbol),
            expiry_date=result.get("expiry_date", expiry_date),
            underlying_spot_price=_optional_float(result.get("underlying_spot_price")),
            chain=rows,
            market_timestamp=None,  # no single exchange event time at chain level
            received_timestamp=self._now(),
            source=source_label,
            data_mode=DataMode.BROKER_SNAPSHOT,
            contract_version=ContractVersion.v1_0_0,
        )

    @staticmethod
    def _chain_leg(leg) -> PriceQuote | None:
        """Project one canonical chain leg onto the Day-9 PriceQuote.

        Reads only the canonical chain-leg keys (``ltp`` / ``oi`` /
        ``volume``) defined by the adapter protocol — never broker payload
        keys.  A leg with no LTP is absent (``None``) rather than a
        fabricated zero price.
        """
        if not isinstance(leg, dict):
            return None
        ltp = leg.get("ltp")
        if ltp is None:
            return None
        return PriceQuote(
            ltp=float(ltp),
            volume=_optional_float(leg.get("volume")),
            oi=_optional_float(leg.get("oi")),
        )

    @staticmethod
    def _non_canonical(operation: str) -> BrokerError:
        return BrokerError(
            BrokerErrorCode.INVALID_MARKET_DATA,
            f"Source adapter returned a non-canonical {operation} payload — "
            "raw broker data is refused at the gateway boundary.",
        )


# ---------------------------------------------------------------------------
# Timestamp / freshness helpers (pure arithmetic — NOT quality scoring)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObservationAges:
    """Age of an observation in seconds at a reference ``now``.

    ``market_age_seconds`` is the age of the exchange/event timestamp
    (``None`` when the observation has no market timestamp — never
    fabricated).  ``received_age_seconds`` is the age of the application
    receive timestamp.  This is timestamp normalization only: there is no
    score and no quality classification here (Day 12).
    """

    market_age_seconds: float | None
    received_age_seconds: float | None


def observation_ages(observation, *, now: datetime | None = None) -> ObservationAges:
    """Compute market/received ages of a canonical observation at ``now``.

    Deterministic: pass ``now`` for reproducible results.
    """
    reference = now or datetime.now(timezone.utc)

    def age(ts) -> float | None:
        if ts is None:
            return None
        return (reference - ts).total_seconds()

    return ObservationAges(
        market_age_seconds=age(getattr(observation, "market_timestamp", None)),
        received_age_seconds=age(getattr(observation, "received_timestamp", None)),
    )


def _optional_float(value) -> float | None:
    if value is None:
        return None
    return float(value)
