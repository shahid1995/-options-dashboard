"""Upstox-specific mappings (Phase 6.5.0.2).

EVERY Upstox-specific concept lives here or in ``adapter.py`` — instrument
keys, transaction types, product codes, V3 order field names, chain payload
field names, order status strings. Nothing in this module is imported by
domain/application code except through the adapter boundary (compat
re-exports in the pre-existing broker services are documented there).

Pure functions only: no HTTP, no side effects, deterministic.
"""

from __future__ import annotations

from app.brokers.domain.enums import (
    ExecutionPolicy,
    InstrumentType,
    OptionType,
    OrderStatus,
    OrderType,
    Product,
    Segment,
    Side,
    Validity,
)
from app.brokers.domain.errors import BrokerError, BrokerErrorCode
from app.brokers.domain.models import BrokerOrderRequest, BrokerOrderResult, InstrumentIdentity

# ---- Instrument master (canonical identity + Upstox keys) --------------------
#
# The platform's canonical symbol → identity + Upstox instrument_key. The
# Upstox key is a BROKER mapping and lives only here (and in the adapter);
# it is never the platform's universal instrument ID.
UPSTOX_INSTRUMENTS: dict[str, dict] = {
    "NIFTY": {
        "exchange": "NSE",
        "segment": Segment.INDEX_DERIVATIVES.value,
        "underlying": "NIFTY",
        "instrument_type": InstrumentType.INDEX.value,
        "broker_instrument_id": "NSE_INDEX|Nifty 50",
    },
    "BANKNIFTY": {
        "exchange": "NSE",
        "segment": Segment.INDEX_DERIVATIVES.value,
        "underlying": "BANKNIFTY",
        "instrument_type": InstrumentType.INDEX.value,
        "broker_instrument_id": "NSE_INDEX|Nifty Bank",
    },
    # Note: Upstox uses older index names for these two ("Nifty Fin
    # Service", "NIFTY MID SELECT"), not the current official NSE names.
    "FINNIFTY": {
        "exchange": "NSE",
        "segment": Segment.INDEX_DERIVATIVES.value,
        "underlying": "FINNIFTY",
        "instrument_type": InstrumentType.INDEX.value,
        "broker_instrument_id": "NSE_INDEX|Nifty Fin Service",
    },
    "MIDCPNIFTY": {
        "exchange": "NSE",
        "segment": Segment.INDEX_DERIVATIVES.value,
        "underlying": "MIDCPNIFTY",
        "instrument_type": InstrumentType.INDEX.value,
        "broker_instrument_id": "NSE_INDEX|NIFTY MID SELECT",
    },
    "NIFTYNXT50": {
        "exchange": "NSE",
        "segment": Segment.INDEX_DERIVATIVES.value,
        "underlying": "NIFTYNXT50",
        "instrument_type": InstrumentType.INDEX.value,
        "broker_instrument_id": "NSE_INDEX|Nifty Next 50",
    },
    "SENSEX": {
        "exchange": "BSE",
        "segment": Segment.INDEX_DERIVATIVES.value,
        "underlying": "SENSEX",
        "instrument_type": InstrumentType.INDEX.value,
        "broker_instrument_id": "BSE_INDEX|SENSEX",
    },
    "BANKEX": {
        "exchange": "BSE",
        "segment": Segment.INDEX_DERIVATIVES.value,
        "underlying": "BANKEX",
        "instrument_type": InstrumentType.INDEX.value,
        "broker_instrument_id": "BSE_INDEX|BANKEX",
    },
    "SENSEX50": {
        "exchange": "BSE",
        "segment": Segment.INDEX_DERIVATIVES.value,
        "underlying": "SENSEX50",
        "instrument_type": InstrumentType.INDEX.value,
        "broker_instrument_id": "BSE_INDEX|SENSEX50",
    },
}

# symbol → Upstox instrument_key (kept under this exact name for the
# pre-existing chain router compatibility re-export).
UPSTOX_INSTRUMENT_KEYS: dict[str, str] = {
    symbol: info["broker_instrument_id"] for symbol, info in UPSTOX_INSTRUMENTS.items()
}

# Margin basket size limit for the Upstox charges/margin endpoint.
UPSTOX_MAX_MARGIN_INSTRUMENTS = 20

# The paper engine simulates HELD positions (no intraday square-off), so F&O
# margin requests use the delivery product. Kept here, broker-side.
UPSTOX_PRODUCT_DEFAULT = "D"


def resolve_instrument_identity(symbol: str) -> InstrumentIdentity:
    """Canonical identity for a known platform symbol (pure lookup).

    Raises BrokerError(INVALID_INSTRUMENT) for unknown symbols. The
    returned identity is the UNDERLYING/index level: expiry/strike/option
    type are filled by callers when a concrete contract is resolved.
    lot_size/tick_size stay None when the platform has no authoritative
    value — never fabricated.
    """
    info = UPSTOX_INSTRUMENTS.get((symbol or "").upper())
    if info is None:
        raise BrokerError(
            BrokerErrorCode.INVALID_INSTRUMENT,
            f"Unknown symbol '{symbol}' — no broker mapping exists.",
        )
    return InstrumentIdentity(
        exchange=info["exchange"],
        segment=info["segment"],
        underlying=info["underlying"],
        symbol=(symbol or "").upper(),
        instrument_type=info["instrument_type"],
    )


def broker_key_for(symbol: str) -> str:
    """Upstox instrument_key for a symbol (raises INVALID_INSTRUMENT when
    unknown). Adapter-internal — never call from domain code."""
    identity = resolve_instrument_identity(symbol)
    return UPSTOX_INSTRUMENT_KEYS[identity.symbol]


# ---- Option-type / side / order-type / validity / product / status maps -------


def option_type_to_domain(option_type) -> OptionType | None:
    """Map a platform/internal option type (call|put, lower or upper, or
    CE/PE) to the canonical CALL | PUT. None/unknown → None (never guessed)."""
    if option_type is None:
        return None
    value = str(getattr(option_type, "value", option_type)).strip().upper()
    if value in ("CALL", "CE", "C"):
        return OptionType.CALL
    if value in ("PUT", "PE", "P"):
        return OptionType.PUT
    return None


def option_type_to_upstox(option_type: str | OptionType | None) -> str | None:
    """Canonical CALL|PUT → the Upstox chain side key (``call`` / ``put``)."""
    mapped = option_type_to_domain(option_type)
    if mapped is None:
        return None
    return "call" if mapped is OptionType.CALL else "put"


def side_to_upstox(side: Side | str) -> str:
    """Canonical BUY/SELL → Upstox ``transaction_type`` (BUY/SELL)."""
    value = Side(side)
    return "BUY" if value is Side.BUY else "SELL"


def order_type_to_upstox(order_type: OrderType | str) -> str:
    """Canonical order type → Upstox V3 ``order_type`` value."""
    value = OrderType(order_type)
    return {
        OrderType.MARKET: "MARKET",
        OrderType.LIMIT: "LIMIT",
        OrderType.STOP_LOSS: "SL",
        OrderType.STOP_LOSS_MARKET: "SL-M",
    }[value]


def validity_to_upstox(validity: Validity | str) -> str:
    """Canonical validity → Upstox V3 ``validity`` (DAY | IOC)."""
    value = Validity(validity)
    return "DAY" if value is Validity.DAY else "IOC"


def product_to_upstox(product: Product | str | None) -> str:
    """Canonical product → Upstox product code (I | D | CO | MTF)."""
    if product is None:
        return UPSTOX_PRODUCT_DEFAULT
    value = Product(product)
    return {
        Product.INTRADAY: "I",
        Product.DELIVERY: "D",
        Product.CO: "CO",
        Product.MTF: "MTF",
    }[value]


# Upstox V3 order status strings → canonical lifecycle.
UPSTOX_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "complete": OrderStatus.FILLED,
    "filled": OrderStatus.FILLED,
    "pending": OrderStatus.PENDING,
    "trigger_pending": OrderStatus.PENDING,
    "open": OrderStatus.OPEN,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "partial_fill": OrderStatus.PARTIALLY_FILLED,
    "cancelled": OrderStatus.CANCELLED,
    "canceled": OrderStatus.CANCELLED,
    "rejected": OrderStatus.REJECTED,
    "expired": OrderStatus.EXPIRED,
}


def upstox_status_to_domain(status: str | None) -> OrderStatus:
    """Map an Upstox order status string to the canonical lifecycle.
    Unknown/missing → UNKNOWN (never guessed)."""
    if not status:
        return OrderStatus.UNKNOWN
    return UPSTOX_ORDER_STATUS_MAP.get(str(status).strip().lower(), OrderStatus.UNKNOWN)


# ---- Quantity conversion -------------------------------------------------------


def lots_to_contracts(quantity_lots: int, lot_size: int) -> int:
    """Platform LOTS → broker contract quantity (lots × lot_size).

    Upstox order/margin APIs expect contract units: 1 lot of NIFTY
    (lot_size 65) → 65 contracts. Never pass lots directly to the broker.
    """
    return int(quantity_lots) * int(lot_size)


# ---- Margin request/response payloads (moved from broker_margin service) ------


def build_margin_request_instruments(
    instruments: list[dict], product: str = UPSTOX_PRODUCT_DEFAULT
) -> list[dict]:
    """Build the ``POST /v2/charges/margin`` payload instruments.

    Every instrument carries the resolved Upstox key, the contract quantity
    (lots → contracts), ``transaction_type`` and the product. The full
    multi-leg strategy set goes in ONE request.
    """
    return [
        {
            "instrument_key": inst["instrument_key"],
            "quantity": lots_to_contracts(inst["quantity"], inst["lot_size"]),
            "transaction_type": "BUY" if inst["action"] == "buy" else "SELL",
            "product": product,
        }
        for inst in instruments
    ]


def map_funds_payload(data: dict | None) -> dict:
    """Map the V3 funds response (``data`` object) to the capital contract.

    Keeps broker terminology: available_to_trade, cash available, margin
    used, SPAN+exposure, premium present, pledge available. Missing fields
    stay ``None`` — never fabricated 0. The full raw payload is preserved in
    ``raw`` so future phases never lose broker fields.
    """
    data = data or {}
    available = data.get("available_to_trade") or {}
    cash = available.get("cash_available_to_trade") or {}
    margin_used = cash.get("margin_used") or {}
    pledge = available.get("pledge_available_to_trade") or {}
    pledge_margin_used = pledge.get("margin_used") or {}
    pledge_from = pledge.get("margin_from_pledge") or {}
    unavailable = data.get("unavailable_to_trade") or {}
    unsettled = (unavailable.get("cash_unavailable_to_trade") or {}).get("unsettled_profit") or {}
    delivery = margin_used.get("delivery_margin") or {}
    return {
        "available_to_trade": available.get("total"),
        "cash_available_to_trade": cash.get("total"),
        "margin_used": margin_used.get("total"),
        "span_exposure": margin_used.get("span_exposure"),
        "cash_margin_var_elm": margin_used.get("cash_margin_var_elm"),
        "premium_present": margin_used.get("premium_present"),
        "delivery_margin": delivery.get("total"),
        "pledge_available_to_trade": pledge.get("total"),
        "margin_from_pledge": pledge_from.get("total"),
        "pledge_margin_used": pledge_margin_used.get("total"),
        "unsettled_profit": unsettled.get("todays_profit"),
        "raw": data,
    }


def map_margin_payload(data: dict | None) -> dict:
    """Map the V2 margin response to the capital contract.

    ``required_margin`` (the broker's whole-request figure) is authoritative
    and preserved as-is — the platform never sums SPAN + exposure itself.
    Per-instrument rows are kept separately in ``rows``.
    """
    data = data or {}
    inner = data.get("data") or {}
    rows = inner.get("margins") or []
    return {
        "required_margin": inner.get("required_margin"),
        "final_margin": inner.get("final_margin"),
        "rows": rows,
        "raw": data,
    }


# ---- Option chain canonicalization (moved from the chains router) -------------


def transform_chain(symbol: str, expiry_date: str, raw: dict) -> dict:
    """Canonicalize a raw Upstox chain payload into platform chain rows.

    Reads the Upstox payload shape (``call_options`` / ``put_options`` /
    ``market_data`` / ``option_greeks``) HERE — inside the adapter — and
    returns the canonical chain contract consumed by the app and UI:

        {"symbol", "expiry_date", "underlying_spot_price", "chain": [...]}
    """
    rows = []
    underlying_spot = None

    for item in raw.get("data", []):
        strike = item.get("strike_price")
        if underlying_spot is None:
            underlying_spot = item.get("underlying_spot_price")

        def leg(side_key):
            side = item.get(side_key) or {}
            market = side.get("market_data") or {}
            greeks = side.get("option_greeks") or {}

            oi = market.get("oi")
            prev_oi = market.get("prev_oi")
            chg_oi = (oi - prev_oi) if (oi is not None and prev_oi is not None) else None

            return {
                "ltp": market.get("ltp"),
                "oi": oi,
                "chg_oi": chg_oi,
                "volume": market.get("volume"),
                "iv": greeks.get("iv"),
                "delta": greeks.get("delta"),
                "theta": greeks.get("theta"),
                "gamma": greeks.get("gamma"),
                "vega": greeks.get("vega"),
                "pop": greeks.get("pop"),
            }

        rows.append({
            "strike": strike,
            "call": leg("call_options"),
            "put": leg("put_options"),
        })

    rows.sort(key=lambda r: r["strike"])

    return {
        "symbol": symbol,
        "expiry_date": expiry_date,
        "underlying_spot_price": underlying_spot,
        "chain": rows,
    }


def contracts_from_payload(raw: dict) -> list[str]:
    """Extract sorted, deduplicated expiries from the option/contract payload."""
    return sorted({c["expiry"] for c in raw.get("data", []) if "expiry" in c})


# ---- V3 order request payload (prepared, NOT wired) ---------------------------


def build_order_request_payload(request: BrokerOrderRequest) -> dict:
    """Build the Upstox V3 place-order payload from a canonical request.

    PURE preparation for the future execution phase — the adapter does NOT
    submit it in this phase. All Upstox field names (``instrument_token``,
    ``transaction_type``, ``is_amo``, ...) appear only here.

    Raises BrokerError(INVALID_QUANTITY) when the instrument identity lacks
    the lot size needed for the lots → contracts conversion.
    """
    if request.instrument.lot_size is None:
        raise BrokerError(
            BrokerErrorCode.INVALID_QUANTITY,
            "Instrument identity has no lot size — cannot convert lots to broker contracts.",
        )
    broker_key = broker_key_for(request.instrument.symbol)
    payload = {
        "instrument_token": broker_key,
        "transaction_type": side_to_upstox(request.side),
        "quantity": lots_to_contracts(request.quantity, request.instrument.lot_size),
        "order_type": order_type_to_upstox(request.order_type),
        "product": product_to_upstox(request.product),
        "validity": validity_to_upstox(request.validity),
        "is_amo": bool(request.after_market),
    }
    if request.price is not None:
        payload["price"] = request.price
    if request.trigger_price is not None:
        payload["trigger_price"] = request.trigger_price
    if request.disclosed_quantity is not None:
        payload["disclosed_quantity"] = request.disclosed_quantity
    if request.market_protection:
        payload["market_protection"] = 1
    if request.client_order_tag:
        payload["tag"] = request.client_order_tag
    # The canonical execution policy is never sent to the broker verbatim;
    # slicing stays a platform-side concern represented by capability +
    # result shape (multiple broker_order_ids), never a payload field.
    return payload


# ---- V3 order response mapping (prepared, NOT wired) --------------------------


def map_order_result(payload: dict | None, broker: str = "UPSTOX") -> BrokerOrderResult:
    """Map an Upstox V3 order response to the canonical order result.

    Supports ONE logical request producing MULTIPLE broker order ids
    (broker-native slicing): a single ``order_id`` string, or a list of
    order objects / ids, or ``data`` shaped either way — all normalize into
    ``broker_order_ids``. Status strings map through
    ``upstox_status_to_domain``; unknown stays UNKNOWN.
    """
    payload = payload or {}
    data = payload.get("data")
    if isinstance(data, dict):
        ids = _extract_order_ids(data.get("order_id"))
        status = upstox_status_to_domain(data.get("status"))
        message = data.get("message")
    elif isinstance(data, list):
        ids = tuple(
            order_id
            for item in data
            for order_id in _extract_order_ids(
                item.get("order_id") if isinstance(item, dict) else item
            )
        )
        status = OrderStatus.UNKNOWN
        message = None
    else:
        ids = _extract_order_ids(payload.get("order_id"))
        status = upstox_status_to_domain(payload.get("status"))
        message = payload.get("message")

    return BrokerOrderResult(
        broker=broker,
        broker_order_ids=ids,
        status=status,
        client_order_id=data.get("client_order_id") if isinstance(data, dict) else payload.get("client_order_id"),
        message=message,
        accepted_at=data.get("timestamp") if isinstance(data, dict) else None,
    )


def _extract_order_ids(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value if v is not None)
    return (str(value),)
