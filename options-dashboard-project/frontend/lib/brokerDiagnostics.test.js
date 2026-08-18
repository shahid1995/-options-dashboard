import { describe, it, expect } from "vitest";
import {
  CONNECTION_STATE,
  DIAGNOSTIC_STATUS,
  buildBrokerDiagnostics,
  brokerCapabilities,
  isBrokerSessionExpired,
  profileAvailable,
  profileDiagnostic,
  fundsDiagnostic,
  marginDiagnostic,
  marketStatusDiagnostic,
  optionChainDiagnostic,
} from "./brokerDiagnostics";

const connectedProfile = {
  status: "available",
  source: "BROKER_REPORTED",
  broker: "UPSTOX",
  profile: {
    user_name: "Shahid Ahmed",
    email: "shahid@example.com",
    user_id: "UCC12345",
    user_type: "individual",
    account_type: null,
    is_active: true,
    exchanges: ["NSE", "NFO", "BSE"],
    products: ["D", "I"],
    order_types: ["MARKET", "LIMIT"],
    poa: true,
    ddpi: false,
  },
  generated_at: "2026-08-18T10:57:32+05:30",
  error: null,
  message: "Upstox profile retrieved.",
};

// The diagnostics layer consumes the DISPLAY shape (capitalDisplay output):
// camelCase brokerAvailableFunds / brokerMargin with {value, source, status}.
const capitalWithBroker = {
  brokerAvailableFunds: { value: 250000, source: "BROKER_REPORTED", status: "available" },
  brokerMargin: { value: 37503, source: "BROKER_REPORTED", status: "available" },
  brokerGeneratedAt: "2026-08-18T10:57:30+05:30",
  brokerErrors: {},
};

const capitalNoBroker = {
  brokerAvailableFunds: { value: null, source: "UNAVAILABLE", status: "unavailable" },
  brokerMargin: { value: null, source: "UNAVAILABLE", status: "unavailable" },
  brokerErrors: { funds: "BROKER_MAINTENANCE" },
};

const marketOpen = { status: "open", source: "upstox", checked_at: "2026-08-18T10:57:00+05:30" };
const marketUnknown = { status: "unknown", source: "upstox" };

describe("profileDiagnostic", () => {
  it("is AVAILABLE when the profile endpoint succeeds", () => {
    const d = profileDiagnostic(connectedProfile);
    expect(d.status).toBe(DIAGNOSTIC_STATUS.AVAILABLE);
    expect(d.source).toBe("BROKER_REPORTED");
    expect(d.checkedAt).toBe(connectedProfile.generated_at);
  });

  it("is UNAVAILABLE with the structured reason when the profile fails", () => {
    const d = profileDiagnostic({ status: "unavailable", error: "BROKER_TOKEN_EXPIRED", message: "Upstox session expired" });
    expect(d.status).toBe(DIAGNOSTIC_STATUS.UNAVAILABLE);
    expect(d.message).toBe("Upstox session expired");
  });

  it("never falls back to a valid-looking profile when unavailable", () => {
    expect(profileAvailable({ status: "unavailable", profile: connectedProfile.profile })).toBe(false);
    expect(profileAvailable(null)).toBe(false);
  });
});

describe("funds / margin diagnostics (Phase 6.1 integration)", () => {
  it("FUNDS is AVAILABLE when broker funds data exists", () => {
    const d = fundsDiagnostic(capitalWithBroker);
    expect(d.status).toBe(DIAGNOSTIC_STATUS.AVAILABLE);
    expect(d.source).toBe("BROKER_REPORTED");
  });

  it("FUNDS is UNAVAILABLE (not 0) when broker funds are missing", () => {
    const d = fundsDiagnostic(capitalNoBroker);
    expect(d.status).toBe(DIAGNOSTIC_STATUS.UNAVAILABLE);
    expect(d.message).toContain("maintenance");
  });

  it("MARGIN is AVAILABLE only from BROKER_REPORTED data", () => {
    expect(marginDiagnostic(capitalWithBroker).status).toBe(DIAGNOSTIC_STATUS.AVAILABLE);
    expect(marginDiagnostic(capitalNoBroker).status).toBe(DIAGNOSTIC_STATUS.UNAVAILABLE);
    // Estimated capital is never a substitute for broker margin.
    expect(marginDiagnostic({ brokerMargin: { value: null }, estimatedCapital: { value: 5827 } }).status).toBe(DIAGNOSTIC_STATUS.UNAVAILABLE);
  });
});

describe("market status diagnostic", () => {
  it("is AVAILABLE for a resolved open or closed status", () => {
    expect(marketStatusDiagnostic(marketOpen).status).toBe(DIAGNOSTIC_STATUS.AVAILABLE);
    expect(marketStatusDiagnostic({ status: "closed", source: "upstox" }).status).toBe(DIAGNOSTIC_STATUS.AVAILABLE);
  });

  it("is UNAVAILABLE when the status could not be resolved", () => {
    expect(marketStatusDiagnostic(marketUnknown).status).toBe(DIAGNOSTIC_STATUS.UNAVAILABLE);
  });

  it("is UNKNOWN when no check has happened yet", () => {
    expect(marketStatusDiagnostic(null).status).toBe(DIAGNOSTIC_STATUS.UNKNOWN);
  });
});

describe("option chain diagnostic", () => {
  it("is AVAILABLE when every required chain is loaded", () => {
    expect(optionChainDiagnostic({ required: 2, loaded: 2 }).status).toBe(DIAGNOSTIC_STATUS.AVAILABLE);
  });

  it("is PARTIAL when only some required chains are loaded", () => {
    expect(optionChainDiagnostic({ required: 2, loaded: 1 }).status).toBe(DIAGNOSTIC_STATUS.PARTIAL);
  });

  it("is UNAVAILABLE when required chains are missing", () => {
    expect(optionChainDiagnostic({ required: 1, loaded: 0 }).status).toBe(DIAGNOSTIC_STATUS.UNAVAILABLE);
  });

  it("is UNKNOWN when nothing is required yet", () => {
    expect(optionChainDiagnostic({ required: 0, loaded: 0 }).status).toBe(DIAGNOSTIC_STATUS.UNKNOWN);
  });
});

describe("overall connection state", () => {
  it("is CONNECTED when profile + all broker services are available", () => {
    const { connection } = buildBrokerDiagnostics({
      profile: connectedProfile,
      capital: capitalWithBroker,
      marketStatus: marketOpen,
      optionChain: { required: 1, loaded: 1 },
    });
    expect(connection).toBe(CONNECTION_STATE.CONNECTED);
  });

  it("is PARTIAL (never DISCONNECTED) when only one service is down", () => {
    const { connection, items } = buildBrokerDiagnostics({
      profile: connectedProfile,
      capital: capitalNoBroker, // funds + margin unavailable
      marketStatus: marketOpen,
      optionChain: { required: 1, loaded: 1 },
    });
    expect(connection).toBe(CONNECTION_STATE.PARTIAL);
    const profile = items.find((i) => i.name === "Profile");
    expect(profile.status).toBe(DIAGNOSTIC_STATUS.AVAILABLE);
  });

  it("is DISCONNECTED when the profile authentication fails", () => {
    const { connection } = buildBrokerDiagnostics({
      profile: { status: "unavailable", error: "BROKER_TOKEN_EXPIRED" },
      capital: capitalWithBroker,
      marketStatus: marketOpen,
      optionChain: { required: 1, loaded: 1 },
    });
    expect(connection).toBe(CONNECTION_STATE.DISCONNECTED);
  });

  it("is DISCONNECTED when the profile cannot be obtained at all", () => {
    const { connection } = buildBrokerDiagnostics({
      profile: { status: "unavailable", error: "BROKER_NETWORK_ERROR" },
      capital: capitalWithBroker,
      marketStatus: marketOpen,
      optionChain: { required: 1, loaded: 1 },
    });
    expect(connection).toBe(CONNECTION_STATE.DISCONNECTED);
  });

  it("is never CONNECTED merely from a session cookie (no profile call)", () => {
    const { connection } = buildBrokerDiagnostics({
      profile: null,
      capital: capitalWithBroker,
      marketStatus: marketOpen,
      optionChain: { required: 1, loaded: 1 },
    });
    expect(connection).toBe(CONNECTION_STATE.DISCONNECTED);
  });
});

describe("brokerCapabilities", () => {
  it("derives capabilities ONLY from reported profile data", () => {
    const caps = brokerCapabilities(connectedProfile.profile);
    const byKey = Object.fromEntries(caps.map((c) => [c.key, c]));
    expect(byKey.nfo.enabled).toBe(true); // NFO is in exchanges
    expect(byKey.options.enabled).toBe(true); // products reported
    expect(byKey.market_order.enabled).toBe(true);
    expect(byKey.limit_order.enabled).toBe(true);
    expect(byKey.poa.enabled).toBe(true);
    expect(byKey.ddpi.enabled).toBe(false); // reported false, shown as capability state
  });

  it("never invents NFO when the broker does not report it", () => {
    const caps = brokerCapabilities({ ...connectedProfile.profile, exchanges: ["NSE", "BSE"] });
    const byKey = Object.fromEntries(caps.map((c) => [c.key, c]));
    expect(byKey.nfo.enabled).toBe(false);
  });

  it("returns [] for a missing profile", () => {
    expect(brokerCapabilities(null)).toEqual([]);
  });
});

describe("session expiry detection", () => {
  it("detects BROKER_TOKEN_EXPIRED results", () => {
    expect(isBrokerSessionExpired({ status: "unavailable", error: "BROKER_TOKEN_EXPIRED" })).toBe(true);
    expect(isBrokerSessionExpired(connectedProfile)).toBe(false);
    expect(isBrokerSessionExpired(null)).toBe(false);
  });
});

describe("no network calls from the diagnostics layer", () => {
  it("derives everything from passed-in inputs (no fetch/axios)", () => {
    // The module must not import any HTTP client.
    const src = require("fs").readFileSync(require.resolve("./brokerDiagnostics.js"), "utf8");
    expect(src).not.toMatch(/axios|fetch\(|api\.get|XMLHttpRequest/);
  });
});
