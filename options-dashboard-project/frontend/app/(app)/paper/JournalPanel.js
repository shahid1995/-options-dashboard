"use client";
import { C, fmtIN } from "@/lib/ui";
import { Metric, Badge, Table, EmptyState, LoadingState, ActionButton } from "@/components/app/core";

const JOURNAL_PAGE_SIZE = 10;

const fmtJournalDate = (iso) =>
  iso
    ? new Date(iso).toLocaleString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

const panel = {
  background: C.surface,
  border: `1px solid ${C.border}`,
  borderRadius: 10,
  padding: 18,
  minWidth: 0,
};

export { fmtJournalDate, JOURNAL_PAGE_SIZE };

export default function JournalPanel({
  journal,
  journalError,
  paperHistory = [],
  journalPage,
  onPageChange,
  onExportCsv,
  perStrategy = [],
}) {
  const journalIds = new Set((journal?.trades ?? []).map((t) => String(t.id)));
  const localOnly = paperHistory.filter((h) => !(h.tradeId && journalIds.has(String(h.tradeId))));
  const logRows = journal
    ? [...journal.trades, ...localOnly.map((h) => ({ local: true, ...h }))]
    : journalError
      ? paperHistory.map((h) => ({ local: true, ...h }))
      : [];

  const logPageCount = Math.max(1, Math.ceil(logRows.length / JOURNAL_PAGE_SIZE));
  const logPage = Math.min(journalPage, logPageCount - 1);
  const logPageRows = logRows.slice(logPage * JOURNAL_PAGE_SIZE, logPage * JOURNAL_PAGE_SIZE + JOURNAL_PAGE_SIZE);

  const tableData = logPageRows.map((r) => {
    if (r.local) {
      return {
        id: `local-${r.entryTime}-${r.tradeId ?? "noid"}`,
        _sortKey: r.entryTime,
        status: "CLOSED",
        statusSemantic: r.realizedPnl >= 0 ? "positive" : "negative",
        strategyTag: r.strategyName ?? "Custom",
        symbol: r.symbol,
        legs: `${r.action.toUpperCase()} ${fmtIN(r.strike)} ${r.type === "call" ? "CE" : "PE"}×${r.qty}`,
        netEntry: `Entry ${fmtIN(r.entryPremium, 2)}`,
        netEntrySemantic: "neutral",
        realizedPnl: r.realizedPnl,
        realizedPnlFormatted: `${r.realizedPnl >= 0 ? "+" : ""}₹${fmtIN(r.realizedPnl, 2)}`,
        realizedPnlSemantic: r.realizedPnl >= 0 ? "positive" : "negative",
        openedAt: fmtJournalDate(r.entryTime),
        closedAt: fmtJournalDate(r.exitTime),
      };
    }
    const realized = r.realized_pnl;
    const credit = r.entry_net < 0;
    return {
      id: `server-${r.id}`,
      _sortKey: r.entry_at,
      status: r.status,
      statusSemantic: r.status === "open" ? "strategy" : realized >= 0 ? "positive" : "negative",
      strategyTag: r.strategy_tag,
      symbol: r.symbol,
      legs: r.legs
        .map((l) => `${l.action === "sell" ? "S" : "B"} ${fmtIN(l.strike_price)} ${l.option_type === "call" ? "CE" : "PE"}×${l.quantity}`)
        .join(" · "),
      netEntry: credit ? `Credit ${fmtIN(Math.abs(r.entry_net), 2)}` : `Debit ${fmtIN(r.entry_net, 2)}`,
      netEntrySemantic: credit ? "positive" : "neutral",
      realizedPnl: realized,
      realizedPnlFormatted: realized == null ? "—" : `${realized >= 0 ? "+" : ""}₹${fmtIN(realized, 2)}`,
      realizedPnlSemantic: realized == null ? "neutral" : realized >= 0 ? "positive" : "negative",
      openedAt: fmtJournalDate(r.entry_at),
      closedAt: r.exit_at ? fmtJournalDate(r.exit_at) : "—",
    };
  });

  const columns = [
    {
      key: "status",
      header: "Status",
      render: (v, row) => <Badge variant={row.statusSemantic}>{v}</Badge>,
    },
    {
      key: "strategyTag",
      header: "Strategy Tag",
      render: (v, row) => (
        <div>
          <div style={{ fontWeight: 700 }}>{v}</div>
          <div style={{ color: C.faint, fontSize: 11 }}>{row.symbol}</div>
        </div>
      ),
    },
    {
      key: "legs",
      header: "Strike / Legs",
      render: (v) => <span style={{ color: C.muted }}>{v}</span>,
    },
    {
      key: "netEntry",
      header: "Net Entry",
      align: "right",
      render: (v, row) => (
        <span style={{ color: row.netEntrySemantic === "positive" ? C.green : C.muted }}>{v}</span>
      ),
    },
    {
      key: "realizedPnlFormatted",
      header: "Realized P&L",
      align: "right",
      render: (v, row) => (
        <span style={{ color: row.realizedPnlSemantic === "positive" ? C.green : row.realizedPnlSemantic === "negative" ? C.red : C.muted }}>{v}</span>
      ),
    },
    {
      key: "openedAt",
      header: "Opened",
      render: (v) => <span style={{ color: C.muted, fontSize: 11.5 }}>{v}</span>,
    },
    {
      key: "closedAt",
      header: "Closed",
      render: (v) => <span style={{ color: C.muted, fontSize: 11.5 }}>{v}</span>,
    },
  ];

  const stats = journal?.stats ?? {};
  const winRate = stats.closed_trades ? `${((stats.win_rate ?? 0) * 100).toFixed(1)}%` : "—";
  const profitFactor = stats.profit_factor != null ? stats.profit_factor.toFixed(2) : "—";
  const closedTrades = stats.closed_trades ?? "—";

  return (
    <div style={{ marginTop: 14, ...panel }} role="region" aria-label="Transaction log and historical journal">
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 14,
          flexWrap: "wrap",
          gap: 10,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <div style={{ fontSize: 13, fontWeight: 800, letterSpacing: 0.5, color: C.text }}>
            📝 TRANSACTION LOG & HISTORICAL JOURNAL
          </div>
          {logRows.length > 0 && <Badge variant="neutral">{logRows.length} records</Badge>}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          {paperHistory.length > 0 && (
            <ActionButton variant="secondary" size="sm" onClick={onExportCsv}>
              Export CSV
            </ActionButton>
          )}
          {logRows.length > JOURNAL_PAGE_SIZE && (
            <nav aria-label="Journal pagination" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <ActionButton
                variant="secondary"
                size="sm"
                onClick={() => onPageChange(Math.max(0, logPage - 1))}
                disabled={logPage === 0}
                aria-label="Previous page"
              >
                ← Prev
              </ActionButton>
              <span style={{ fontSize: 11, color: C.muted }}>
                Page {logPage + 1} / {logPageCount} · {logRows.length} rows
              </span>
              <ActionButton
                variant="secondary"
                size="sm"
                onClick={() => onPageChange(Math.min(logPageCount - 1, logPage + 1))}
                disabled={logPage >= logPageCount - 1}
                aria-label="Next page"
              >
                Next →
              </ActionButton>
            </nav>
          )}
        </div>
      </div>

      {/* Performance summary */}
      {journal?.stats && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
            gap: 12,
            marginBottom: 14,
          }}
        >
          <Metric label="Win rate" value={winRate} size="sm" />
          <Metric label="Profit factor" value={profitFactor} size="sm" />
          <Metric label="Closed trades" value={closedTrades} size="sm" />
        </div>
      )}

      {/* Per-strategy summary */}
      {perStrategy.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
          {perStrategy.map((s) => (
            <span
              key={s.strategyName}
              style={{
                fontSize: 10.5,
                color: C.muted,
                background: C.surface2,
                border: `1px solid ${C.border}`,
                borderRadius: 999,
                padding: "3px 10px",
              }}
            >
              {s.strategyName} · {s.trades} closed · {(s.winRate * 100).toFixed(0)}% win ·{" "}
              <span style={{ color: s.totalPnl >= 0 ? C.green : C.red, fontWeight: 600 }}>
                ₹{fmtIN(s.totalPnl, 2)}
              </span>
            </span>
          ))}
        </div>
      )}

      {/* Content states */}
      {journal === null && !journalError ? (
        <LoadingState message="Loading journal…" />
      ) : (
        <>
          {journalError && (
            <div style={{ fontSize: 11.5, color: C.muted, marginBottom: 10, lineHeight: 1.6 }}>
              Journal sync is unavailable right now ({journalError}). Showing this browser's local history — local paper
              trading still works, and fills will log to the database once the backend is reachable.
            </div>
          )}
          {logRows.length === 0 ? (
            <EmptyState
              message={
                journalError
                  ? "No closed trades in this browser yet."
                  : "No journal entries yet — submit a paper order and it will be logged here automatically."
              }
            />
          ) : (
            <Table columns={columns} data={tableData} compact keyExtractor={(row) => row.id} />
          )}
        </>
      )}
    </div>
  );
}
