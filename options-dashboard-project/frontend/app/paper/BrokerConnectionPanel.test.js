import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import BrokerConnectionPanel from "./BrokerConnectionPanel";

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
    order_types: ["MARKET", "LIMIT", "SL"],
    poa: true,
    ddpi: false,
  },
  generated_at: "2026-08-18T10:57:32+05:30",
  cached: false,
  error: null,
  message: "Upstox profile retrieved.",
};

const capitalWithBroker = {
  broker_available_funds: { value: 250000, source: "BROKER_REPORTED", status: "available" },
  broker_margin: { value: 37503, source: "BROKER_REPORTED", status: "available" },
  broker_generated_at: "2026-08-18T10:57:30+05:30",
  broker_errors: {},
  estimated_capital: { value: null, source: "ESTIMATED", status: "unavailable" },
};

const capitalNoBroker = {
  broker_available_funds: { value: null, source: "UNAVAILABLE", status: "unavailable" },
  broker_margin: { value: null, source: "UNAVAILABLE", status: "unavailable" },
  broker_errors: { funds: "BROKER_MAINTENANCE" },
  estimated_capital: { value: null, source: "ESTIMATED", status: "unavailable" },
};

const marketOpen = { status: "open", source: "upstox", checked_at: "2026-08-18T10:57:00+05:30" };

function render(props) {
  return renderToStaticMarkup(
    React.createElement(BrokerConnectionPanel, {
      profile: connectedProfile,
      capital: capitalWithBroker,
      marketStatus: marketOpen,
      optionChain: { required: 1, loaded: 1 },
      loading: false,
      error: null,
      onRefresh: () => {},
      ...props,
    })
  );
}

describe("BrokerConnectionPanel — connected profile", () => {
  it("renders the connected state with user/account/status and health rows", () => {
    const html = render({});
    expect(html).toContain("BROKER CONNECTION");
    expect(html).toContain("UPSTOX CONNECTED");
    expect(html).toContain("Shahid Ahmed");
    expect(html).toContain("ACTIVE");
    expect(html).toContain("CONNECTION HEALTH");
    expect(html).toContain("Market Status");
    expect(html).toContain("Option Chain");
  });

  it("renders the full diagnostic status list from the pure layer", () => {
    const html = render({});
    // Profile, Funds, Margin, Market Status, Option Chain all AVAILABLE.
    const availableCount = (html.match(/>AVAILABLE</g) ?? []).length;
    expect(availableCount).toBe(5);
  });

  it("renders the capability list (NFO, order types, POA/DDPI)", () => {
    const html = render({});
    expect(html).toContain("ACCOUNT CAPABILITIES");
    expect(html).toContain("NFO SEGMENT · ENABLED");
    expect(html).toContain("MARKET ORDER · PERMITTED");
    expect(html).toContain("LIMIT ORDER · PERMITTED");
    expect(html).toContain("POA · AUTHORIZED");
    expect(html).toContain("DDPI · NOT AUTHORIZED"); // reported false → shown as disabled state
  });

  it("shows a Last verified timestamp and a Refresh Connection action", () => {
    const html = render({});
    expect(html).toContain("LAST VERIFIED");
    expect(html).toContain("Refresh Connection");
  });

  it("marks a cached profile as CACHED (stale data is never real-time)", () => {
    const html = render({ profile: { ...connectedProfile, cached: true } });
    expect(html).toContain("CACHED");
  });
});

describe("BrokerConnectionPanel — unavailable / partial states", () => {
  it("renders the unavailable state with the reason, never a fake user name", () => {
    const html = render({
      profile: { status: "unavailable", profile: null, error: "BROKER_PROFILE_UNAVAILABLE", message: "Upstox profile temporarily unavailable" },
    });
    expect(html).toContain("BROKER CONNECTION · UNAVAILABLE");
    expect(html).toContain("Upstox profile temporarily unavailable");
    expect(html).toContain("UPSTOX DISCONNECTED");
    expect(html).not.toContain("Unknown User");
    expect(html).toContain("Refresh Connection");
  });

  it("renders the expired-session state with a Reconnect Broker action", () => {
    const html = render({
      profile: { status: "unavailable", profile: null, error: "BROKER_TOKEN_EXPIRED", message: "Upstox session expired or unauthorized" },
    });
    expect(html).toContain("BROKER SESSION EXPIRED");
    expect(html).toContain("Reconnect Broker");
    expect(html).toContain("UPSTOX DISCONNECTED");
  });

  it("renders PARTIAL (not DISCONNECTED) when only broker data services are down", () => {
    const html = render({ capital: capitalNoBroker });
    expect(html).toContain("UPSTOX PARTIAL");
    // Profile + Market Status stay available; Funds/Margin unavailable.
    expect(html).toContain(">AVAILABLE<");
    expect(html).toContain(">UNAVAILABLE<");
    // The broker connection itself is still verified via the profile call.
    expect(html).toContain("Shahid Ahmed");
  });

  it("handles missing optional fields without crashing", () => {
    const sparse = {
      ...connectedProfile,
      profile: { user_id: "UCC12345", is_active: true, broker: "UPSTOX" },
    };
    const html = render({ profile: sparse, defaultDetailsOpen: true });
    expect(html).toContain("UCC12345");
    expect(html).toContain("ACTIVE");
    // Missing optional fields are never fabricated: no account type, no
    // invented capabilities, no fake user name.
    expect(html).not.toContain("NFO SEGMENT ENABLED");
    expect(html).not.toContain("Unknown User");
  });

  it("renders the expandable profile details (USER / USER ID / EXCHANGES / POA / DDPI)", () => {
    const html = render({ defaultDetailsOpen: true });
    expect(html).toContain("USER ID");
    expect(html).toContain("UCC12345");
    expect(html).toContain("EXCHANGES");
    expect(html).toContain("NSE, NFO, BSE");
    expect(html).toContain("POA");
    expect(html).toContain("DDPI");
  });
});

describe("BrokerConnectionPanel — security", () => {
  it("never renders credential fields even if injected into the payload", () => {
    const tainted = {
      ...connectedProfile,
      profile: {
        ...connectedProfile.profile,
        access_token: "super-secret-token",
        client_secret: "super-secret",
        refresh_token: "ref-token",
      },
    };
    const html = render({ profile: tainted });
    expect(html).not.toContain("super-secret");
    expect(html).not.toContain("ref-token");
    expect(html).not.toContain("access_token");
    expect(html).not.toContain("client_secret");
  });
});
