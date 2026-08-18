// ---------------------------------------------------------------------------
// Phase 6.5.0 — Exit Intent / Selector Foundation (pure domain layer).
//
// Determines WHAT current strategy exposure should be targeted for exit.
// It NEVER executes orders, never calculates fill prices, never mutates
// positions or cash, never calls broker/network APIs, and never bypasses the
// existing paper execution engine. It only RESOLVES targets from the current
// authoritative open positions.
//
// Authoritative exposure: the existing NETTED position model (backend
// `positions` table, PositionOut). Identity = user + symbol + expiry + strike
// + option_type; `net_quantity` is signed lots (BUY = +, SELL = −); a zero
// net quantity marks the position CLOSED. The schema already preserves
// BUY/SELL attribution: the position's net sign gives the current side, and
// the per-leg `action` + `option_type` survive at the order level
// (paper_orders / legs) under `strategy_execution_id`. NO new persistence
// model is introduced by this phase.
//
// Result contract:
//   { ok: true,  scope, intent, targets: [...], warnings: [] }
//   { ok: false, scope, intent, error: { code, message } }
//
// Errors:
//   INVALID_INTENT                malformed scope/identity/selector
//   MISSING_QUANTITY              QUANTITY mode without a quantity
//   INVALID_QUANTITY              non-finite / non-integer / <= 0 quantity
//   TARGET_NOT_FOUND              scope identity has no open, owned position
//   NO_MATCHING_TARGETS           selector matched nothing
//   AMBIGUOUS_EXIT_QUANTITY       QUANTITY mode matched more than one target
//   EXIT_QUANTITY_EXCEEDS_REMAINING  requested quantity > remaining quantity
// ---------------------------------------------------------------------------

export const EXIT_SCOPE = Object.freeze({
  POSITION: "POSITION",
  STRATEGY: "STRATEGY",
  PORTFOLIO: "PORTFOLIO",
});

export const EXIT_QUANTITY_MODE = Object.freeze({
  ALL: "ALL",
  QUANTITY: "QUANTITY",
});

export const OPTION_TYPE = Object.freeze({
  CALL: "CALL",
  PUT: "PUT",
});

export const SIDE = Object.freeze({
  BUY: "BUY",
  SELL: "SELL",
});

export const EXIT_ERROR = Object.freeze({
  INVALID_INTENT: "INVALID_INTENT",
  MISSING_QUANTITY: "MISSING_QUANTITY",
  INVALID_QUANTITY: "INVALID_QUANTITY",
  TARGET_NOT_FOUND: "TARGET_NOT_FOUND",
  NO_MATCHING_TARGETS: "NO_MATCHING_TARGETS",
  AMBIGUOUS_EXIT_QUANTITY: "AMBIGUOUS_EXIT_QUANTITY",
  EXIT_QUANTITY_EXCEEDS_REMAINING: "EXIT_QUANTITY_EXCEEDS_REMAINING",
});

const FINITE = Number.isFinite;

// ---- normalization helpers -------------------------------------------------

// Normalize option type input: "call" | "put" | "CE" | "PE" (any case) →
// "CALL" | "PUT". Anything else → null.
function normalizeOptionType(value) {
  if (value == null) return null;
  const v = String(value).trim().toUpperCase();
  if (v === "CALL" || v === "CE") return OPTION_TYPE.CALL;
  if (v === "PUT" || v === "PE") return OPTION_TYPE.PUT;
  return null;
}

// Normalize side input: "buy" | "sell" (any case) → "BUY" | "SELL". Anything
// else → null.
function normalizeSide(value) {
  if (value == null) return null;
  const v = String(value).trim().toUpperCase();
  if (v === "BUY" || v === "B") return SIDE.BUY;
  if (v === "SELL" || v === "S") return SIDE.SELL;
  return null;
}

// Normalize the selector shape { optionType?, action?, legId? }. Returns
// null when the selector is not an object or carries an unrecognized value.
export function normalizeSelector(selector) {
  if (selector == null || typeof selector !== "object") return null;
  const optionType = normalizeOptionType(selector.optionType);
  const action = normalizeSide(selector.action);
  if (selector.optionType != null && optionType == null) return null;
  if (selector.action != null && action == null) return null;
  const legId = selector.legId == null ? null : String(selector.legId);
  return { optionType, action, legId };
}

// Human label for a normalized selector: ALL / CALL / PUT / BUY / SELL /
// BUY CALL / BUY PUT / SELL CALL / SELL PUT / LEG <id>.
export function selectorLabel(selector) {
  const sel = normalizeSelector(selector);
  if (sel == null) return "INVALID";
  if (sel.legId != null) return `LEG ${sel.legId}`;
  const parts = [sel.action, sel.optionType].filter(Boolean);
  return parts.length === 0 ? "ALL" : parts.join(" ");
}

// ---- exposure view ---------------------------------------------------------

// Map an authoritative position (backend PositionOut, or the frontend shape
// from toFrontendPosition) into the exposure contract the resolver consumes:
//   { positionId, userId?, strategyExecutionId?, optionType, side,
//     remainingQuantity, status, symbol?, expiry?, strike? }
// The side comes from the SIGN of the net quantity (BUY = +, SELL = −); the
// remaining executable quantity is |net_quantity| — NEVER the original order
// quantity. Closed/zero-quantity positions are kept with remainingQuantity 0
// so the resolver can exclude them explicitly.
export function exposureFromPosition(position) {
  if (position == null || typeof position !== "object") return null;
  const positionId = position.positionId ?? position.id;
  if (positionId == null) return null;

  const netQuantity =
    position.net_quantity != null
      ? Number(position.net_quantity)
      : position.qty != null && position.action != null
        ? (normalizeSide(position.action) === SIDE.SELL ? -1 : 1) * Number(position.qty)
        : NaN;

  const optionType = normalizeOptionType(position.option_type ?? position.type ?? position.optionType);
  const explicitSide = normalizeSide(position.side ?? position.action);
  let side = explicitSide;
  if (side == null && FINITE(netQuantity)) {
    side = netQuantity > 0 ? SIDE.BUY : netQuantity < 0 ? SIDE.SELL : null;
  }

  const remaining =
    position.remainingQuantity != null
      ? Number(position.remainingQuantity)
      : FINITE(netQuantity)
        ? Math.abs(netQuantity)
        : NaN;

  return {
    positionId,
    userId: position.userId ?? null,
    strategyExecutionId:
      position.strategyExecutionId ??
      position.executionId ??
      position.execution_id ??
      position.strategy_execution_id ??
      null,
    optionType,
    side,
    remainingQuantity: remaining,
    status: position.status ?? "open",
    symbol: position.symbol ?? null,
    expiry: position.expiry ?? null,
    strike: position.strike ?? position.strike_price ?? null,
  };
}

// ---- target resolution -----------------------------------------------------

// Pure target resolution. Never mutates inputs, never executes, never calls
// the network. Deterministic ordering: targets are sorted by
// [optionType, side, positionId] so the result never depends on the input
// array order.
//
// intent: {
//   scope: "POSITION" | "STRATEGY" | "PORTFOLIO",
//   positionId?: number|string,          // required for POSITION scope
//   strategyExecutionId?: string|null,   // required for STRATEGY scope
//   selector?: { optionType?, action?, legId? },
//   quantityMode: "ALL" | "QUANTITY",
//   quantity?: number,                   // required for QUANTITY mode
// }
// exposures: array of exposure objects (see exposureFromPosition). The
// caller supplies the CURRENT user's open positions — the resolver also
// enforces options.userId isolation when provided.
// options: { userId? }
export function resolveExitTargets(intent, exposures, options) {
  const invalid = (code, message) => ({
    ok: false,
    scope: intent?.scope ?? null,
    intent: { ...(intent ?? {}) },
    error: { code, message },
  });

  if (intent == null || typeof intent !== "object") {
    return invalid(EXIT_ERROR.INVALID_INTENT, "Exit intent is required.");
  }

  const scope = intent.scope;
  if (scope !== EXIT_SCOPE.POSITION && scope !== EXIT_SCOPE.STRATEGY && scope !== EXIT_SCOPE.PORTFOLIO) {
    return invalid(EXIT_ERROR.INVALID_INTENT, `Unknown exit scope: ${String(intent.scope)}`);
  }

  const selector = normalizeSelector(intent.selector);
  if (selector == null) {
    return invalid(EXIT_ERROR.INVALID_INTENT, "Exit selector is invalid.");
  }

  const quantityMode = intent.quantityMode;
  if (quantityMode !== EXIT_QUANTITY_MODE.ALL && quantityMode !== EXIT_QUANTITY_MODE.QUANTITY) {
    return invalid(EXIT_ERROR.INVALID_INTENT, `Unknown quantity mode: ${String(intent.quantityMode)}`);
  }

  let requestedQuantity = null;
  if (quantityMode === EXIT_QUANTITY_MODE.QUANTITY) {
    if (intent.quantity == null || intent.quantity === "") {
      return invalid(EXIT_ERROR.MISSING_QUANTITY, "QUANTITY mode requires a quantity.");
    }
    requestedQuantity = Number(intent.quantity);
    if (!Number.isInteger(requestedQuantity) || !FINITE(requestedQuantity) || requestedQuantity <= 0) {
      return invalid(
        EXIT_ERROR.INVALID_QUANTITY,
        "Exit quantity must be a positive whole number of lots.",
      );
    }
  }

  // Scope identity validation happens BEFORE selector matching so a bad
  // identity is reported as TARGET_NOT_FOUND, never as a selector miss.
  if (scope === EXIT_SCOPE.POSITION) {
    if (intent.positionId == null || intent.positionId === "") {
      return invalid(EXIT_ERROR.INVALID_INTENT, "POSITION scope requires positionId.");
    }
  }
  if (scope === EXIT_SCOPE.STRATEGY) {
    if (intent.strategyExecutionId == null || intent.strategyExecutionId === "") {
      return invalid(EXIT_ERROR.INVALID_INTENT, "STRATEGY scope requires strategyExecutionId.");
    }
  }

  // Build the candidate pool: only the current user's OPEN, non-zero
  // positions. Zero-quantity and closed positions are excluded — the
  // remaining quantity is the ONLY executable quantity, never the original.
  const pool = [];
  for (const exposure of exposures ?? []) {
    const e = exposureFromPosition(exposure);
    if (e == null) continue;
    if (options?.userId != null && e.userId != null && String(e.userId) !== String(options.userId)) {
      continue; // never mix another user's positions
    }
    const isOpen = e.status == null || String(e.status).toLowerCase() === "open";
    const hasRemaining = FINITE(e.remainingQuantity) && e.remainingQuantity > 0;
    if (!isOpen || !hasRemaining) continue;
    pool.push(e);
  }

  const missingTarget = (identityLabel) =>
    invalid(
      EXIT_ERROR.TARGET_NOT_FOUND,
      `No open position for the requested ${identityLabel} — it may be closed or unavailable.`,
    );

  // Scope filter.
  let scoped = pool;
  if (scope === EXIT_SCOPE.POSITION) {
    scoped = pool.filter((e) => String(e.positionId) === String(intent.positionId));
    if (scoped.length === 0) return missingTarget("position");
  } else if (scope === EXIT_SCOPE.STRATEGY) {
    scoped = pool.filter((e) => e.strategyExecutionId != null && String(e.strategyExecutionId) === String(intent.strategyExecutionId));
    if (scoped.length === 0) return missingTarget("strategy execution");
  }

  // Selector filter (optionType / action / legId — all optional).
  let matched = scoped;
  if (selector.legId != null) {
    matched = matched.filter((e) => String(e.positionId) === selector.legId);
  }
  if (selector.optionType != null) {
    matched = matched.filter((e) => e.optionType === selector.optionType);
  }
  if (selector.action != null) {
    matched = matched.filter((e) => e.side === selector.action);
  }

  if (matched.length === 0) {
    return invalid(
      EXIT_ERROR.NO_MATCHING_TARGETS,
      `No open position matches the exit selector (${selectorLabel(selector)}).`,
    );
  }

  // Quantity resolution.
  let targets;
  if (quantityMode === EXIT_QUANTITY_MODE.ALL) {
    // ALL may legitimately resolve multiple targets.
    targets = matched.map((e) => buildTarget(e, e.remainingQuantity));
  } else {
    if (matched.length > 1) {
      return invalid(
        EXIT_ERROR.AMBIGUOUS_EXIT_QUANTITY,
        `QUANTITY mode matched ${matched.length} positions — specify an unambiguous selector or legId.`,
      );
    }
    const only = matched[0];
    if (requestedQuantity > only.remainingQuantity) {
      return invalid(
        EXIT_ERROR.EXIT_QUANTITY_EXCEEDS_REMAINING,
        `Requested ${requestedQuantity} lot(s) but only ${only.remainingQuantity} remain open.`,
      );
    }
    targets = [buildTarget(only, requestedQuantity)];
  }

  // Deterministic ordering: [optionType, side, positionId].
  targets.sort((a, b) => {
    const byType = String(a.optionType).localeCompare(String(b.optionType));
    if (byType !== 0) return byType;
    const bySide = String(a.side).localeCompare(String(b.side));
    if (bySide !== 0) return bySide;
    return String(a.positionId).localeCompare(String(b.positionId), undefined, { numeric: true });
  });

  return {
    ok: true,
    scope,
    intent: { ...intent, selector },
    targets,
    warnings: [],
  };
}

function buildTarget(exposure, quantity) {
  return {
    positionId: exposure.positionId,
    // In the netted model the strategy-leg identity IS the open position;
    // order-level leg attribution (paper_orders.action) rides the same
    // position id via strategy_execution_id.
    legId: String(exposure.positionId),
    strategyExecutionId: exposure.strategyExecutionId,
    optionType: exposure.optionType,
    side: exposure.side,
    remainingQuantity: exposure.remainingQuantity,
    quantity,
    symbol: exposure.symbol,
    expiry: exposure.expiry,
    strike: exposure.strike,
  };
}
