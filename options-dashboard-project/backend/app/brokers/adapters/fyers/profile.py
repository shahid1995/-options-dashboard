"""FYERS profile & identity extraction (broker-specific — AD-6 boundary).

Extracts the FYERS **customer Login ID** from the ``GET /api/v3/profile``
payload. This is broker-specific logic that MUST NOT live in
``app.identity`` (AD-6) and MUST NOT be inlined in the auth callback —
the callback routes identity extraction through the adapter.

LIVE-CONFIRMATION STATUS (staging pending)
------------------------------------------
The exact profile field that carries the customer Login ID is NOT yet
proven against a live FYERS profile response. Third-party material
commonly shows ``fy_id``; that convention is NOT hard-coded here.
``IDENTITY_FIELD_CANDIDATES`` below is the isolated mapping to confirm:

  1. Authenticate once against FYERS staging (one OAuth consent).
  2. Call :func:`diagnose_profile_identity` (safe diagnostics — masked
     values, no tokens/secret/PIN/PAN) and record which field matched.
  3. Reorder/prune the candidate list to the single confirmed field.

The extractor is DELIBERATELY fail-closed: if no candidate field carries
a non-empty identity, it raises ``ValueError`` instead of guessing. It
can NEVER return the API App ID, the secret, an email or a PAN — those
are explicitly rejected, so a wrong-shape profile payload can never make
the App ID become the ownership identity.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# The isolated, to-be-confirmed identity field mapping.
#
# Ordered candidates: the first field present with a non-empty, non-reserved
# value wins. Keep this list MINIMAL — every extra candidate widens what can
# become an ownership identity. Candidates are broker-profile field names
# ONLY; OAuth/credential concepts (app id, client_id, secret, redirect) are
# structurally impossible here and additionally rejected below.
# ---------------------------------------------------------------------------
IDENTITY_FIELD_CANDIDATES: tuple[str, ...] = (
    # UNCONFIRMED — third-party material commonly shows `fy_id`. The FIRST
    # live FYERS staging profile response settles this mapping (reorder /
    # prune; do not extend without a documented source).
    "fy_id",
    "login_id",
)

# Field names that must NEVER be selected as customer identity even if a
# future payload shape changes around them. (Redundant with the candidate
# allow-list above — a second, explicit line of defense.)
_FORBIDDEN_IDENTITY_FIELDS = frozenset(
    {
        "app_id",
        "appId",
        "client_id",
        "clientId",
        "api_key",
        "secret_id",
        "secretId",
        "app_id_hash",
        "appIdHash",
        "redirect_uri",
        "pin",
        "email",
        "email_id",
        "pan",
    }
)


def profile_data(profile: dict) -> dict:
    """Return the FYERS profile payload's inner ``data`` object.

    FYERS v3 bodies are ``{"s": "ok", "data": {...}}``. A missing or
    non-dict ``data`` yields ``{}`` (never a fabricated profile).
    """
    if not isinstance(profile, dict):
        return {}
    data = profile.get("data")
    return data if isinstance(data, dict) else {}


def extract_account_id(profile: dict) -> str | None:
    """Extract the FYERS customer Login ID from a profile response.

    Returns ``None`` when no confirmed candidate field carries a usable
    identity — fail-closed, never guessed, never a credential field.
    Raises ``ValueError`` only for a structurally unacceptable match
    (a forbidden field), which indicates a payload shape drift that must
    be investigated, not silently absorbed.

    This is a FYERS-specific function. Other brokers implement their own
    extraction in their adapter package (AD-6).
    """
    data = profile_data(profile)
    for field in IDENTITY_FIELD_CANDIDATES:
        raw = data.get(field)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value:
            continue
        lowered = field.lower()
        if field in _FORBIDDEN_IDENTITY_FIELDS or lowered in _FORBIDDEN_IDENTITY_FIELDS:
            raise ValueError(
                f"FYERS identity extraction selected a forbidden field '{field}' — "
                "profile payload shape drifted; investigate before connecting."
            )
        return value
    return None


def extract_customer_identity(profile: dict) -> str:
    """Fail-closed customer identity extraction (the adapter's Test F path).

    Unlike :func:`extract_account_id` (which returns ``None`` for a
    missing identity), this raises ``ValueError`` when the customer Login
    ID cannot be determined. Callers that MUST have an identity (OAuth
    callback, ownership arbitration) use this; exploratory callers use
    the ``None``-returning variant.
    """
    identity = extract_account_id(profile)
    if not identity:
        raise ValueError(
            "FYERS profile did not contain a confirmed customer Login ID field "
            f"(candidates: {', '.join(IDENTITY_FIELD_CANDIDATES)}). "
            "Identity extraction is fail-closed — run the staging identity "
            "diagnostic and confirm the profile field mapping."
        )
    return identity


def mask_identity(value: str | None) -> str:
    """Mask an identity value for safe diagnostics/logging.

    Keeps the first 2 and last 2 characters for human correlation; the
    middle is replaced. Short values are fully masked.
    """
    if not value:
        return "<missing>"
    text = str(value)
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:2]}{'*' * (len(text) - 4)}{text[-2:]}"


def diagnose_profile_identity(profile: dict) -> dict:
    """Safe, non-secret profile identity diagnostic (staging Phase 18).

    Reports ONLY: the profile keys present (names, never values), the
    selected identity field name, the MASKED identity, and whether
    extraction succeeded. Safe to log at INFO. Never includes the access
    token, refresh token, app secret, PIN, PAN or the full email.

    The first real staging profile response run through this function
    settles the exact identity field name (update
    ``IDENTITY_FIELD_CANDIDATES`` from its evidence).
    """
    data = profile_data(profile)
    selected_field: str | None = None
    try:
        identity = extract_account_id(profile)
    except ValueError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "selected_field": None,
            "identity_masked": None,
            "candidates": list(IDENTITY_FIELD_CANDIDATES),
            "profile_keys": sorted(data.keys()),
        }
    if identity is not None:
        for field in IDENTITY_FIELD_CANDIDATES:
            raw = data.get(field)
            if raw is not None and str(raw).strip() == identity:
                selected_field = field
                break
    return {
        "ok": identity is not None,
        "error": None if identity is not None else "no candidate identity field present",
        "selected_field": selected_field,
        "identity_masked": mask_identity(identity),
        "candidates": list(IDENTITY_FIELD_CANDIDATES),
        "profile_keys": sorted(data.keys()),
    }
