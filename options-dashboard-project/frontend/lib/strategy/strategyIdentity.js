// Strategy identity model.
//
// A strategy is the named, dated container around a set of legs:
//
//   {
//     id,            // stable unique id (survives edits; new on load/new)
//     name,          // user-visible name ("Bull Call Spread", "My Hedge", ...)
//     underlying,    // symbol (NIFTY, BANKNIFTY, ...)
//     primaryExpiry, // the builder's selected expiry date
//     legs,          // canonical leg records (see ./strategy.js)
//     source,        // "template" | "modified" | "custom" | "draft" | "saved"
//     status,        // "draft" | "review" | "executed"
//     createdAt,
//     updatedAt,
//   }
//
// This is a pure domain module: no React, no side effects. The builder page
// keeps the raw pieces in state (legs, name, ...) and derives the live
// strategy with `deriveStrategy`; anything that needs a *persistent* identity
// (drafts, saved strategies, execution records) snapshots the fields it needs
// through the same helpers so every consumer sees one consistent shape.

export const STRATEGY_SOURCES = ["template", "modified", "custom", "draft", "saved"];

export const STRATEGY_STATUSES = ["draft", "review", "executed"];

export const STRATEGY_SOURCE_LABELS = {
  template: "TEMPLATE",
  modified: "MODIFIED",
  custom: "CUSTOM",
  draft: "DRAFT",
  saved: "SAVED",
};

// A fresh, collision-resistant strategy id.
export function newStrategyId(prefix = "strategy") {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

// Build a strategy from scratch (e.g. when loading a template, starting a
// custom build, or restoring a draft/saved strategy).
export function createStrategy({
  id,
  name,
  underlying = null,
  primaryExpiry = null,
  legs = [],
  source = "custom",
  status = "draft",
  createdAt,
} = {}) {
  const now = new Date().toISOString();
  return {
    id: id ?? newStrategyId(),
    name: name ?? "Custom Strategy",
    underlying,
    primaryExpiry,
    legs,
    source: STRATEGY_SOURCES.includes(source) ? source : "custom",
    status: STRATEGY_STATUSES.includes(status) ? status : "draft",
    createdAt: createdAt ?? now,
    updatedAt: now,
  };
}

// Derive the live strategy from builder state. Identity fields (id, source,
// createdAt) are passed through unchanged so the strategy keeps its identity
// across edits; `updatedAt` always reflects the latest change.
export function deriveStrategy({ id, name, underlying, primaryExpiry, legs = [], source = "custom", createdAt = null, status = "draft" } = {}) {
  return {
    id: id ?? newStrategyId(),
    name: name ?? "Custom Strategy",
    underlying: underlying ?? null,
    primaryExpiry: primaryExpiry ?? null,
    legs,
    source: STRATEGY_SOURCES.includes(source) ? source : "custom",
    status: STRATEGY_STATUSES.includes(status) ? status : "draft",
    createdAt: createdAt ?? new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

// Editing a template (or a saved template) makes it a modified strategy — the
// name is kept, only the source changes, so the user is never surprised by a
// renamed strategy after a small tweak. Custom/draft strategies are already
// user-owned and are returned unchanged.
export function markModified(strategy) {
  if (strategy.source === "template" || strategy.source === "saved") {
    return { ...strategy, source: "modified" };
  }
  return strategy;
}

// Compact display label for a source ("template" → "TEMPLATE").
export function strategySourceLabel(source) {
  return STRATEGY_SOURCE_LABELS[source] ?? STRATEGY_SOURCE_LABELS.custom;
}

// Snapshot for persistence (drafts / saved strategies): everything needed to
// reconstruct the strategy later. `legs` are copied so later builder edits can
// never mutate a stored snapshot.
export function serializeStrategy(strategy) {
  return {
    id: strategy.id,
    name: strategy.name,
    underlying: strategy.underlying,
    primaryExpiry: strategy.primaryExpiry,
    legs: strategy.legs.map((l) => ({ ...l })),
    source: strategy.source,
    createdAt: strategy.createdAt,
    updatedAt: strategy.updatedAt,
  };
}
