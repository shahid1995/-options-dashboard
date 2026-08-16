// Strategy validation domain: structural checks on legs / strategies.
//
// These validate the canonical leg shape (type, action, strike, qty), not
// market conditions — market-open validation stays in the paper-trading
// execution gate. Returns { valid, issues } so callers can either block or
// surface warnings without throwing.

export function validateLeg(leg) {
  const issues = [];
  if (!leg) return { valid: false, issues: ["leg is required"] };
  if (!["call", "put"].includes(leg.type)) issues.push("type must be call or put");
  if (!["buy", "sell"].includes(leg.action)) issues.push("action must be buy or sell");
  if (!Number.isFinite(Number(leg.strike)) || !(Number(leg.strike) > 0)) issues.push("strike must be a positive number");
  if (!Number.isFinite(Number(leg.qty)) || Number(leg.qty) < 1) issues.push("quantity must be at least 1");
  return { valid: issues.length === 0, issues };
}

export function validateStrategy(legs) {
  if (!Array.isArray(legs) || legs.length === 0) {
    return { valid: false, issues: ["strategy must have at least one leg"] };
  }
  const issues = [];
  legs.forEach((l, i) => {
    validateLeg(l).issues.forEach((msg) => issues.push(`leg ${i + 1}: ${msg}`));
  });
  return { valid: issues.length === 0, issues };
}
