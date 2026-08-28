"""Upstox-specific profile normalization (Phase 10.2B-2).

Extracts the broker account ID from an Upstox profile response.
This is broker-specific logic that MUST NOT live in app/identity.py (AD-6).
"""

from __future__ import annotations


def extract_account_id(profile: dict) -> str | None:
    """Extract the Upstox user_id from a profile response.

    Returns the broker's account identifier (Upstox user_id / UCC),
    or None if the profile does not contain one.

    This is an Upstox-specific function.  Other brokers implement their
    own extraction in their adapter package (AD-6).
    """
    data = profile.get("data") if isinstance(profile, dict) else None
    data = data if isinstance(data, dict) else {}
    user_id = str(data.get("user_id") or "").strip()
    return user_id or None
