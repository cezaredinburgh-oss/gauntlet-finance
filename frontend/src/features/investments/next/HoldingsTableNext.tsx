import { useMemo, useState } from "react";
import { Layers } from "lucide-react";
import type { TickerDigest } from "../../../api/types";
import { formatQty, formatUsd } from "../../../lib/money";
import { cn } from "../../../lib/cn";
import {
  type HoldingsAssetFilter,
  type HoldingsSortColumn,
  type HoldingsSortMode,
  taxFreeSharePct,
} from "../holdingsSort";
import {
  compareNextHoldingsColumn,
  resolvePersistedNextSort,
  savePersistedNextSort,
  type NextSortColumn,
  type NextSortDir,
} from "./holdingsCompare";

function SortTh({
  label,
  col,
  activeCol,
  dir,
  onSort,
  align = "left",
  title,
  className,
}: {
  label: string;
  col: NextSortColumn;
  activeCol: NextSortColumn;
  dir: NextSortDir;
  onSort: (col: NextSortColumn) => void;
  align?: "left" | "right";
  title?: string;
  className?: string;
}) {
  const active = activeCol === col;
  return (
    <th
      className={cn(
        "cursor-pointer select-none px-2 py-2 font-medium transition hover:text-ink",
        align === "right" ? "text-right" : "text-left",
        active ? "text-brand" : "text-ink-faint",
        className,
      )}
      title={title}
      onClick={() => onSort(col)}
    >
      {label}
      {active ? (
        <span className="ml-0.5 text-[10px] opacity-80">{dir === "asc" ? "↑" : "↓"}</span>
      ) : null}
    </th>
  );
}

function platformTooltip(t: TickerDigest): string {
  const sources = t.by_platform.map((p) => p.source).filter(Boolean);
  return sources.length ? sources.join("\n") : "Multi-platform";
}

function taxFreeTooltip(t: TickerDigest): string {
  if (!t.tax_tranches.length) return "Tax-free share of position (MV when priced)";
  return t.tax_tranches.map((x) => `${x.label}: ${formatQty(x.quantity)}`).join("\n");
}

/**
 * Lab next Verify table. Owns sort so qty / last / honest MV work without
 * widening classic HoldingsSortColumn or using compareHoldingsColumn.
 */
export function HoldingsTableNext({
  rows,
  selectedTicker,
  onSelect,
  assetFilter,
  onAssetFilter,
  totalCount,
}: {
  rows: TickerDigest[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  /** Kept so PR3 page wiring typechecks; Verify owns sort below. */
  sortColumn: HoldingsSortColumn;
  sortDir: "asc" | "desc";
  onSortColumn: (col: HoldingsSortColumn) => void;
  /** Wealth-only in PR5 — hidden on this Verify default. */
  performanceMode: HoldingsSortMode;
  onPerformanceMode: (mode: HoldingsSortMode) => void;
  assetFilter: HoldingsAssetFilter;
  onAssetFilter: (f: HoldingsAssetFilter) => void;
  totalCount: number;
}) {
  const [sort, setSort] = useState(resolvePersistedNextSort);
  const { column: sortColumn, dir: sortDir } = sort;

  function onSort(col: NextSortColumn) {
    const nextDir: NextSortDir =
      sortColumn === col
        ? sortDir === "asc"
          ? "desc"
          : "asc"
        : col === "ticker"
          ? "asc"
          : "desc";
    setSort({ column: col, dir: nextDir });
    savePersistedNextSort(col, nextDir);
  }

  const sortedRows = useMemo(
    () => [...rows].sort((a, b) => compareNextHoldingsColumn(a, b, sortColumn, sortDir)),
    [rows, sortColumn, sortDir],
  );

  return (
    <div className="card flex flex-col">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-white/5 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold tracking-tight">Holdings</h2>
          <p className="text-xs text-ink-faint">
            Scan positions · select a row to verify qty & platforms
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-lg border border-white/10 bg-white/[0.03] p-0.5">
            {(
              [
                ["all", "All"],
                ["stock", "Stocks"],
                ["crypto", "Crypto"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => onAssetFilter(id)}
                className={cn(
                  "rounded-md px-2 py-1 text-[11px] font-semibold transition",
                  assetFilter === id
                    ? "bg-brand/20 text-brand"
                    : "text-ink-faint hover:text-ink-muted",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <span className="badge bg-white/5 text-ink-muted">
            {rows.length}
            {rows.length !== totalCount ? ` / ${totalCount}` : ""} tickers
          </span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[48rem] text-left text-xs">
          <thead>
            <tr className="border-b border-white/10">
              <SortTh
                label="Ticker"
                col="ticker"
                activeCol={sortColumn}
                dir={sortDir}
                onSort={onSort}
              />
              <SortTh
                label="Qty"
                col="qty"
                activeCol={sortColumn}
                dir={sortDir}
                onSort={onSort}
                align="right"
                title="Fee-net quantity on open lots"
              />
              <SortTh
                label="Platforms"
                col="platforms"
                activeCol={sortColumn}
                dir={sortDir}
                onSort={onSort}
                title="Broker / venue split"
              />
              <SortTh
                label="Last / as-of"
                col="last"
                activeCol={sortColumn}
                dir={sortDir}
                onSort={onSort}
                align="right"
                title="Live mark and as-of — not cost"
              />
              <SortTh
                label="MV"
                col="mv"
                activeCol={sortColumn}
                dir={sortDir}
                onSort={onSort}
                align="right"
                title="Market value — unpriced rows show labeled cost, not a quote"
              />
              <SortTh
                label="FIFO avg"
                col="fifoAvg"
                activeCol={sortColumn}
                dir={sortDir}
                onSort={onSort}
                align="right"
                title="Average cost per unit (FIFO)"
              />
              <SortTh
                label="Tax-free"
                col="unlock"
                activeCol={sortColumn}
                dir={sortDir}
                onSort={onSort}
                align="right"
                className="min-w-[5.5rem] px-3"
                title="Tax-free share of position (MV when priced)"
              />
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {sortedRows.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-ink-faint">
                  No holdings match this filter.
                </td>
              </tr>
            ) : (
              sortedRows.map((t) => {
                const active = selectedTicker === t.ticker;
                const freePct = taxFreeSharePct(t);
                const noQuote = t.missing_price || t.price_usd == null;
                return (
                  <tr
                    key={t.ticker}
                    role="button"
                    tabIndex={0}
                    onClick={() => onSelect(t.ticker)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onSelect(t.ticker);
                      }
                    }}
                    className={cn(
                      "cursor-pointer transition",
                      active
                        ? "bg-brand/15 ring-1 ring-inset ring-brand/30"
                        : "hover:bg-white/[0.04]",
                    )}
                  >
                    <td className="px-2 py-2">
                      <div className="font-semibold text-ink">{t.ticker}</div>
                      {t.asset_class ? (
                        <div className="text-[10px] text-ink-faint">{t.asset_class}</div>
                      ) : null}
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums font-medium">
                      {formatQty(t.quantity_total)}
                    </td>
                    <td className="px-2 py-2">
                      {t.multi_platform ? (
                        <span
                          className="inline-flex items-center text-ink-muted"
                          title={platformTooltip(t)}
                        >
                          <Layers className="h-3.5 w-3.5" />
                        </span>
                      ) : (
                        <span className="text-[11px] text-ink-faint">
                          {t.by_platform[0]?.source ?? "—"}
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-right">
                      {noQuote ? (
                        <span className="inline-flex rounded-md bg-warn/15 px-1.5 py-0.5 text-[10px] font-semibold text-warn">
                          No quote
                        </span>
                      ) : (
                        <>
                          <div className="tabular-nums font-medium">
                            {formatUsd(t.price_usd)}
                          </div>
                          {t.price_as_of ? (
                            <div className="text-[10px] tabular-nums text-ink-faint">
                              {t.price_as_of}
                            </div>
                          ) : null}
                        </>
                      )}
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums font-medium">
                      {t.market_value_usd != null ? (
                        formatUsd(t.market_value_usd)
                      ) : (
                        <span
                          className="block text-ink-faint"
                          title="No live quote — not market value"
                        >
                          <span className="text-[10px] font-semibold uppercase tracking-wide">
                            COST ·{" "}
                          </span>
                          {formatUsd(t.cost_basis_usd)}
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums text-ink-muted">
                      {formatUsd(t.avg_cost_usd)}
                    </td>
                    <td className="min-w-[5.5rem] px-3 py-2 text-right text-xs">
                      {freePct != null ? (
                        <span
                          className={
                            freePct >= 100
                              ? "text-ok"
                              : freePct <= 0
                                ? "text-warn"
                                : "text-ink-muted"
                          }
                          title={taxFreeTooltip(t)}
                        >
                          {freePct.toFixed(freePct % 1 === 0 ? 0 : 1)}%
                        </span>
                      ) : (
                        <span className="text-ink-faint" title={taxFreeTooltip(t)}>
                          —
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
