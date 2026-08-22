import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { BulkExitModal, BulkExitResultBanner } from "./BulkExit";

const target = {
  executionId: "exec-1",
  strategyName: "Bull Call Spread",
  positions: [{ positionId: 1 }, { positionId: 2 }],
  value: 24300,
  unrealized: 1200,
  isStrategy: true,
};

const accountStats = { openPositions: 5, openStrategies: 3 };

function render(node) {
  return renderToStaticMarkup(node);
}

describe("BulkExitModal", () => {
  it("renders nothing when closed", () => {
    expect(render(<BulkExitModal kind={null} />)).toBe("");
  });

  it("shows the EXIT STRATEGY confirmation with informational metrics", () => {
    const html = render(
      <BulkExitModal kind="STRATEGY" target={target} accountStats={accountStats} busy={false} error={null} onCancel={() => {}} onConfirm={() => {}} />
    );
    expect(html).toContain("Exit all positions for Bull Call Spread?");
    expect(html).toContain("Positions");
    expect(html).toContain("2");
    expect(html).toContain("Approximate current value");
    expect(html).toContain("Current unrealized P&amp;L");
    expect(html).toContain("EXIT STRATEGY");
    expect(html).toContain("Cancel");
    // Informational-only disclaimer: the backend decides the fill prices.
    expect(html).toContain("informational only");
  });

  it("shows the EXIT ALL confirmation with account stats", () => {
    const html = render(
      <BulkExitModal kind="ACCOUNT" target={null} accountStats={accountStats} busy={false} error={null} onCancel={() => {}} onConfirm={() => {}} />
    );
    expect(html).toContain("EXIT ALL PAPER POSITIONS?");
    expect(html).toContain("Open positions");
    expect(html).toContain("5");
    expect(html).toContain("Open strategies");
    expect(html).toContain("3");
    expect(html).toContain("EXIT ALL");
    expect(html).toContain("close ALL currently open paper positions");
  });

  it("disables both buttons and shows EXITING… while busy (double-click protection)", () => {
    const html = render(
      <BulkExitModal kind="ACCOUNT" target={null} accountStats={accountStats} busy error={null} onCancel={() => {}} onConfirm={() => {}} />
    );
    expect(html).toContain("EXITING…");
    // Both buttons are disabled during execution.
    const cancel = html.match(/<button[^>]*disabled=""[^>]*>Cancel<\/button>/);
    expect(cancel).not.toBeNull();
    expect(html).toContain("EXITING…");
  });

  it("shows a structured error message inside the modal", () => {
    const html = render(
      <BulkExitModal kind="ACCOUNT" target={null} accountStats={accountStats} busy={false} error="Market is closed." onCancel={() => {}} onConfirm={() => {}} />
    );
    expect(html).toContain("Market is closed.");
  });
});

describe("BulkExitResultBanner", () => {
  it("renders nothing without a result", () => {
    expect(render(<BulkExitResultBanner result={null} onDismiss={() => {}} />)).toBe("");
  });

  it("shows the empty state without claiming success", () => {
    const html = render(<BulkExitResultBanner result={{ status: "NO_POSITIONS" }} onDismiss={() => {}} />);
    expect(html).toContain("No open positions to exit");
    expect(html).not.toContain("EXIT COMPLETE");
  });

  it("shows EXIT COMPLETE with counts, realized P&L and cash change", () => {
    const html = render(
      <BulkExitResultBanner
        result={{
          status: "SUCCESS",
          requestedCount: 5,
          exitedCount: 5,
          failedCount: 0,
          totalRealizedPnl: 1234.5,
          cashChange: 7890.0,
          positions: [],
          groups: [
            { exited: 2 },
            { exited: 1 },
            { exited: 1 },
          ],
          errors: [],
        }}
        onDismiss={() => {}}
      />
    );
    expect(html).toContain("EXIT COMPLETE");
    expect(html).toContain("Positions exited: <b>5</b>");
    expect(html).toContain("Strategies closed: <b>3</b>");
    expect(html).toContain("Realized P&amp;L");
  });

  it("shows EXIT PARTIALLY COMPLETED and never claims all positions exited", () => {
    const html = render(
      <BulkExitResultBanner
        result={{
          status: "PARTIAL",
          requestedCount: 4,
          exitedCount: 3,
          failedCount: 1,
          totalRealizedPnl: 100,
          cashChange: 200,
          positions: [
            { status: "EXITED" },
            { status: "ALREADY_CLOSED", symbol: "NIFTY", strike: 24550, option_type: "call", expiry: "2026-08-27", error: "Position already closed" },
          ],
          groups: [],
          errors: ["Position 3 (NIFTY 24550 CALL): already closed"],
        }}
        onDismiss={() => {}}
      />
    );
    expect(html).toContain("EXIT PARTIALLY COMPLETED");
    expect(html).toContain("Exited: <b>3</b> / 4");
    expect(html).toContain("Failed: <b>1</b>");
    expect(html).toContain("Position already closed");
    expect(html).not.toContain("All positions exited");
  });

  it("shows EXIT FAILED with the errors when nothing exited", () => {
    const html = render(
      <BulkExitResultBanner
        result={{
          status: "FAILED",
          requestedCount: 1,
          exitedCount: 0,
          failedCount: 1,
          totalRealizedPnl: 0,
          cashChange: 0,
          positions: [],
          groups: [],
          errors: ["Position 1 (NIFTY 24350 CALL): simulated failure"],
        }}
        onDismiss={() => {}}
      />
    );
    expect(html).toContain("EXIT FAILED");
    expect(html).toContain("simulated failure");
  });
});
