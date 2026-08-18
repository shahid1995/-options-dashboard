"""Broker capability model (Phase 6.5.0.2).

Capability states distinguish WHAT the broker API provides from what the
CURRENT user/session can use:

- ``SUPPORTED``       — the broker API provides the capability.
- ``AVAILABLE``       — provided AND the current session/account can use it.
- ``UNSUPPORTED``     — the broker API does not provide it.
- ``UNAVAILABLE``     — provided but not currently usable (e.g. no session).
- ``AUTH_REQUIRED``   — provided but the user must authenticate first.
- ``ACCOUNT_DISABLED``— provided but the user's account/segment has it
                        disabled (e.g. F&O segment not enabled).
- ``TEMPORARILY_UNAVAILABLE`` — provided but currently down (maintenance /
                        rate limit / transient failure).

Example that must never collapse to a boolean: Upstox F&O order placement
is SUPPORTED by the API but ACCOUNT_DISABLED for a user without the NFO
segment — that is NOT ``UNSUPPORTED``.

``wired`` is a PLATFORM dimension (not a broker dimension): it records
whether the capability is wired into the current application execution
path. Order capabilities are SUPPORTED by Upstox V3 but wired=False in this
phase (no live execution) — the contract is prepared, not connected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CapabilityState(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"


@dataclass(frozen=True)
class BrokerCapability:
    """One capability: its broker-supported state, its platform wiring and a
    human detail. Never a bare boolean."""

    name: str
    state: CapabilityState
    wired: bool = False
    detail: str | None = None

    def with_state(self, state: CapabilityState, detail: str | None = None) -> "BrokerCapability":
        """Immutable copy with a different state (used to derive session/
        account-specific capability views)."""
        return BrokerCapability(self.name, state, self.wired, detail or self.detail)


class BrokerCapabilities:
    """An ordered capability set keyed by canonical capability name."""

    def __init__(self, items: list[BrokerCapability] | None = None):
        self._items: dict[str, BrokerCapability] = {}
        for item in items or []:
            self._items[item.name] = item

    def get(self, name: str) -> BrokerCapability | None:
        return self._items.get(name)

    def state(self, name: str) -> CapabilityState | None:
        item = self._items.get(name)
        return item.state if item else None

    def __contains__(self, name: str) -> bool:
        return name in self._items

    def __iter__(self):
        return iter(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def states(self) -> dict[str, str]:
        return {name: item.state.value for name, item in self._items.items()}

    def wired(self) -> tuple[str, ...]:
        return tuple(name for name, item in self._items.items() if item.wired)

    def names(self) -> tuple[str, ...]:
        return tuple(self._items)

    def with_session_state(
        self, session_active: bool, profile: dict | None = None
    ) -> "BrokerCapabilities":
        """Derive the session/account-aware capability view.

        Data capabilities require an active session (else AUTH_REQUIRED).
        When the broker profile is available, account-level signals are
        applied: an inactive account disables account data, and a profile
        whose exchange list omits the F&O segment (NFO) disables the
        F&O/options capabilities as ACCOUNT_DISABLED — never UNSUPPORTED.
        """
        fno_names = {
            "option_chain",
            "option_contracts",
            "orders",
            "market_orders",
            "limit_orders",
            "stop_loss",
            "stop_loss_market",
            "modify_order",
            "cancel_order",
            "multi_order",
            "order_tags",
            "native_slicing",
            "market_protection",
            "after_market_orders",
            "positions",
            "trades",
        }
        data_names = {
            "profile",
            "funds",
            "margin",
            "market_status",
            "option_chain",
            "option_contracts",
            "quotes",
            "positions",
            "trades",
            "holdings",
            "orders",
            "market_orders",
            "limit_orders",
            "stop_loss",
            "stop_loss_market",
            "modify_order",
            "cancel_order",
            "multi_order",
            "order_tags",
            "native_slicing",
            "market_protection",
            "after_market_orders",
        }
        exchanges = profile.get("exchanges") if isinstance(profile, dict) else None
        fno_disabled = isinstance(exchanges, list) and len(exchanges) > 0 and "NFO" not in exchanges
        account_inactive = (
            isinstance(profile, dict) and profile.get("is_active") is False
        )

        items = []
        for item in self._items.values():
            state = item.state
            detail = item.detail
            if account_inactive and item.name in data_names and state in (
                CapabilityState.SUPPORTED,
                CapabilityState.AVAILABLE,
            ):
                state, detail = CapabilityState.ACCOUNT_DISABLED, "Broker account is not active."
            elif fno_disabled and item.name in fno_names and state in (
                CapabilityState.SUPPORTED,
                CapabilityState.AVAILABLE,
            ):
                state, detail = CapabilityState.ACCOUNT_DISABLED, "F&O segment (NFO) is not enabled for this account."
            elif not session_active and item.name in data_names and state in (
                CapabilityState.SUPPORTED,
                CapabilityState.AVAILABLE,
            ):
                state, detail = CapabilityState.AUTH_REQUIRED, "Authenticate with the broker to use this capability."
            items.append(item.with_state(state, detail))
        return BrokerCapabilities(items)
