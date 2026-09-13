// =============================================================================
// StrikeNova App Core Components — Tests
// =============================================================================
import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  Metric,
  Table,
  Badge,
  Chip,
  SegmentedControl,
  ChartContainer,
  EmptyState,
  LoadingState,
  ErrorState,
  ActionButton,
} from "./core";

describe("App Core Components", () => {
  describe("Metric", () => {
    it("renders label and value", () => {
      const html = renderToStaticMarkup(
        React.createElement(Metric, { label: "Spot", value: 25512 })
      );
      expect(html).toContain("Spot");
      expect(html).toContain("25,512");
    });

    it("renders null as em-dash", () => {
      const html = renderToStaticMarkup(
        React.createElement(Metric, { label: "Test", value: null })
      );
      expect(html).toContain("—");
    });

    it("renders zero correctly", () => {
      const html = renderToStaticMarkup(
        React.createElement(Metric, { label: "Test", value: 0 })
      );
      expect(html).toContain("0");
    });

    it("renders unit", () => {
      const html = renderToStaticMarkup(
        React.createElement(Metric, { label: "IV", value: 14.2, unit: "%", decimals: 1 })
      );
      expect(html).toContain("14.2");
      expect(html).toContain("%");
    });

    it("renders hint", () => {
      const html = renderToStaticMarkup(
        React.createElement(Metric, { label: "Test", value: 100, hint: "Helper text" })
      );
      expect(html).toContain("Helper text");
    });

    it("applies positive semantic color", () => {
      const html = renderToStaticMarkup(
        React.createElement(Metric, { label: "P&L", value: 1250, semantic: "positive" })
      );
      expect(html).toContain("color:#4CAF7D");
    });

    it("applies negative semantic color", () => {
      const html = renderToStaticMarkup(
        React.createElement(Metric, { label: "P&L", value: -500, semantic: "negative" })
      );
      expect(html).toContain("color:#E15252");
    });

    it("renders all sizes without error", () => {
      ["sm", "md", "lg", "hero"].forEach((size) => {
        const html = renderToStaticMarkup(
          React.createElement(Metric, { label: "Test", value: 100, size })
        );
        expect(html).toContain("Test");
      });
    });
  });

  describe("Table", () => {
    const columns = [
      { key: "symbol", header: "Symbol" },
      { key: "value", header: "Value", align: "right" },
    ];
    const data = [
      { symbol: "NIFTY", value: 25500 },
      { symbol: "BANKNIFTY", value: 52000 },
    ];

    it("renders headers", () => {
      const html = renderToStaticMarkup(
        React.createElement(Table, { columns, data })
      );
      expect(html).toContain("Symbol");
      expect(html).toContain("Value");
    });

    it("renders data rows", () => {
      const html = renderToStaticMarkup(
        React.createElement(Table, { columns, data })
      );
      expect(html).toContain("NIFTY");
      expect(html).toContain("25500");
    });

    it("renders empty state when no data", () => {
      const html = renderToStaticMarkup(
        React.createElement(Table, { columns, data: [] })
      );
      expect(html).toContain("No data available.");
    });

    it("renders custom empty message", () => {
      const html = renderToStaticMarkup(
        React.createElement(Table, { columns, data: [], emptyMessage: "No positions found." })
      );
      expect(html).toContain("No positions found.");
    });

    it("renders compact mode", () => {
      const html = renderToStaticMarkup(
        React.createElement(Table, { columns, data, compact: true })
      );
      expect(html).toContain("NIFTY");
    });

    it("renders custom cell render", () => {
      const cols = [
        { key: "name", header: "Name", render: (v) => `**${v}**` },
      ];
      const html = renderToStaticMarkup(
        React.createElement(Table, { columns: cols, data: [{ name: "Test" }] })
      );
      expect(html).toContain("**Test**");
    });
  });

  describe("Badge", () => {
    it("renders neutral badge", () => {
      const html = renderToStaticMarkup(
        React.createElement(Badge, null, "OPEN")
      );
      expect(html).toContain("OPEN");
    });

    it("renders positive badge", () => {
      const html = renderToStaticMarkup(
        React.createElement(Badge, { variant: "positive" }, "PROFIT")
      );
      expect(html).toContain("color:#4CAF7D");
    });

    it("renders negative badge", () => {
      const html = renderToStaticMarkup(
        React.createElement(Badge, { variant: "negative" }, "LOSS")
      );
      expect(html).toContain("color:#E15252");
    });

    it("renders warning badge", () => {
      const html = renderToStaticMarkup(
        React.createElement(Badge, { variant: "warning" }, "CAUTION")
      );
      expect(html).toContain("color:#F59E0B");
    });

    it("renders info badge", () => {
      const html = renderToStaticMarkup(
        React.createElement(Badge, { variant: "info" }, "INFO")
      );
      expect(html).toContain("color:#22D3EE");
    });
  });

  describe("Chip", () => {
    it("renders unselected chip", () => {
      const html = renderToStaticMarkup(
        React.createElement(Chip, { value: "a" }, "Chip A")
      );
      expect(html).toContain("Chip A");
    });

    it("renders selected chip", () => {
      const html = renderToStaticMarkup(
        React.createElement(Chip, { selected: true, value: "a" }, "Chip A")
      );
      expect(html).toContain("color:#C9A15A");
    });
  });

  describe("SegmentedControl", () => {
    const options = [
      { value: "all", label: "All" },
      { value: "open", label: "Open" },
      { value: "closed", label: "Closed" },
    ];

    it("renders all options", () => {
      const html = renderToStaticMarkup(
        React.createElement(SegmentedControl, {
          options,
          value: "all",
          onChange: () => {},
          "aria-label": "Filter",
        })
      );
      expect(html).toContain("All");
      expect(html).toContain("Open");
      expect(html).toContain("Closed");
    });

    it("marks selected option", () => {
      const html = renderToStaticMarkup(
        React.createElement(SegmentedControl, {
          options,
          value: "open",
          onChange: () => {},
          "aria-label": "Filter",
        })
      );
      expect(html).toContain('aria-selected="true"');
    });
  });

  describe("ChartContainer", () => {
    it("renders title and children", () => {
      const html = renderToStaticMarkup(
        React.createElement(ChartContainer, { title: "GEX Profile" }, "chart-content")
      );
      expect(html).toContain("GEX Profile");
      expect(html).toContain("chart-content");
    });

    it("renders eyebrow and caption", () => {
      const html = renderToStaticMarkup(
        React.createElement(ChartContainer, {
          title: "Test",
          eyebrow: "MARKET STATE",
          caption: "Not a trading signal",
        }, "content")
      );
      expect(html).toContain("MARKET STATE");
      expect(html).toContain("Not a trading signal");
    });

    it("renders source", () => {
      const html = renderToStaticMarkup(
        React.createElement(ChartContainer, { title: "Test", source: "NSE" }, "content")
      );
      expect(html).toContain("NSE");
    });
  });

  describe("EmptyState", () => {
    it("renders default message", () => {
      const html = renderToStaticMarkup(React.createElement(EmptyState));
      expect(html).toContain("No data available.");
    });

    it("renders custom message", () => {
      const html = renderToStaticMarkup(
        React.createElement(EmptyState, { message: "No positions open." })
      );
      expect(html).toContain("No positions open.");
    });
  });

  describe("LoadingState", () => {
    it("renders default message", () => {
      const html = renderToStaticMarkup(React.createElement(LoadingState));
      expect(html).toContain("Loading...");
    });

    it("renders custom message", () => {
      const html = renderToStaticMarkup(
        React.createElement(LoadingState, { message: "Fetching data..." })
      );
      expect(html).toContain("Fetching data...");
    });
  });

  describe("ErrorState", () => {
    it("renders default message", () => {
      const html = renderToStaticMarkup(React.createElement(ErrorState));
      expect(html).toContain("Unable to load data.");
    });

    it("renders custom message", () => {
      const html = renderToStaticMarkup(
        React.createElement(ErrorState, { message: "Connection failed." })
      );
      expect(html).toContain("Connection failed.");
    });

    it("renders retry button when onRetry provided", () => {
      const html = renderToStaticMarkup(
        React.createElement(ErrorState, { onRetry: () => {} })
      );
      expect(html).toContain("Retry");
    });

    it("hides retry button when onRetry not provided", () => {
      const html = renderToStaticMarkup(React.createElement(ErrorState));
      expect(html).not.toContain("Retry");
    });
  });

  describe("ActionButton", () => {
    it("renders primary button", () => {
      const html = renderToStaticMarkup(
        React.createElement(ActionButton, null, "Execute")
      );
      expect(html).toContain("Execute");
    });

    it("renders secondary button", () => {
      const html = renderToStaticMarkup(
        React.createElement(ActionButton, { variant: "secondary" }, "Cancel")
      );
      expect(html).toContain("Cancel");
    });

    it("renders destructive button", () => {
      const html = renderToStaticMarkup(
        React.createElement(ActionButton, { variant: "destructive" }, "Delete")
      );
      expect(html).toContain("Delete");
    });

    it("renders disabled state", () => {
      const html = renderToStaticMarkup(
        React.createElement(ActionButton, { disabled: true }, "Disabled")
      );
      expect(html).toContain("not-allowed");
      expect(html).toContain("0.45");
    });

    it("renders all sizes", () => {
      ["sm", "md", "lg"].forEach((size) => {
        const html = renderToStaticMarkup(
          React.createElement(ActionButton, { size }, `Btn ${size}`)
        );
        expect(html).toContain(`Btn ${size}`);
      });
    });
  });
});
