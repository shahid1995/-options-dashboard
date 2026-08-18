"""Phase 6.1 — Upstox broker margin integration (READ-ONLY).

Implements the real Upstox provider behind the Phase 6.0 ``MarginProvider``
abstraction (``app/services/capital.py``). Two read-only broker endpoints:

- ``GET  /v3/user/get-funds-and-margin``  (``Api-Version: 3.0``) — account
  funds & margin: available-to-trade, cash available, margin used, SPAN +
  exposure, premium present, pledge available. The documented maintenance
  window (12:00 AM – 5:30 AM IST, HTTP 423) is surfaced as an UNAVAILABLE
  broker status with ``BROKER_MAINTENANCE`` — never a crash, never a 0.
- ``POST /v2/charges/margin`` — broker-computed margin for a basket of up to
  20 instruments. The provider sends the COMPLETE multi-leg strategy set in
  ONE request so Upstox applies spread/combination logic; the broker-reported
  ``required_margin`` (whole-request) is preserved as the authoritative
  figure. The platform NEVER re-derives margin from per-leg sums and never
  re-computes SPAN/exposure itself (analytical models belong to Phase 6.2+).

Non-negotiable rules carried over from Phase 6.0:

- Every broker value keeps ``source = BROKER_REPORTED`` and a status of
  available | partial | unavailable. Missing values are ``null``, never 0.
- No fallback from broker margin to ESTIMATED capital, and no fallback from
  broker funds to paper cash.
- Broker available funds and strategy broker margin are different concepts
  and stay separate (no "margin available" relabeling).
- No real-money order placement — funds and margin are read-only.

Quantity contract (§13): Phase 5 quantities are LOTS; the Upstox margin API
expects broker contract units, so every leg is converted with
``lots × lot_size`` (e.g. 1 lot of NIFTY = 65 contracts). Never send ``1``
when ``1 lot = 65``.

Product type (§12): the paper engine has no broker-product concept (it
simulates held positions, not intraday square-off), so the margin request
uses ``BROKER_PRODUCT_DEFAULT = "D"`` (delivery) for F&O options. This is
documented in one place and kept behind a module constant; broker-specific
values never leak into the capital domain.

Instrument keys (§14): resolved from the existing option-chain API (the same
market-data path paper execution already uses) — ``call_options`` /
``put_options`` each carry the contract's ``instrument_key``. Keys are never
constructed manually from strike text. When a key cannot be resolved the
strategy margin is unavailable with a structured ``MISSING_INSTRUMENT_KEY``
error and no broker request is submitted.

Caching policy (§25/§26): capital/funds data is NOT quote data.
- account funds are cached briefly (``FUNDS_TTL_SECONDS`` = 60 s)
- strategy margin is cached by ``user + strategy fingerprint``
  (``MARGIN_TTL_SECONDS`` = 300 s)
- every snapshot carries ``generated_at`` / ``expires_at`` so stale broker
  data is never presented as real-time.
Margin APIs are never called from the existing 1-second chain tick loop.

User isolation (§28): all cache keys are scoped by ``user_id`` — one user's
margin is never served from another user's cache entry.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from app.brokers.adapters.upstox import mapper as _upstox_mapper
from app.brokers.domain.enums import BROKER_ID_UPSTOX
from app.brokers.domain.errors import BrokerError, BrokerErrorCode
from app.brokers.gateway import gateway
from app.services.capital import (
    SOURCE_BROKER_REPORTED,
    STATUS_AVAILABLE,
    STATUS_PARTIAL,
    STATUS_UNAVAILABLE,
    MarginProvider,
    is_valid_number,
)
from app.services.upstox import UpstoxError

# ---- Structured broker errors (§24) -----------------------------------------

BROKER_AUTH_REQUIRED = "BROKER_AUTH_REQUIRED"
BROKER_TOKEN_EXPIRED = "BROKER_TOKEN_EXPIRED"
BROKER_RATE_LIMITED = "BROKER_RATE_LIMITED"
BROKER_FUNDS_UNAVAILABLE = "BROKER_FUNDS_UNAVAILABLE"
BROKER_MARGIN_UNAVAILABLE = "BROKER_MARGIN_UNAVAILABLE"
MISSING_INSTRUMENT_KEY = "MISSING_INSTRUMENT_KEY"
MARGIN_REQUEST_TOO_LARGE = "MARGIN_REQUEST_TOO_LARGE"
BROKER_BAD_RESPONSE = "BROKER_BAD_RESPONSE"
BROKER_MAINTENANCE = "BROKER_MAINTENANCE"

MAINTENANCE_MESSAGE = (
    "Upstox Funds service is in its daily maintenance window (12:00 AM – 5:30 AM IST)."
)


class BrokerMarginError(Exception):
    """A structured broker-data failure. Carries a stable ``code`` (one of the
    constants above) and a human-readable message. Never a raw provider stack
    trace — the capital domain only ever sees the structured code + message.
    """

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def classify_upstox_error(exc: UpstoxError, kind: str = "funds") -> BrokerMarginError:
    """Map an Upstox HTTP failure to a structured broker error code.

    Kept for injected test fetchers and direct compatibility. The live path
    routes through the adapter, which raises canonical BrokerError mapped by
    ``classify_broker_error`` below.

    ``kind`` is ``funds`` or ``margin`` and only decides the generic fallback
    code (BROKER_FUNDS_UNAVAILABLE vs BROKER_MARGIN_UNAVAILABLE); auth, rate
    limit and the 423 maintenance window always map to their own codes.
    """
    fallback = BROKER_FUNDS_UNAVAILABLE if kind == "funds" else BROKER_MARGIN_UNAVAILABLE
    if exc.status_code in (401, 403):
        return BrokerMarginError(
            BROKER_TOKEN_EXPIRED, "Upstox session expired or unauthorized — broker data is unavailable."
        )
    if exc.status_code == 423:
        return BrokerMarginError(BROKER_MAINTENANCE, MAINTENANCE_MESSAGE)
    if exc.status_code == 429:
        return BrokerMarginError(BROKER_RATE_LIMITED, "Upstox rate limit reached — try again shortly.")
    return BrokerMarginError(fallback, f"Upstox API error ({exc.status_code}): {exc.message}")


def classify_broker_error(exc: BrokerError, kind: str = "funds") -> BrokerMarginError:
    """Map a canonical BrokerError to the structured broker-data error code.

    Mirrors ``classify_upstox_error`` so the adapter path (the live path)
    produces the exact same structured codes and human messages.
    """
    fallback = BROKER_FUNDS_UNAVAILABLE if kind == "funds" else BROKER_MARGIN_UNAVAILABLE
    if exc.code in (BrokerErrorCode.AUTH_REQUIRED, BrokerErrorCode.TOKEN_EXPIRED):
        return BrokerMarginError(
            BROKER_TOKEN_EXPIRED, "Upstox session expired or unauthorized — broker data is unavailable."
        )
    if exc.code is BrokerErrorCode.MAINTENANCE:
        return BrokerMarginError(BROKER_MAINTENANCE, MAINTENANCE_MESSAGE)
    if exc.code is BrokerErrorCode.RATE_LIMITED:
        return BrokerMarginError(BROKER_RATE_LIMITED, "Upstox rate limit reached — try again shortly.")
    if exc.status_code:
        return BrokerMarginError(fallback, f"Upstox API error ({exc.status_code}): {exc.message}")
    return BrokerMarginError(fallback, str(exc.message))


# ---- Product type (§12) ------------------------------------------------------

# The paper engine simulates HELD positions (no intraday square-off concept),
# so F&O margin requests use the delivery product. Kept as one documented,
# testable constant — a future broker-product concept can map here.
BROKER_PRODUCT_DEFAULT = "D"


# ---- Pure helpers ------------------------------------------------------------

def lots_to_contracts(quantity_lots: int, lot_size: int) -> int:
    """Convert Phase 5 LOTS into broker contract quantity (lots × lot_size).

    Upstox margin APIs expect contract units: 1 lot of NIFTY (lot_size 65)
    → 65 contracts. Never pass lots directly to the broker. (Compat wrapper
    — canonical implementation lives in the Upstox adapter mapper.)
    """
    return _upstox_mapper.lots_to_contracts(quantity_lots, lot_size)


def net_strategy_instruments(orders: list[dict]) -> list[dict]:
    """Aggregate one whole strategy execution's entry orders into NET
    instruments (same netting rule as Phase 5.0 positions: buy = +, sell = −).

    A leg pair that nets to zero (e.g. buy AND sell the same strike) produces
    no margin instrument — there is no position to margin. Order of the
    returned instruments is deterministic (sorted by instrument identity).
    """
    nets: dict[tuple, dict] = {}
    for order in orders or []:
        if order.get("status") != "FILLED":
            continue
        key = (order["symbol"], order["expiry"], order["strike"], order["option_type"])
        entry = nets.setdefault(
            key,
            {"symbol": order["symbol"], "expiry": order["expiry"], "strike": order["strike"],
             "option_type": order["option_type"], "quantity": 0, "lot_size": order["lot_size"]},
        )
        signed = int(order["quantity"]) if order["action"] == "buy" else -int(order["quantity"])
        entry["quantity"] += signed

    instruments = []
    for info in nets.values():
        if info["quantity"] == 0:
            continue  # fully netted — no position, no margin
        instruments.append(
            {
                "symbol": info["symbol"],
                "expiry": info["expiry"],
                "strike": info["strike"],
                "option_type": info["option_type"],
                "action": "buy" if info["quantity"] > 0 else "sell",
                "quantity": abs(info["quantity"]),  # lots
                "lot_size": info["lot_size"],
            }
        )
    instruments.sort(
        key=lambda i: (i["symbol"], i["expiry"], i["strike"], i["option_type"], i["action"])
    )
    return instruments


def strategy_fingerprint(instruments: list[dict]) -> str:
    """Deterministic fingerprint of the margin-relevant inputs (§27).

    Includes symbol, expiry, strike, option type, action, contract quantity
    (lots × lot_size) and product. Leg order is normalized (sorted) so the
    same strategy structure always yields the same fingerprint, while any
    change in quantity / expiry / strike / action changes it.
    """
    parts = []
    for inst in sorted(
        instruments,
        key=lambda i: (i["symbol"], i["expiry"], i["strike"], i["option_type"], i["action"]),
    ):
        parts.append(
            {
                "symbol": inst["symbol"],
                "expiry": inst["expiry"],
                "strike": inst["strike"],
                "option_type": inst["option_type"],
                "action": inst["action"],
                "contract_quantity": lots_to_contracts(inst["quantity"], inst["lot_size"]),
                "product": inst.get("product", BROKER_PRODUCT_DEFAULT),
            }
        )
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_margin_request_instruments(instruments: list[dict], product: str = BROKER_PRODUCT_DEFAULT) -> list[dict]:
    """Build the ``POST /v2/charges/margin`` payload instruments.

    Every instrument carries the resolved broker key, the contract quantity
    (lots → contracts), BUY/SELL and the documented product. The full
    multi-leg strategy set goes in ONE request. (Compat wrapper — the
    Upstox-specific payload lives in the adapter mapper.)
    """
    return _upstox_mapper.build_margin_request_instruments(instruments, product=product)


def map_funds_payload(data: dict | None) -> dict:
    """Map the V3 funds response (``data`` object) to the capital contract.

    Keeps broker terminology: available_to_trade, cash available, margin
    used, SPAN+exposure, premium present, pledge available. Missing fields
    stay ``None`` — never fabricated 0. The full raw payload is preserved in
    ``raw``. (Compat wrapper — canonical implementation lives in the Upstox
    adapter mapper.)
    """
    return _upstox_mapper.map_funds_payload(data)


def map_margin_payload(data: dict | None) -> dict:
    """Map the V2 margin response to the capital contract.

    ``required_margin`` (the broker's whole-request figure) is authoritative
    and preserved as-is — the platform never sums SPAN + exposure itself.
    Per-instrument rows are kept separately in ``rows``. (Compat wrapper —
    canonical implementation lives in the Upstox adapter mapper.)
    """
    return _upstox_mapper.map_margin_payload(data)


async def default_instrument_key_resolver(access_token: str, instruments: list[dict]) -> list[dict]:
    """Resolve broker instrument keys from the existing option-chain API.

    Delegates to the Upstox adapter (``resolve_instrument_keys``), which
    fetches each required expiry's chain ONCE and reads the contract's
    Upstox ``instrument_key`` from the raw payload — never constructed from
    strike text. Legs whose strike/side is missing get ``instrument_key:
    None`` (the provider then returns MISSING_INSTRUMENT_KEY instead of
    submitting an invalid request). Compat wrapper kept for direct callers.
    """
    adapter = gateway.create(BROKER_ID_UPSTOX, access_token=access_token)
    return await adapter.resolve_instrument_keys(instruments)


# ---- Caching (§25/§26/§28) ---------------------------------------------------


class BrokerMarginCache:
    """Small TTL cache for broker funds / strategy margin.

    Keys are strings; a value expires after its TTL and is never served
    stale. Strategy-margin keys embed the user id AND the strategy
    fingerprint, so users are isolated and identical strategies reuse the
    broker result while changed strategies miss the cache.
    """

    def __init__(self, now=None):
        self._store: dict[str, dict] = {}
        self._now = now or (lambda: datetime.now(timezone.utc))

    def get(self, key: str):
        item = self._store.get(key)
        if item is None:
            return None
        if item["expires_at"] <= self._now():
            del self._store[key]
            return None
        return item["value"]

    def set(self, key: str, value, ttl_seconds: int) -> None:
        self._store[key] = {"value": value, "expires_at": self._now() + timedelta(seconds=ttl_seconds)}

    def clear(self) -> None:
        self._store.clear()


# ---- Upstox provider ---------------------------------------------------------


class UpstoxMarginProvider(MarginProvider):
    """Real Upstox implementation behind the Phase 6.0 MarginProvider.

    Read-only: fetches account funds (V3) and whole-strategy broker margin
    (V2 charges/margin) with the authenticated broker session. Never places
    orders. Never fabricates figures: on any failure the affected broker
    figures stay UNAVAILABLE with a structured error code, and broker data is
    never replaced by ESTIMATED capital or paper cash.
    """

    FUNDS_TTL_SECONDS = 60          # funds are cached briefly (§25)
    MARGIN_TTL_SECONDS = 300        # strategy margin is cached 5 minutes max
    MAX_INSTRUMENTS = 20            # Upstox limit (§16)

    def __init__(
        self,
        access_token: str,
        funds_fetcher=None,
        margin_fetcher=None,
        instrument_resolver=None,
        cache: BrokerMarginCache | None = None,
        now=None,
        adapter=None,
    ):
        self.access_token = access_token
        # Injected fetchers (tests / tooling) override the adapter path. When
        # None, the broker gateway builds an Upstox adapter that performs the
        # call through the canonical boundary (errors arrive as BrokerError).
        self._funds_fetcher = funds_fetcher
        self._margin_fetcher = margin_fetcher
        self._instrument_resolver = instrument_resolver
        self._adapter = adapter
        self._cache = cache or BrokerMarginCache()
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _broker_adapter(self):
        """The canonical Upstox adapter for this provider's session."""
        if self._adapter is not None:
            return self._adapter
        return gateway.create(BROKER_ID_UPSTOX, access_token=self.access_token)

    # ---- interface ----------------------------------------------------------

    async def get_capital_snapshot(self, context: dict) -> dict:
        """Broker snapshot for ONE authenticated user's full strategy set.

        ``context`` carries ``user_id``, ``broker``, ``strategies`` (each with
        its ``orders`` — the whole-strategy entry leg set) and ``account``.
        Returns the Phase 6.0 contract extended with funds/margin detail and
        timestamps. Never raises for broker failures: failures are reported
        as structured unavailable statuses.
        """
        user_id = context.get("user_id")
        strategies = context.get("strategies", [])
        generated_at = self._now().isoformat()

        funds = await self._funds_snapshot(user_id, generated_at)
        margin = await self._margin_snapshot(user_id, strategies, generated_at)

        margin_ok = margin["status"] == STATUS_AVAILABLE
        funds_ok = funds["status"] == STATUS_AVAILABLE
        if margin_ok and funds_ok:
            overall = STATUS_AVAILABLE
        elif margin_ok or funds_ok:
            overall = STATUS_PARTIAL
        else:
            overall = STATUS_UNAVAILABLE

        timestamps = [t for t in (funds.get("timestamp"), margin.get("timestamp")) if t]
        expires_at = margin.get("expires_at") or funds.get("expires_at")
        return {
            "broker_margin": margin["required_margin"],
            "broker_margin_status": margin["status"],
            "broker_margin_timestamp": margin.get("timestamp"),
            "broker_available_funds": funds["available_to_trade"],
            "broker_cash_available": funds["cash_available_to_trade"],
            "broker_margin_used": funds["margin_used"],
            "broker_pledge_available": funds["pledge_available_to_trade"],
            "broker_funds_timestamp": funds.get("timestamp"),
            "broker_funds_detail": funds["detail"],
            "broker_margin_detail": margin["detail"],
            "source": SOURCE_BROKER_REPORTED,
            "status": overall,
            "timestamp": max(timestamps) if timestamps else None,
            "generated_at": generated_at,
            "expires_at": expires_at,
            "errors": {"funds": funds.get("error"), "margin": margin.get("errors", [])},
        }

    # ---- account funds ------------------------------------------------------

    async def _funds_snapshot(self, user_id: str, generated_at: str) -> dict:
        cache_key = f"funds:{user_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            if self._funds_fetcher is not None:
                body = await self._funds_fetcher(self.access_token)
            else:
                body = await self._broker_adapter().get_funds()
            if not isinstance(body, dict):
                raise BrokerMarginError(BROKER_BAD_RESPONSE, "Upstox funds response was not an object.")
            mapped = map_funds_payload(body.get("data"))
            expires_at = (self._now() + timedelta(seconds=self.FUNDS_TTL_SECONDS)).isoformat()
            snapshot = {
                "available_to_trade": mapped["available_to_trade"],
                "cash_available_to_trade": mapped["cash_available_to_trade"],
                "margin_used": mapped["margin_used"],
                "pledge_available_to_trade": mapped["pledge_available_to_trade"],
                "status": STATUS_AVAILABLE,
                "timestamp": generated_at,
                "expires_at": expires_at,
                "error": None,
                "detail": {**mapped, "generated_at": generated_at, "expires_at": expires_at},
            }
        except UpstoxError as exc:
            snapshot = self._unavailable_funds(classify_upstox_error(exc, kind="funds"))
        except BrokerError as exc:
            snapshot = self._unavailable_funds(classify_broker_error(exc, kind="funds"))
        except BrokerMarginError as exc:
            snapshot = self._unavailable_funds(exc)
        self._cache.set(cache_key, snapshot, self.FUNDS_TTL_SECONDS)
        return snapshot

    @staticmethod
    def _unavailable_funds(error: BrokerMarginError) -> dict:
        return {
            "available_to_trade": None,
            "cash_available_to_trade": None,
            "margin_used": None,
            "pledge_available_to_trade": None,
            "status": STATUS_UNAVAILABLE,
            "timestamp": None,
            "expires_at": None,
            "error": error.code,
            "detail": {
                "available_to_trade": None, "cash_available_to_trade": None,
                "margin_used": None, "span_exposure": None, "cash_margin_var_elm": None,
                "premium_present": None, "delivery_margin": None,
                "pledge_available_to_trade": None, "margin_from_pledge": None,
                "pledge_margin_used": None, "unsettled_profit": None, "raw": None,
                "error": error.code, "message": error.message,
                "generated_at": None, "expires_at": None,
            },
        }

    # ---- strategy margin ----------------------------------------------------

    async def _margin_snapshot(self, user_id: str, strategies: list[dict], generated_at: str) -> dict:
        per_strategy = []
        required_values = []
        statuses = []
        errors = []
        expires_at = None
        for strategy in strategies:
            row = await self._strategy_margin_row(user_id, strategy, generated_at)
            per_strategy.append(row)
            statuses.append(row["status"])
            if row["status"] == STATUS_AVAILABLE and is_valid_number(row["required_margin"]):
                required_values.append(row["required_margin"])
            if row.get("error"):
                errors.append(row["error"])
            if row.get("expires_at") and (expires_at is None or row["expires_at"] > expires_at):
                expires_at = row["expires_at"]

        if required_values:
            aggregate_margin = round(sum(required_values), 2)
            aggregate_status = (
                STATUS_PARTIAL if any(s != STATUS_AVAILABLE for s in statuses) else STATUS_AVAILABLE
            )
        else:
            aggregate_margin = None
            aggregate_status = STATUS_UNAVAILABLE

        timestamps = [r["timestamp"] for r in per_strategy if r.get("timestamp")]
        return {
            "required_margin": aggregate_margin,
            "status": aggregate_status,
            "timestamp": max(timestamps) if timestamps else None,
            "expires_at": expires_at,
            "errors": errors,
            "detail": {
                "per_strategy": per_strategy,
                "aggregate_required_margin": aggregate_margin,
                "aggregate_status": aggregate_status,
                "generated_at": generated_at,
                "expires_at": expires_at,
            },
        }

    async def _strategy_margin_row(self, user_id: str, strategy: dict, generated_at: str) -> dict:
        instruments = net_strategy_instruments(strategy.get("orders") or [])
        if not instruments:
            # No net position in this open strategy → no margin required. This
            # is derived from the strategy structure (not a margin model) and
            # cannot occur for genuinely open strategies with open positions.
            return {
                "execution_id": strategy.get("execution_id"),
                "strategy_tag": strategy.get("strategy_tag"),
                "status": STATUS_AVAILABLE,
                "error": None,
                "required_margin": 0.0,
                "final_margin": 0.0,
                "instrument_count": 0,
                "timestamp": generated_at,
                "expires_at": (self._now() + timedelta(seconds=self.MARGIN_TTL_SECONDS)).isoformat(),
                "rows": [],
            }

        if len(instruments) > self.MAX_INSTRUMENTS:
            return self._margin_row_unavailable(
                strategy,
                MARGIN_REQUEST_TOO_LARGE,
                f"{len(instruments)} instruments exceed the Upstox 20-instrument limit.",
            )

        fingerprint = strategy_fingerprint(instruments)
        cache_key = f"margin:{user_id}:{fingerprint}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            if self._instrument_resolver is not None:
                resolved = await self._instrument_resolver(self.access_token, instruments)
            else:
                resolved = await self._broker_adapter().resolve_instrument_keys(instruments)
        except UpstoxError as exc:
            err = classify_upstox_error(exc, kind="margin")
            row = self._margin_row_unavailable(strategy, err.code, err.message)
            self._cache.set(cache_key, row, self.MARGIN_TTL_SECONDS)
            return row
        except BrokerError as exc:
            err = classify_broker_error(exc, kind="margin")
            row = self._margin_row_unavailable(strategy, err.code, err.message)
            self._cache.set(cache_key, row, self.MARGIN_TTL_SECONDS)
            return row
        except BrokerMarginError as exc:
            row = self._margin_row_unavailable(strategy, exc.code, exc.message)
            self._cache.set(cache_key, row, self.MARGIN_TTL_SECONDS)
            return row

        missing = [inst for inst in resolved if not inst.get("instrument_key")]
        if missing:
            row = self._margin_row_unavailable(
                strategy,
                MISSING_INSTRUMENT_KEY,
                f"Instrument key unavailable for {len(missing)} of {len(resolved)} leg(s) — no broker request submitted.",
            )
            self._cache.set(cache_key, row, self.MARGIN_TTL_SECONDS)
            return row

        try:
            payload = build_margin_request_instruments(resolved)
            if self._margin_fetcher is not None:
                body = await self._margin_fetcher(self.access_token, payload)
            else:
                body = await self._broker_adapter().get_margin(payload)
            if not isinstance(body, dict):
                raise BrokerMarginError(BROKER_BAD_RESPONSE, "Upstox margin response was not an object.")
            mapped = map_margin_payload(body)
            if not is_valid_number(mapped["required_margin"]):
                raise BrokerMarginError(
                    BROKER_BAD_RESPONSE, "Upstox margin response had no valid required_margin."
                )
            expires_at = (self._now() + timedelta(seconds=self.MARGIN_TTL_SECONDS)).isoformat()
            row = {
                "execution_id": strategy.get("execution_id"),
                "strategy_tag": strategy.get("strategy_tag"),
                "status": STATUS_AVAILABLE,
                "error": None,
                "required_margin": round(mapped["required_margin"], 2),
                "final_margin": mapped["final_margin"],
                "instrument_count": len(resolved),
                "timestamp": generated_at,
                "expires_at": expires_at,
                "rows": mapped["rows"],
            }
        except UpstoxError as exc:
            err = classify_upstox_error(exc, kind="margin")
            row = self._margin_row_unavailable(strategy, err.code, err.message)
        except BrokerError as exc:
            err = classify_broker_error(exc, kind="margin")
            row = self._margin_row_unavailable(strategy, err.code, err.message)
        except BrokerMarginError as exc:
            row = self._margin_row_unavailable(strategy, exc.code, exc.message)
        self._cache.set(cache_key, row, self.MARGIN_TTL_SECONDS)
        return row

    @staticmethod
    def _margin_row_unavailable(strategy: dict, code: str | None, message: str | None) -> dict:
        return {
            "execution_id": strategy.get("execution_id"),
            "strategy_tag": strategy.get("strategy_tag"),
            "status": STATUS_UNAVAILABLE,
            "error": code,
            "message": message,
            "required_margin": None,
            "final_margin": None,
            "instrument_count": 0,
            "timestamp": None,
            "expires_at": None,
            "rows": [],
        }
