"""Provider-specific authorization renewal strategies (capability gated).

Brokers differ materially in what renewal they permit — the architecture
NEVER assumes a refresh token exists or may be used:

* UPSTOX — OAuth v2 access tokens last ~8:30 AM to next day ~3:30 AM IST
  and Upstox provides NO refresh token. Renewal == full re-OAuth by the
  user. ``can_refresh()`` is False, always.

* FYERS — the v3 flow issues an access token plus a refresh token valid
  ~15 days (documented; subject to change). HOWEVER:
    - the refresh flow is PIN-gated (requires the user's TOTP/PIN flow);
    - FYERS's April-2026 rules state continuous refresh-token sessions
      are NOT supported for trading.
  Automated/unattended refresh is therefore NOT implemented — renewal is
  user-driven re-authorization through the existing OAuth popup flow.
  We persist the refresh token encrypted when FYERS returns one (for a
  future, explicitly-approved, PIN-gated mechanism) but never use it
  silently. Collecting FYERS password/PIN/TOTP/OTP or automating browser
  credentials is FORBIDDEN.

Data-only vs trading: a ``-100`` (data-only) FYERS app NEVER gains
trading capability — no renewal path grants it; the capabilities()
matrix and the BrokerConnection trading_status stay honest.

Interface (conceptual contract, one strategy per broker):

    authorization_status()        # alias of broker_authorization.authorization_status
    can_refresh()                 # may this broker refresh unattended?
    refresh_authorization(db, authz)  # raises BrokerNotRefreshableError
    requires_reauthorization(authz, now)  # True → user must re-OAuth
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.services.broker_authorization import authorization_status

logger = logging.getLogger(__name__)


class BrokerNotRefreshableError(Exception):
    """The broker (or architecture policy) does not permit automated refresh.

    Raised by every refresh_authorization() implementation today: renewal
    is user-driven re-authorization for all current brokers.
    """


class BrokerRenewalStrategy:
    """Base strategy: refresh never permitted, reauthorization when expired."""

    broker_id: str = ""

    def authorization_status(self, authz, *, now: datetime | None = None) -> str:
        return authorization_status(authz, now=now)

    def can_refresh(self) -> bool:
        return False

    def refresh_authorization(self, db, authz) -> None:
        raise BrokerNotRefreshableError(
            f"{self.broker_id or 'broker'} authorization cannot be refreshed "
            "automatically — user re-authorization required"
        )

    def requires_reauthorization(
        self, authz, *, now: datetime | None = None
    ) -> bool:
        now = now or datetime.now(timezone.utc)
        return self.authorization_status(authz, now=now) in ("expired", "revoked", "superseded")

    def capabilities(self, *, app_type: str | None = None) -> dict:
        return {"data": True, "trading": False}


class UpstoxRenewalStrategy(BrokerRenewalStrategy):
    """Upstox: no refresh token exists — renewal == user re-OAuth."""

    broker_id = "UPSTOX"


class FyersRenewalStrategy(BrokerRenewalStrategy):
    """FYERS: refresh token exists (~15d) but is PIN-gated; April-2026
    rules bar continuous refresh sessions for trading. Automated refresh
    is NOT permitted — reauthorization via OAuth popup."""

    broker_id = "FYERS"

    def capabilities(self, *, app_type: str | None = None) -> dict:
        data_only = app_type == "-100"
        return {
            "data": True,
            "trading": False if data_only else True,  # -200 trading app only
            "market_websocket": True,
            "order_websocket": False,  # data-only app: no order events
            "refresh_automated": False,  # PIN-gated — never automated
            "reauthorization_required_on_expiry": True,
        }


_STRATEGIES: dict[str, BrokerRenewalStrategy] = {}


def get_renewal_strategy(broker: str) -> BrokerRenewalStrategy:
    key = (broker or "").upper()
    if key == "FYERS":
        if "FYERS" not in _STRATEGIES:
            _STRATEGIES["FYERS"] = FyersRenewalStrategy()
        return _STRATEGIES["FYERS"]
    if key == "UPSTOX":
        if "UPSTOX" not in _STRATEGIES:
            _STRATEGIES["UPSTOX"] = UpstoxRenewalStrategy()
        return _STRATEGIES["UPSTOX"]
    # Unknown broker: conservative base strategy (never refreshable).
    base = BrokerRenewalStrategy()
    base.broker_id = key or "UNKNOWN"
    return base


def broker_capabilities(broker: str, *, app_type: str | None = None) -> dict:
    """Convenience: capability matrix for a broker (and app type)."""
    return get_renewal_strategy(broker).capabilities(app_type=app_type)
