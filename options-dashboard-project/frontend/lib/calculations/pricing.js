// Pricing domain: dependency-free Black-Scholes-style valuation for European
// options, plus the Greeks that are mathematically consistent with the same
// model.
//
// This is the Phase 3 scenario layer. It is deliberately SEPARATE from:
//   - the Phase 2 expiry payoff engine (intrinsic value at expiration), and
//   - the live chain Greek engine (broker/chain greeks).
// Live chain values stay live; model values stay labelled as modelled.
//
// Model parameters (all configurable inputs, never hidden assumptions):
//   S — underlying spot  (scenario state, must be > 0)
//   K — strike           (must be > 0)
//   T — time to expiry in YEAR FRACTIONS (calendar days / 365), clamped >= 0
//   σ — volatility as a decimal fraction (0.18 = 18%), clamped to a small
//       positive floor
//   r — risk-free interest rate (decimal, default 0)
//   q — dividend yield (decimal, default 0)
//
// Numerical stability: T = 0 short-circuits to intrinsic value (clean
// transition to the Phase 2 expiry payoff), σ ≈ 0 falls back to the
// deterministic forward value, and deep ITM/OTM saturate the normal CDF. No
// NaN or Infinity is ever returned for valid numeric inputs — invalid inputs
// return NaN so callers can surface a structured warning instead.

const SQRT_2PI = Math.sqrt(2 * Math.PI);
// Smallest volatility the model will accept (clamped). Chosen so σ√T never
// underflows for realistic times, while still allowing "very small vol"
// scenarios to be computed.
export const MIN_VOLATILITY = 1e-4;

// ---- Normal distribution helpers ----------------------------------------

// Standard normal PDF: φ(x) = e^(-x²/2) / √(2π).
export function normalPdf(x) {
  if (!Number.isFinite(x)) return 0;
  return Math.exp(-0.5 * x * x) / SQRT_2PI;
}

// Standard normal CDF via the Abramowitz & Stegun 7.1.26 erf approximation
// (max abs error ~1.5e-7, dependency-free, saturates cleanly at ±∞).
export function normalCdf(x) {
  if (Number.isNaN(x)) return NaN;
  if (x === Infinity) return 1;
  if (x === -Infinity) return 0;
  if (x === 0) return 0.5; // exact (the rational approximation is off at 0 by ~1e-10)
  const z = x / Math.SQRT2;
  const t = 1 / (1 + 0.3275911 * Math.abs(z));
  const erf =
    1 -
    (((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t *
      Math.exp(-z * z));
  return 0.5 * (1 + (x >= 0 ? erf : -erf));
}

// d1 / d2 for the Black-Scholes model. Undefined (NaN) when T <= 0 or σ <= 0 —
// callers short-circuit those cases before calling this.
export function bsD1D2(S, K, T, sigma, r = 0, q = 0) {
  const volT = sigma * Math.sqrt(T);
  if (volT <= 0) return { d1: NaN, d2: NaN };
  const logSk = Math.log(S / K);
  return {
    d1: (logSk + (r - q + (sigma * sigma) / 2) * T) / volT,
    d2: (logSk + (r - q - (sigma * sigma) / 2) * T) / volT,
  };
}

// ---- Option values --------------------------------------------------------

function validInputs(S, K, T, sigma, r, q) {
  return (
    Number.isFinite(S) && Number.isFinite(K) && Number.isFinite(T) && Number.isFinite(sigma) && Number.isFinite(r) && Number.isFinite(q)
  );
}

// Black-Scholes call value.
export function bsCall(S, K, T, sigma, r = 0, q = 0) {
  if (!validInputs(S, K, T, sigma, r, q)) return NaN;
  if (!(S > 0) || !(K > 0)) return NaN;
  if (T <= 0) return Math.max(S - K, 0); // expiry: intrinsic value
  const s = Math.max(sigma, MIN_VOLATILITY);
  if (sigma <= 0) return Math.max(S * Math.exp(-q * T) - K * Math.exp(-r * T), 0);
  const { d1, d2 } = bsD1D2(S, K, T, s, r, q);
  return S * Math.exp(-q * T) * normalCdf(d1) - K * Math.exp(-r * T) * normalCdf(d2);
}

// Black-Scholes put value.
export function bsPut(S, K, T, sigma, r = 0, q = 0) {
  if (!validInputs(S, K, T, sigma, r, q)) return NaN;
  if (!(S > 0) || !(K > 0)) return NaN;
  if (T <= 0) return Math.max(K - S, 0); // expiry: intrinsic value
  const s = Math.max(sigma, MIN_VOLATILITY);
  if (sigma <= 0) return Math.max(K * Math.exp(-r * T) - S * Math.exp(-q * T), 0);
  const { d1, d2 } = bsD1D2(S, K, T, s, r, q);
  return K * Math.exp(-r * T) * normalCdf(-d2) - S * Math.exp(-q * T) * normalCdf(-d1);
}

// Dispatch on leg type: "call" | "put".
export function bsValue(type, S, K, T, sigma, r = 0, q = 0) {
  return type === "put" ? bsPut(S, K, T, sigma, r, q) : bsCall(S, K, T, sigma, r, q);
}

// ---- Greeks from the same model ------------------------------------------

// Full Greek set { delta, gamma, theta, vega } for one European option, using
// exactly the same S, K, T, σ, r, q as the value functions.
//
// Sign conventions: delta ∈ (0,1) for calls / (−1,0) for puts; gamma, vega ≥ 0
// for long options; theta = dV/dT per year (negative for long options — value
// erodes as time passes). At T = 0 the model returns the step-function limits
// (delta 0/±1, gamma/vega 0, theta 0) so nothing leaks NaN/Infinity.
export function bsGreeks(type, S, K, T, sigma, r = 0, q = 0) {
  if (!validInputs(S, K, T, sigma, r, q) || !(S > 0) || !(K > 0)) {
    return { delta: NaN, gamma: NaN, theta: NaN, vega: NaN };
  }
  if (T <= 0) {
    if (type === "call") return { delta: S > K ? 1 : 0, gamma: 0, theta: 0, vega: 0 };
    return { delta: S < K ? -1 : 0, gamma: 0, theta: 0, vega: 0 };
  }
  const s = Math.max(sigma, MIN_VOLATILITY);
  if (sigma <= 0) {
    // Deterministic forward: value is a step function at the forward strike.
    const fwd = S * Math.exp((r - q) * T);
    if (type === "call") return { delta: fwd > K ? 1 : 0, gamma: 0, theta: 0, vega: 0 };
    return { delta: fwd < K ? -1 : 0, gamma: 0, theta: 0, vega: 0 };
  }
  const { d1, d2 } = bsD1D2(S, K, T, s, r, q);
  const pdf = normalPdf(d1);
  const sqrtT = Math.sqrt(T);
  const dfQ = Math.exp(-q * T);
  const dfR = Math.exp(-r * T);
  const isCall = type === "call";
  const nD1 = normalCdf(d1);
  const nD2 = normalCdf(d2);

  const delta = dfQ * (isCall ? nD1 : nD1 - 1);
  const gamma = (dfQ * pdf) / (S * s * sqrtT);
  const vega = S * dfQ * pdf * sqrtT;
  const theta =
    -((S * dfQ * pdf * s) / (2 * sqrtT)) +
    (isCall ? -1 : 1) * r * K * dfR * (isCall ? nD2 : normalCdf(-d2)) +
    (isCall ? 1 : -1) * q * S * dfQ * (isCall ? nD1 : normalCdf(-d1));

  return { delta, gamma, theta, vega };
}

export function bsDelta(type, S, K, T, sigma, r = 0, q = 0) {
  return bsGreeks(type, S, K, T, sigma, r, q).delta;
}
export function bsGamma(type, S, K, T, sigma, r = 0, q = 0) {
  return bsGreeks(type, S, K, T, sigma, r, q).gamma;
}
export function bsTheta(type, S, K, T, sigma, r = 0, q = 0) {
  return bsGreeks(type, S, K, T, sigma, r, q).theta;
}
export function bsVega(type, S, K, T, sigma, r = 0, q = 0) {
  return bsGreeks(type, S, K, T, sigma, r, q).vega;
}

// ---- Time representation ---------------------------------------------------

// Year fraction between an ISO valuation date (YYYY-MM-DD) and an ISO expiry
// date, using calendar days / 365, clamped to >= 0. Returns null when either
// date is unparseable. Never passes a raw integer "days remaining" to the
// pricing model — the model only ever sees this year fraction.
export function timeToExpiry(valuationDate, expiryDate) {
  const v = new Date(`${valuationDate}T00:00:00Z`);
  const e = new Date(`${expiryDate}T00:00:00Z`);
  if (Number.isNaN(v.getTime()) || Number.isNaN(e.getTime())) return null;
  const days = (e - v) / 86400000;
  return Math.max(0, days / 365);
}

// Add whole calendar days to an ISO date, returning a new ISO date. Used to
// advance the valuation date for time scenarios.
export function addDays(isoDate, days) {
  const d = new Date(`${isoDate}T00:00:00Z`);
  if (Number.isNaN(d.getTime()) || !Number.isFinite(Number(days))) return isoDate;
  d.setUTCDate(d.getUTCDate() + Number(days));
  return d.toISOString().slice(0, 10);
}
