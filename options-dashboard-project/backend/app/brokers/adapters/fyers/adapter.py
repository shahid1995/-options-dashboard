"""FYERS adapter — Adapter #2 behind the broker gateway.

Wraps the raw FYERS HTTP client (``app.services.fyers`` — base URLs,
OAuth, appIdHash, tokens, FYERS symbols, response formats and
``FyersError`` all stay HERE / in the raw client) and exposes the
broker-neutral :class:`BrokerAdapter` contract to the application.

Boundary rules enforced here (mirroring the Upstox adapter):

- ``FyersError`` never escapes this adapter: every failure is mapped to a
  canonical :class:`BrokerError` (audit §10 error map).
- Broker-specific field names never appear in canonical method returns.
- Tokens / appIdHash / secrets are never logged, never repr'd, never
  returned in results.
- Identity: ``extract_account_id`` / ``extract_customer_identity`` return
  the FYERS **customer Login ID** — NEVER the API App ID, the OAuth
  ``client_id``, a secret, an email or a PAN. The field mapping is
  isolated in ``app.brokers.adapters.fyers.profile`` and is
  fail-closed until the live staging profile confirms it.
- Trading operations are capability-gated: a data-only / legacy FYERS
  app never reaches order placement, regardless of HTTP connectivity
  (Phase 11 gate). A compliant ``-200`` app reports SUPPORTED but the
  order family remains PREPARED-not-wired this phase, like Upstox.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.brokers.adapters.fyers import mapper
from app.brokers.adapters.fyers.profile import (
    extract_account_id,
    extract_customer_identity,
)
from app.brokers.domain.capabilities import (
    BrokerCapabilities,
    BrokerCapability,
    CapabilityState,
)
from app.brokers.domain.enums import BROKER_ID_UPSTOX, BrokerId
from app.brokers.domain.errors import BrokerError, BrokerErrorCode
from app.brokers.domain.models import (
    BrokerConnectionContext,
    BrokerInstrumentMapping,
    BrokerOrderRequest,
    BrokerOrderResult,
    InstrumentIdentity,
)
from app.market_data.contracts import QuoteObservation
from app.services import fyers
from app.services.fyers import FyersError

logger = logging.getLogger(__name__)

NOT_WIRED_MESSAGE = (
    "FYERS {operation} is prepared but NOT wired — live broker execution "
    "is not enabled in this phase."
)

# Canonical platform symbols supported by the FYERS instrument master
# (subset of the Upstox master: FYERS index naming applies).
FYERS_INSTRUMENTS = mapper.FYERS_INSTRUMENTS


class FyersAdapter:
    """Canonical broker adapter for FYERS (Adapter #2)."""

    broker_id: str = BrokerId.FYERS.value
    broker_name: str = "FYERS"

    # ---- construction -----------------------------------------------------

    def __init__(
        self,
        access_token: str | None = None,
        *,
        api_key: str | None = None,           # BYOB: FYERS API App ID
        api_secret: str | None = None,        # BYOB: FYERS Secret ID
        redirect_uri: str | None = None,
        app_type: str | None = None,          # "100" / "-100" / "200" / "-200"
        connection_context: BrokerConnectionContext | None = None,
        login_url_builder=None,
        token_exchanger=None,
        profile_fetcher=None,
        funds_fetcher=None,
        positions_fetcher=None,
        holdings_fetcher=None,
        orders_fetcher=None,
        tradebook_fetcher=None,
        chain_fetcher=None,
        quotes_fetcher=None,
        now=None,
    ):
        self._access_token = access_token
        self._app_id = api_key           # API App ID — never customer identity
        self._secret_id = api_secret     # Secret ID — never logged
        self._redirect_uri = redirect_uri
        self._app_type = app_type
        self._connection_context = connection_context
        # Fetcher defaults resolve at CALL time via the module attribute so
        # runtime monkeypatching (tests, tooling) always intercepts.
        self._login_url_builder = login_url_builder
        self._token_exchanger = token_exchanger
        self._profile_fetcher = profile_fetcher
        self._funds_fetcher = funds_fetcher
        self._positions_fetcher = positions_fetcher
        self._holdings_fetcher = holdings_fetcher
        self._orders_fetcher = orders_fetcher
        self._tradebook_fetcher = tradebook_fetcher
        self._chain_fetcher = chain_fetcher
        self._quotes_fetcher = quotes_fetcher
        self._now = now or (lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:  # never include the token or app secret
        return f"FyersAdapter(broker={self.broker_name})"

    def get_connection_context(self) -> BrokerConnectionContext | None:
        return self._connection_context

    # ---- error boundary ---------------------------------------------------

    @staticmethod
    def _map_error(exc: FyersError) -> BrokerError:
        """Map a FYERS HTTP failure to the canonical taxonomy.

        The upstream message is preserved (broker diagnostics, not a
        credential); the canonical code is what the app branches on.
        FYERS reports failures on HTTP 200 too (``s`` = ``error``);
        payload-level checks raise via :meth:`_error_from_payload`.
        """
        status = exc.status_code
        if status in (401, 403):
            return BrokerError(
                BrokerErrorCode.TOKEN_EXPIRED,
                "FYERS session expired or unauthorized.",
                status_code=status,
            )
        if status == 429:
            return BrokerError(
                BrokerErrorCode.RATE_LIMITED,
                "FYERS rate limit reached — try again shortly.",
                status_code=status,
            )
        if status == 502 and str(exc.message).startswith("Could not reach FYERS"):
            return BrokerError(
                BrokerErrorCode.NETWORK_ERROR,
                f"Could not reach FYERS: {exc.message}",
                status_code=status,
            )
        return BrokerError(
            BrokerErrorCode.UPSTREAM_ERROR,
            exc.message,
            status_code=status,
        )

    @staticmethod
    def _error_from_payload(body: dict | None, context: str) -> BrokerError:
        """Map a FYERS payload-level failure (``s``: ``error``) to the
        canonical taxonomy using the audit's FYERS → StrikeNova error map.

        Matching is on the SAFE message text FYERS returns (never a
        credential); unmatched failures stay UPSTREAM_ERROR.
        """
        body = body if isinstance(body, dict) else {}
        message = str(body.get("message") or "").strip()
        code = str(body.get("code") or "").strip()
        text = f"{code} {message}".lower()

        def _fail(canonical: BrokerErrorCode, human: str) -> BrokerError:
            return BrokerError(canonical, human, metadata={"fyers_code": code or None})

        if "token" in text and ("expire" in text or "invalid" in text or "expired" in text):
            return _fail(BrokerErrorCode.TOKEN_EXPIRED, "FYERS session expired or invalid — reconnect your broker.")
        if "auth" in text or "app_id" in text and "hash" in text or "appidhash" in text:
            return _fail(BrokerErrorCode.AUTH_REQUIRED, "FYERS rejected the app credentials — check your app id/secret.")
        if "permission" in text or "not allowed" in text or "access denied" in text:
            return _fail(BrokerErrorCode.ACCOUNT_RESTRICTED, "FYERS denied this operation for your account/app.")
        if "static ip" in text or "ip" in text and "restrict" in text:
            return _fail(BrokerErrorCode.STATIC_IP_REQUIRED, "FYERS requires a registered static IP for this operation.")
        if "unsupported" in text or "not supported" in text or "not available" in text and "api" in text:
            return _fail(BrokerErrorCode.CAPABILITY_UNSUPPORTED, "FYERS API does not support this operation for your app.")
        if "invalid" in text and ("symbol" in text or "instrument" in text):
            return _fail(BrokerErrorCode.INVALID_INSTRUMENT, "FYERS rejected the instrument symbol.")
        if "invalid" in text and "qty" in text:
            return _fail(BrokerErrorCode.INVALID_QUANTITY, "FYERS rejected the order quantity.")
        if "invalid" in text and "price" in text:
            return _fail(BrokerErrorCode.INVALID_PRICE, "FYERS rejected the order price.")
        if "margin" in text and ("short" in text or "insufficient" in text):
            return _fail(BrokerErrorCode.ORDER_REJECTED, "FYERS rejected the order — insufficient margin.")
        if "order" in text and "not found" in text:
            return _fail(BrokerErrorCode.ORDER_NOT_FOUND, "FYERS has no such open order.")
        if "final" in text or "modify" in text and "reject" in text:
            return _fail(BrokerErrorCode.ORDER_ALREADY_FINAL, "FYERS order is already final and cannot be modified.")
        return BrokerError(
            BrokerErrorCode.UPSTREAM_ERROR,
            message or f"FYERS {context} failed.",
            metadata={"fyers_code": code or None},
        )

    @staticmethod
    def _assert_payload_ok(body: dict | None, context: str) -> None:
        """Raise the canonical error when a FYERS payload reports failure.

        FYERS signals payload-level failures via ``s``: ``"error"`` even
        on HTTP 200; silent success-without-data shapes are treated
        conservatively per endpoint (empty lists are valid data).
        """
        if isinstance(body, dict) and str(body.get("s", "")).lower() == "error":
            raise FyersAdapter._error_from_payload(body, context)

    # ---- low-level fetch helpers (token + fetcher resolution) -------------

    def _require_session(self) -> tuple[str, str]:
        """Require an access token AND the app id (REST auth needs both)."""
        if not self._access_token or not self._app_id:
            raise BrokerError(
                BrokerErrorCode.AUTH_REQUIRED,
                "Broker login required — authenticate with FYERS first.",
            )
        return self._access_token, self._app_id

    async def _fetch_profile(self) -> dict:
        fetcher = self._profile_fetcher or fyers.get_profile
        return await fetcher(*self._require_session())

    async def _fetch_funds(self) -> dict:
        fetcher = self._funds_fetcher or fyers.get_funds
        return await fetcher(*self._require_session())

    async def _fetch_positions(self) -> dict:
        fetcher = self._positions_fetcher or fyers.get_positions
        return await fetcher(*self._require_session())

    async def _fetch_holdings(self) -> dict:
        fetcher = self._holdings_fetcher or fyers.get_holdings
        return await fetcher(*self._require_session())

    async def _fetch_orders(self) -> dict:
        fetcher = self._orders_fetcher or fyers.get_orders
        return await fetcher(*self._require_session())

    async def _fetch_tradebook(self) -> dict:
        fetcher = self._tradebook_fetcher or fyers.get_tradebook
        return await fetcher(*self._require_session())

    async def _fetch_raw_chain(self, fyers_symbol: str, expiry_date: str) -> dict:
        fetcher = self._chain_fetcher or fyers.get_option_chain
        token, app_id = self._require_session()
        return await fetcher(token, app_id, fyers_symbol, expiry_date)

    async def _fetch_quotes(self, symbols: list[str]) -> dict:
        fetcher = self._quotes_fetcher or fyers.get_quotes
        token, app_id = self._require_session()
        return await fetcher(token, app_id, symbols)

    # ---- AUTHENTICATION ---------------------------------------------------

    def get_authorization_url(self, state: str) -> str:
        """FYERS step 1 — generate-authcode URL (client_id = API App ID)."""
        if self._login_url_builder:
            return self._login_url_builder(state)
        return fyers.get_login_url(
            state,
            app_id=self._app_id or "",
            redirect_uri=self._redirect_uri or "",
        )

    async def exchange_authorization_code(self, code: str) -> str:
        """FYERS step 2 — validate-authcode → access token.

        The FYERS response also carries a refresh token. The shared
        contract returns only the access token (mirror of Upstox); the
        refresh token is NOT discarded — the auth callback persists it
        encrypted via ``token_store.persist_fyers_refresh_token``. Until
        that plumbing runs, the value is held on the adapter instance
        (never logged) for the callback to read.
        """
        if not self._app_id or not self._secret_id:
            raise BrokerError(
                BrokerErrorCode.AUTH_REQUIRED,
                "FYERS app id and secret are required for the authorization-code exchange.",
            )
        if self._token_exchanger:
            try:
                body = await self._token_exchanger(code)
            except FyersError as exc:
                raise self._map_error(exc) from exc
        else:
            try:
                body = await fyers.exchange_code_for_token(self._app_id, self._secret_id, code)
            except FyersError as exc:
                raise self._map_error(exc) from exc
        self._assert_payload_ok(body, "authorization-code exchange")
        access_token = (body or {}).get("access_token")
        if not access_token:
            raise FyersError(502, "FYERS token response did not include an access token")
        self._refresh_token = body.get("refresh_token")  # held, never logged
        return access_token

    def disconnect(self) -> None:
        """Release this adapter's token references."""
        self._access_token = None
        self._refresh_token = None

    # ---- BROKER-SPECIFIC PROFILE EXTRACTION (AD-6) ------------------------

    @staticmethod
    def extract_account_id(profile: dict) -> str | None:
        """Extract the FYERS customer Login ID from a profile response.

        Broker-specific logic lives in the adapter layer, never in
        identity.py (AD-6). Returns the customer Login ID — never the
        API App ID, secret, email or PAN — or ``None`` when the profile
        carries no confirmable identity field (fail-closed).
        """
        return extract_account_id(profile)

    def extract_customer_identity(self, profile: dict) -> str:
        """Fail-closed customer identity extraction (callback path)."""
        return extract_customer_identity(profile)

    # ---- ACCOUNT ----------------------------------------------------------

    async def get_profile(self) -> dict:
        try:
            body = await self._fetch_profile()
        except FyersError as exc:
            raise self._map_error(exc) from exc
        self._assert_payload_ok(body, "profile")
        return body

    async def get_funds(self) -> dict:
        """Canonical FYERS funds payload (see ``mapper.map_funds_payload``)."""
        try:
            body = await self._fetch_funds()
        except FyersError as exc:
            raise self._map_error(exc) from exc
        self._assert_payload_ok(body, "funds")
        return mapper.map_funds_payload(body)

    async def get_margin(self, instruments: list[dict]) -> dict:
        raise BrokerError(
            BrokerErrorCode.CAPABILITY_UNSUPPORTED,
            "FYERS multi-leg margin is not supported — no FYERS margin endpoint is mapped.",
        )

    # ---- CAPABILITIES -----------------------------------------------------

    def get_capabilities(self, profile: dict | None = None) -> BrokerCapabilities:
        """Canonical capability matrix (see ``mapper.fyers_capability_matrix``).

        App-type aware: trading capabilities depend on the compliant
        ``-200`` app generation, not on session state. When the profile
        is available and reports an ``appattribution``/app-type signal,
        it refines the matrix; session awareness follows the shared
        domain model (no session → AUTH_REQUIRED for data capabilities).
        """
        profile = profile if isinstance(profile, dict) else None
        profile_data = profile.get("data") if profile else None
        profile_data = profile_data if isinstance(profile_data, dict) else {}
        app_type = self._app_type or profile_data.get("appattribution") or profile_data.get("app_type")
        items = [
            BrokerCapability(name, state, wired, detail)
            for name, state, wired, detail in mapper.fyers_capability_matrix(app_type)
        ]
        capabilities = BrokerCapabilities(items)
        return capabilities.with_session_state(
            session_active=self._access_token is not None, profile=profile
        )

    def trading_available(self, profile: dict | None = None) -> bool:
        """True only for a compliant trading-capable ``-200`` app.

        The Phase-11 order gate: a successful HTTP connection NEVER
        implies trading capability. Data-only / legacy (``-100``) apps
        and unknown app types are not trading-capable.
        """
        profile_data = profile.get("data") if isinstance(profile, dict) else None
        profile_data = profile_data if isinstance(profile_data, dict) else {}
        app_type = self._app_type or profile_data.get("appattribution") or profile_data.get("app_type")
        return mapper.orders_capable(app_type)

    # ---- INSTRUMENTS ------------------------------------------------------

    def resolve_instrument(self, symbol: str) -> InstrumentIdentity:
        return mapper.resolve_instrument_identity(symbol)

    def search_instruments(self, query: str) -> list[BrokerInstrumentMapping]:
        """Search the FYERS instrument master (canonical identities + FYERS symbols)."""
        q = (query or "").strip().upper()
        if not q:
            return []
        results = []
        for symbol, info in mapper.FYERS_INSTRUMENTS.items():
            if q in symbol or q in info["underlying"].upper():
                identity = mapper.resolve_instrument_identity(symbol)
                results.append(
                    BrokerInstrumentMapping(
                        broker=self.broker_name,
                        broker_instrument_id=info["broker_instrument_id"],
                        identity=identity,
                    )
                )
        return results

    async def get_option_contracts(self, symbol: str) -> dict:
        """Canonical ``{"symbol": ..., "expiries": [...]}`` contract."""
        identity = self.resolve_instrument(symbol)
        fyers_symbol = mapper.fyers_symbol_for(identity)
        try:
            raw = await self._fetch_raw_chain(fyers_symbol, "")
        except FyersError as exc:
            raise self._map_error(exc) from exc
        self._assert_payload_ok(raw, "option contracts")
        return {
            "symbol": identity.symbol,
            "expiries": mapper.contracts_from_payload(raw),
        }

    # ---- MARKET DATA ------------------------------------------------------

    async def get_market_status(self, exchange: str) -> dict:
        raise BrokerError(
            BrokerErrorCode.CAPABILITY_UNSUPPORTED,
            "FYERS market status is not mapped — no FYERS v3 market-status endpoint.",
        )

    async def get_option_chain(self, symbol: str, expiry_date: str) -> dict:
        """Canonical option chain (see ``mapper.fyers_chain_to_observation``)."""
        identity = self.resolve_instrument(symbol)
        fyers_symbol = mapper.fyers_symbol_for(identity)
        try:
            raw = await self._fetch_raw_chain(fyers_symbol, expiry_date)
        except FyersError as exc:
            raise self._map_error(exc) from exc
        self._assert_payload_ok(raw, "option chain")
        observation = mapper.fyers_chain_to_observation(
            identity.symbol, expiry_date, raw, received_at=self._now()
        )
        return {
            "symbol": observation.symbol,
            "expiry_date": observation.expiry_date,
            "underlying_spot_price": observation.underlying_spot_price,
            "chain": [
                {
                    "strike": row.strike,
                    "call": {"ltp": row.call.ltp, "oi": row.call.oi, "volume": row.call.volume}
                    if row.call
                    else None,
                    "put": {"ltp": row.put.ltp, "oi": row.put.oi, "volume": row.put.volume}
                    if row.put
                    else None,
                }
                for row in observation.chain
            ],
        }

    def _quote_fyers_symbol(self, instrument: InstrumentIdentity) -> str:
        """Resolve the FYERS symbol needed for a market quote.

        Only underlying/index identities carry a static FYERS symbol. A
        concrete option/future contract's symbol is only discoverable
        from chain data, so quoting it directly from its canonical
        identity is impossible here — canonical error, never a
        fabricated symbol.
        """
        if instrument.is_concrete_contract:
            raise BrokerError(
                BrokerErrorCode.INVALID_INSTRUMENT,
                "Quote requires a chain-resolved broker symbol; concrete contract "
                "identities cannot be quoted directly.",
            )
        return mapper.fyers_symbol_for(instrument)

    def _extract_quote_payload(self, raw: dict, fyers_symbol: str) -> dict:
        """Locate one instrument's quote payload inside the response body.

        The FYERS ``data.d`` map is keyed by the requested FYERS symbol;
        the single-entry case is accepted as a fallback. No data →
        canonical INVALID_MARKET_DATA.
        """
        data = raw.get("data") if isinstance(raw, dict) else None
        inner = data.get("d") if isinstance(data, dict) else None
        if not isinstance(inner, dict) or not inner:
            raise BrokerError(
                BrokerErrorCode.INVALID_MARKET_DATA,
                "FYERS quote response contained no data payload.",
            )
        if fyers_symbol in inner:
            payload = inner[fyers_symbol]
        elif len(inner) == 1:
            payload = next(iter(inner.values()))
        else:
            raise BrokerError(
                BrokerErrorCode.INVALID_MARKET_DATA,
                f"FYERS quote unavailable for {fyers_symbol}.",
            )
        if not isinstance(payload, dict):
            raise BrokerError(
                BrokerErrorCode.INVALID_MARKET_DATA,
                "FYERS quote payload was malformed.",
            )
        return payload

    async def get_quote(self, instrument: InstrumentIdentity) -> QuoteObservation:
        """Single canonical market quote (canonical Day-9 contract)."""
        fyers_symbol = self._quote_fyers_symbol(instrument)
        try:
            raw = await self._fetch_quotes([fyers_symbol])
        except FyersError as exc:
            raise self._map_error(exc) from exc
        self._assert_payload_ok(raw, "quotes")
        payload = self._extract_quote_payload(raw, fyers_symbol)
        normalized = mapper.instrument_identity_to_normalized(instrument)
        return mapper.fyers_quote_to_observation(payload, normalized, received_at=self._now())

    async def get_quotes(self, instruments: list[InstrumentIdentity]) -> list[QuoteObservation]:
        """Batch canonical market quotes, in request order."""
        symbols = [self._quote_fyers_symbol(inst) for inst in instruments]
        try:
            raw = await self._fetch_quotes(symbols)
        except FyersError as exc:
            raise self._map_error(exc) from exc
        self._assert_payload_ok(raw, "quotes")
        observations = []
        for instrument, fyers_symbol in zip(instruments, symbols):
            payload = self._extract_quote_payload(raw, fyers_symbol)
            normalized = mapper.instrument_identity_to_normalized(instrument)
            observations.append(
                mapper.fyers_quote_to_observation(payload, normalized, received_at=self._now())
            )
        return observations

    # ---- ORDERS (capability-gated; prepared, NOT wired) --------------------

    def _not_wired(self, operation: str) -> BrokerError:
        return BrokerError(
            BrokerErrorCode.CAPABILITY_UNSUPPORTED,
            NOT_WIRED_MESSAGE.format(operation=operation),
        )

    def _assert_trading_gate(self) -> None:
        """Phase-11 capability gate — BEFORE any order attempt.

        A data-only/legacy FYERS app can never place orders regardless
        of HTTP connectivity; the canonical error is
        STATIC_IP_REQUIRED-flavored per the audit map when the app is
        compliant but unconfigured, CAPABILITY_UNSUPPORTED otherwise.
        """
        if self.trading_available():
            return
        app_type = (self._app_type or "").strip().upper().replace("-", "")
        if app_type.endswith("100"):
            raise BrokerError(
                BrokerErrorCode.CAPABILITY_UNSUPPORTED,
                "FYERS app is data-only/legacy (-100) — order placement requires a "
                "compliant -200 app with activated trading, a static IP and "
                "order-placement permission.",
            )
        raise BrokerError(
            BrokerErrorCode.STATIC_IP_REQUIRED,
            "FYERS order placement requires a compliant -200 app with activated "
            "trading, a registered static IP and order-placement permission.",
        )

    def build_order_request_payload(self, request: BrokerOrderRequest) -> dict:
        """Build the FYERS place-order payload from a canonical request.

        PURE preparation for the future execution phase — never submitted
        here. FYERS field names (``symbol``, ``qty``, ``type``, ``side``,
        ``productType``, ``limitPrice``, ``stopPrice``, ``validity``,
        ``disclosedQty``) appear only here. Raises
        INVALID_QUANTITY when the identity lacks a lot size.
        """
        if request.instrument.lot_size is None:
            raise BrokerError(
                BrokerErrorCode.INVALID_QUANTITY,
                "Instrument identity has no lot size — cannot convert lots to broker contracts.",
            )
        payload: dict[str, Any] = {
            "symbol": mapper.fyers_symbol_for(request.instrument),
            "qty": int(request.quantity) * int(request.instrument.lot_size),
            "type": mapper.order_type_to_fyers(request.order_type),
            "side": mapper.side_to_fyers(request.side),
            "productType": mapper.product_to_fyers(request.product),
            "validity": mapper.validity_to_fyers(request.validity.value),
        }
        if request.order_type in (request.order_type.LIMIT, request.order_type.STOP_LOSS):
            if request.price is None:
                raise BrokerError(
                    BrokerErrorCode.INVALID_PRICE,
                    "LIMIT/SL orders require a price.",
                )
            payload["limitPrice"] = request.price
        if request.order_type in (request.order_type.STOP_LOSS, request.order_type.STOP_LOSS_MARKET):
            if request.trigger_price is None:
                raise BrokerError(
                    BrokerErrorCode.INVALID_PRICE,
                    "SL/SL-M orders require a trigger price.",
                )
            payload["stopPrice"] = request.trigger_price
        if request.disclosed_quantity is not None:
            payload["disclosedQty"] = int(request.disclosed_quantity) * int(request.instrument.lot_size)
        return payload

    def place_order(self, request: BrokerOrderRequest) -> BrokerOrderResult:
        self._assert_trading_gate()
        raise self._not_wired("order placement")

    def place_orders(self, requests: list[BrokerOrderRequest]) -> list[BrokerOrderResult]:
        self._assert_trading_gate()
        raise self._not_wired("multi-order placement")

    def modify_order(self, broker_order_id: str, request: BrokerOrderRequest) -> BrokerOrderResult:
        self._assert_trading_gate()
        raise self._not_wired("order modification")

    def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        self._assert_trading_gate()
        raise self._not_wired("order cancellation")

    def cancel_orders(self, broker_order_ids: list[str]) -> list[BrokerOrderResult]:
        self._assert_trading_gate()
        raise self._not_wired("multi-order cancellation")

    def get_order(self, broker_order_id: str) -> BrokerOrderResult:
        raise self._not_wired("order details")

    def get_orders(self) -> list[BrokerOrderResult]:
        raise self._not_wired("order book")

    def get_order_history(self, broker_order_id: str) -> list[BrokerOrderResult]:
        raise self._not_wired("order history")

    # ---- TRADES / PORTFOLIO -------------------------------------------------

    def get_trades(self) -> list[dict]:
        raise self._not_wired("trade history")

    def get_order_trades(self, broker_order_id: str) -> list[dict]:
        raise self._not_wired("order trades")

    def get_trade_history(self) -> list[dict]:
        raise self._not_wired("trade history")

    # ---- PORTFOLIO (wired: positions / holdings) -----------------------------

    async def get_positions(self) -> list[dict]:
        """Fetch current-day trading positions from FYERS.

        ``GET /api/v3/positions`` normalized via
        ``mapper.normalize_fyers_position`` — broker-neutral dict key
        set, quantity in broker contract units (NOT platform LOTS).
        """
        try:
            raw = await self._fetch_positions()
        except FyersError as exc:
            raise self._map_error(exc) from exc
        self._assert_payload_ok(raw, "positions")
        raw_list = raw.get("netPositions") if isinstance(raw, dict) else None
        raw_list = raw_list if isinstance(raw_list, list) else []
        return [
            pos
            for pos in (mapper.normalize_fyers_position(item) for item in raw_list)
            if pos
        ]

    async def get_holdings(self) -> list[dict]:
        """Fetch long-term holdings from FYERS (normalized)."""
        try:
            raw = await self._fetch_holdings()
        except FyersError as exc:
            raise self._map_error(exc) from exc
        self._assert_payload_ok(raw, "holdings")
        raw_list = raw.get("holdings") if isinstance(raw, dict) else None
        raw_list = raw_list if isinstance(raw_list, list) else []
        return [
            h
            for h in (mapper.normalize_fyers_holding(item) for item in raw_list)
            if h
        ]

    async def get_tradebook(self) -> list[dict]:
        """Fetch the FYERS tradebook (normalized, read-only diagnostics)."""
        try:
            raw = await self._fetch_tradebook()
        except FyersError as exc:
            raise self._map_error(exc) from exc
        self._assert_payload_ok(raw, "tradebook")
        raw_list = raw.get("tradeBook") if isinstance(raw, dict) else None
        raw_list = raw_list if isinstance(raw_list, list) else []
        return [
            t
            for t in (mapper.normalize_fyers_trade(item) for item in raw_list)
            if t
        ]

    # ---- STREAMING ----------------------------------------------------------

    def streaming_source_class(self):
        """The FYERS streaming bridge class (lazy import keeps the
        transport optional). Returns ``None`` when the transport module
        is unavailable — the platform falls back to HTTP polling."""
        from app.brokers.adapters.fyers.streaming_source import FyersStreamingSource

        return FyersStreamingSource


# Canonical re-export used by the capability-with-session-state contract.
BROKER_ID_FYERS = BrokerId.FYERS
