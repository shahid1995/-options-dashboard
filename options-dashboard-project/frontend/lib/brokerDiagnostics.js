// ---------------------------------------------------------------------------
// Phase 6.4.1 — Broker connection diagnostics (PURE / derived layer).
//
// This layer NEVER makes network calls. It receives already-fetched results
// (broker profile, capital/funds/margin, market status, option chain state)
// and derives SYSTEM-HEALTH statuses for the connection card.
//
// These are health states (AVAILABLE / UNAVAILABLE / PARTIAL / UNKNOWN) —
// NOT trading-style green/red signals, NOT trading recommendations.
//
// Connection state model (§13):
//   CONNECTED    — profile is available and the broker session is valid.
//   PARTIAL      — profile works, but one or more broker data services are
//                  unavailable (margin down ≠ broker disconnected).
//   DISCONNECTED — profile authentication fails or cannot be obtained.
// ---------------------------------------------------------------------------

export const DIAGNOSTIC_STATUS = {
  AVAILABLE: "AVAILABLE",
  UNAVAILABLE: "UNAVAILABLE",
  PARTIAL: "PARTIAL",
  UNKNOWN: "UNKNOWN",
};

export const CONNECTION_STATE = {
  CONNECTED: "CONNECTED",
  PARTIAL: "PARTIAL",
  DISCONNECTED: "DISCONNECTED",
};

export const BROKER_PROFILE_ERRORS = {
  BROKER_AUTH_REQUIRED: "Broker login required",
  BROKER_TOKEN_EXPIRED: "Broker session expired — reconnect your broker",
  BROKER_RATE_LIMITED: "Broker rate limited — try again shortly",
  BROKER_PROFILE_UNAVAILABLE: "Upstox profile temporarily unavailable",
  BROKER_BAD_RESPONSE: "Upstox profile response unreadable",
  BROKER_MAINTENANCE: "Upstox maintenance window",
  BROKER_NETWORK_ERROR: "Could not reach Upstox",
};

// One diagnostic item (§11): {name, status, source, message, checkedAt}.
export function diagnosticItem(name, status, source, message, checkedAt) {
  return { name, status, source: source ?? "UNKNOWN", message: message ?? null, checkedAt: checkedAt ?? null };
}

// A finite number is "present". null/NaN/Infinity are missing — never 0.
function isFiniteNumber(v) {
  return v != null && typeof v === "number" && Number.isFinite(v);
}

// The broker profile is usable when the endpoint reports availability AND a
// normalized profile object came back.
export function profileAvailable(profileResult) {
  return Boolean(profileResult && profileResult.status === "available" && profileResult.profile);
}

// A profile result is a session-expiry failure when the backend classified
// the broker auth as expired (401/403 → BROKER_TOKEN_EXPIRED).
export function isBrokerSessionExpired(profileResult) {
  return Boolean(profileResult && profileResult.error === "BROKER_TOKEN_EXPIRED");
}

// ---- Per-service diagnostic rules (§12) -------------------------------------

// PROFILE: available when the profile endpoint succeeds. The reason comes
// from the structured error (never a raw provider message).
export function profileDiagnostic(profileResult, checkedAt) {
  if (profileAvailable(profileResult)) {
    return diagnosticItem(
      "Profile",
      DIAGNOSTIC_STATUS.AVAILABLE,
      "BROKER_REPORTED",
      "Upstox profile verified",
      checkedAt ?? profileResult.generated_at ?? null
    );
  }
  const error = profileResult?.error ?? "BROKER_PROFILE_UNAVAILABLE";
  const message =
    profileResult?.message ?? BROKER_PROFILE_ERRORS[error] ?? "Broker profile unavailable";
  return diagnosticItem("Profile", DIAGNOSTIC_STATUS.UNAVAILABLE, "BROKER_REPORTED", message, null);
}

// FUNDS: available when current broker funds data exists (Phase 6.1 result).
export function fundsDiagnostic(capitalDisplay, checkedAt) {
  const funds = capitalDisplay?.brokerAvailableFunds ?? null;
  if (isFiniteNumber(funds?.value)) {
    return diagnosticItem("Funds", DIAGNOSTIC_STATUS.AVAILABLE, "BROKER_REPORTED", "Broker funds available", checkedAt ?? capitalDisplay?.brokerGeneratedAt ?? null);
  }
  const code = capitalDisplay?.brokerErrors?.funds;
  return diagnosticItem(
    "Funds",
    DIAGNOSTIC_STATUS.UNAVAILABLE,
    "BROKER_REPORTED",
    code ? BROKER_PROFILE_ERRORS[code] ?? "Broker funds unavailable" : "Broker funds unavailable",
    null
  );
}

// MARGIN: available when broker-reported margin data exists (Phase 6.1).
export function marginDiagnostic(capitalDisplay, checkedAt) {
  const margin = capitalDisplay?.brokerMargin ?? null;
  if (isFiniteNumber(margin?.value)) {
    return diagnosticItem("Margin", DIAGNOSTIC_STATUS.AVAILABLE, "BROKER_REPORTED", "Broker margin available", checkedAt ?? capitalDisplay?.brokerGeneratedAt ?? null);
  }
  return diagnosticItem("Margin", DIAGNOSTIC_STATUS.UNAVAILABLE, "BROKER_REPORTED", "Broker margin unavailable", null);
}

// MARKET STATUS: available when the status was RESOLVED (open or closed —
// both are valid broker/exchange answers). Unknown/unresolved → unavailable.
export function marketStatusDiagnostic(marketStatus, checkedAt) {
  const resolved = marketStatus && (marketStatus.status === "open" || marketStatus.status === "closed");
  if (resolved) {
    return diagnosticItem(
      "Market Status",
      DIAGNOSTIC_STATUS.AVAILABLE,
      marketStatus.source ?? "BROKER_REPORTED",
      marketStatus.status === "open" ? "Market open" : "Market closed",
      checkedAt ?? marketStatus.checkedAt ?? marketStatus.checked_at ?? null
    );
  }
  return diagnosticItem(
    "Market Status",
    marketStatus ? DIAGNOSTIC_STATUS.UNAVAILABLE : DIAGNOSTIC_STATUS.UNKNOWN,
    marketStatus?.source ?? "UNKNOWN",
    marketStatus?.status === "unknown" ? "Market status could not be resolved" : "Market status not checked yet",
    null
  );
}

// OPTION CHAIN: available when every currently-required chain is loaded;
// partial when some are; unavailable when none is; unknown when nothing is
// required yet (no expiry selected / no legs).
export function optionChainDiagnostic(optionChain, checkedAt) {
  const required = optionChain?.required ?? 0;
  const loaded = optionChain?.loaded ?? 0;
  if (required === 0) {
    return diagnosticItem("Option Chain", DIAGNOSTIC_STATUS.UNKNOWN, "CHAIN_CACHE", "No option chain required yet", checkedAt ?? null);
  }
  if (loaded >= required) {
    return diagnosticItem("Option Chain", DIAGNOSTIC_STATUS.AVAILABLE, "CHAIN_CACHE", "Required option chain loaded", checkedAt ?? null);
  }
  if (loaded > 0) {
    return diagnosticItem("Option Chain", DIAGNOSTIC_STATUS.PARTIAL, "CHAIN_CACHE", `${loaded} of ${required} required chains loaded`, checkedAt ?? null);
  }
  return diagnosticItem("Option Chain", DIAGNOSTIC_STATUS.UNAVAILABLE, "CHAIN_CACHE", "Required option chain not loaded", checkedAt ?? null);
}

// ---- Overall state (§13) -----------------------------------------------------

// CONNECTED when the profile works and auth/session is valid. DISCONNECTED
// when the profile fails (including expired sessions). PARTIAL when the
// profile works but at least one broker data service is unavailable. Never
// "connected" merely because the browser holds a session cookie — the broker
// profile call is the primary verification.
export function overallConnectionState(profile, otherDiagnostics) {
  if (isBrokerSessionExpired(profile)) return CONNECTION_STATE.DISCONNECTED;
  if (!profileAvailable(profile)) return CONNECTION_STATE.DISCONNECTED;
  const degraded = (otherDiagnostics ?? []).some((d) => d.status === DIAGNOSTIC_STATUS.UNAVAILABLE);
  return degraded ? CONNECTION_STATE.PARTIAL : CONNECTION_STATE.CONNECTED;
}

// ---- Full diagnostics set ----------------------------------------------------

// Builds the complete CONNECTION HEALTH set from already-fetched inputs.
// `optionChain` is {required, loaded} (derived by the page from the chain
// cache — this layer never fetches).
export function buildBrokerDiagnostics({ profile, capital, marketStatus, optionChain, checkedAt }) {
  const display = capital ?? {};
  const profileItem = profileDiagnostic(profile, checkedAt);
  const items = [
    profileItem,
    fundsDiagnostic(display, checkedAt),
    marginDiagnostic(display, checkedAt),
    marketStatusDiagnostic(marketStatus, checkedAt),
    optionChainDiagnostic(optionChain, checkedAt),
  ];
  const connection = overallConnectionState(profile, items);
  return { connection, items };
}

// ---- Broker account capabilities (§19) ---------------------------------------
// Derived ONLY from what the broker profile reports — capabilities that the
// API does not report are never inferred. Presented as ACCOUNT CAPABILITIES,
// not trading recommendations.

export function brokerCapabilities(profile) {
  if (!profile) return [];
  const caps = [];
  const exchanges = Array.isArray(profile.exchanges) ? profile.exchanges : [];
  const products = Array.isArray(profile.products) ? profile.products : [];
  const orderTypes = Array.isArray(profile.order_types) ? profile.order_types : [];
  // Each capability carries a state word (ENABLED/DISABLED, PERMITTED/NOT
  // PERMITTED, AUTHORIZED/NOT AUTHORIZED) so the UI never renders a feature
  // name like "NFO SEGMENT ENABLED" with a "—" prefix as if it were enabled.
  const push = (key, label, enabled, detail, stateWord) => {
    if (enabled != null) caps.push({ key, label, enabled, detail, stateWord, source: "BROKER_REPORTED" });
  };

  push("nfo", "NFO SEGMENT", exchanges.includes("NFO"), "NIFTY index-options segment", exchanges.includes("NFO") ? "ENABLED" : "DISABLED");
  push("options", "OPTIONS PRODUCTS", products.length > 0, `products: ${products.join(", ")}`, products.length > 0 ? "ENABLED" : "DISABLED");
  push("market_order", "MARKET ORDER", orderTypes.includes("MARKET"), null, orderTypes.includes("MARKET") ? "PERMITTED" : "NOT PERMITTED");
  push("limit_order", "LIMIT ORDER", orderTypes.includes("LIMIT"), null, orderTypes.includes("LIMIT") ? "PERMITTED" : "NOT PERMITTED");
  push("sl_order", "SL ORDER", orderTypes.includes("SL"), null, orderTypes.includes("SL") ? "PERMITTED" : "NOT PERMITTED");
  push("poa", "POA", profile.poa === true ? true : profile.poa === false ? false : null, null, profile.poa === true ? "AUTHORIZED" : "NOT AUTHORIZED");
  push("ddpi", "DDPI", profile.ddpi === true ? true : profile.ddpi === false ? false : null, null, profile.ddpi === true ? "AUTHORIZED" : "NOT AUTHORIZED");
  return caps.filter((c) => c.enabled != null);
}

// Human label for the profile error code (mirrors the backend structured
// diagnostics; never a raw provider error).
export function brokerProfileErrorLabel(code) {
  return BROKER_PROFILE_ERRORS[code] ?? null;
}
