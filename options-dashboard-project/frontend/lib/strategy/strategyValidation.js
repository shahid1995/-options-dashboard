// Strategy validation domain: structural checks on legs / strategies.
//
// These validate the canonical leg shape (type, action, strike, qty, expiry,
// premium) and, at execution time, the market/instrument context. Market-open
// validation is a two-layer system: `validateExecution` gives the UI an
// immediate, structured answer (shown in the review panel), while the paper
// trading execution gate re-validates live against the server at the exact
// moment of execution and remains the final authority.
//
// All validators return { valid, issues } so callers can either block or
// surface warnings without throwing. Issue messages are leg-indexed and
// actionable ("Leg 2: Quantity must be at least 1."), never vague.

// Structural check for one leg. Expiry is required (every leg the builder
// creates carries one) and the premium must be a finite, non-negative number.
export function validateLeg(leg) {
  const issues = [];
  if (!leg) return { valid: false, issues: ["leg is required"] };
  if (!["call", "put"].includes(leg.type)) issues.push("Option type must be call or put.");
  if (!["buy", "sell"].includes(leg.action)) issues.push("Action must be buy or sell.");
  if (!Number.isFinite(Number(leg.strike)) || !(Number(leg.strike) > 0)) issues.push("Strike must be a positive number.");
  if (!Number.isFinite(Number(leg.qty)) || Number(leg.qty) < 1) issues.push("Quantity must be at least 1.");
  if (!leg.expiry) issues.push("Expiry is missing.");
  const price = Number(leg.price);
  if (!Number.isFinite(price) || price < 0) issues.push("Premium must be a valid non-negative number.");
  return { valid: issues.length === 0, issues };
}

// Structural check for a whole strategy: at least one leg, and every leg valid.
// Each issue is prefixed with its 1-based leg index.
export function validateStrategy(legs) {
  if (!Array.isArray(legs) || legs.length === 0) {
    return { valid: false, issues: ["Strategy must contain at least one leg."] };
  }
  const issues = [];
  legs.forEach((l, i) => {
    validateLeg(l).issues.forEach((msg) => issues.push(`Leg ${i + 1}: ${msg}`));
  });
  return { valid: issues.length === 0, issues };
}

// Chain availability for one leg: the expiry's chain must be loaded and the
// leg's strike must exist in it. Returns [] when the leg is fine.
function chainIssuesForLeg(leg, i, chains, expiries) {
  const issues = [];
  const strikes = chains?.[leg.expiry];
  if (expiries && Array.isArray(expiries) && leg.expiry && !expiries.includes(leg.expiry)) {
    issues.push(`Leg ${i + 1}: Expiry ${leg.expiry} is not available.`);
  }
  if (strikes === undefined) {
    // Only flag missing chain data when we were asked to check it — the
    // builder can still analyze a strategy before every expiry is fetched.
    if (chains) issues.push(`Leg ${i + 1}: Chain data for expiry ${leg.expiry} is not loaded.`);
  } else if (!strikes.includes(Number(leg.strike))) {
    issues.push(`Leg ${i + 1}: Strike ${leg.strike} is not available in the ${leg.expiry} chain.`);
  }
  return issues;
}

// Pre-execution validation: structural checks plus the market/instrument
// context required for execution.
//
//   legs          - the legs to execute
//   marketStatus  - { status: "open" | "closed" | "unknown" } or null/undefined
//                   when status cannot be determined (treated as blocked)
//   chains        - { [expiry]: [strike, ...] } of currently loaded chains
//   expiries      - list of available expiry dates (optional)
//
// Market rules: only a verified "open" status passes; closed, unknown or
// missing status all block with the same user-facing messages the execution
// gate uses. The UI uses this to disable the review's Execute button; the
// server-side gate still re-validates at the moment of execution.
export function validateExecution(legs, { marketStatus, chains, expiries } = {}) {
  const issues = [];
  const structural = validateStrategy(legs);
  issues.push(...structural.issues);

  const status = marketStatus?.status;
  if (status === "open") {
    // OK — proceed with chain checks below.
  } else if (status === "closed") {
    issues.push("Market is closed. Paper order was not executed.");
  } else {
    issues.push("Unable to verify market status. Order was not executed.");
  }

  if (chains && Array.isArray(legs)) {
    legs.forEach((l, i) => issues.push(...chainIssuesForLeg(l, i, chains, expiries)));
  }

  return { valid: issues.length === 0, issues };
}
