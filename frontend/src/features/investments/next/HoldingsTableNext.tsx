import { Layers } from "lucide-react";
import type { TickerDigest } from "../../../api/types";
import { d, formatQty, formatUsd } from "../../../lib/money";
import { cn } from "../../../lib/cn";
import { gradeStyleClass } from "../gradeStyles";
import {
  type HoldingsAssetFilter,
  type HoldingsSortColumn,
  type HoldingsSortMode,
  taxFreeSharePct,
} from "../holdingsSort";

function pctCell(pct: number | null | undefined, suffix = "%") {
  if (pct == null) return <span className="text-ink-faint">—</span>;
  return (
    <span className={cn("tabular-nums", pct >= 0 ? "text-ok" : "text-danger")}>
      {pct >= 0 ? "+" : ""}
      {pct.toFixed(1)}
      {suffix}
    </span>
  );
}

function SortTh({
  label,
  col,
  activeCol,
  dir,
  onSort,
  align = "left",
  title,
}: {
  label: string;
  col: HoldingsSortColumn;
  activeCol: HoldingsSortColumn;
  dir: "asc" | "desc";
  onSort: (col: HoldingsSortColumn) => void;
  align?: "left" | "right";
  title?: string;
}) {
  const active = activeCol === col;
  return (
    <th
      className={cn(
        "cursor-pointer select-none px-2 py-2 font-medium transition hover:text-ink",
        align === "right" ? "text-right" : "text-left",
        active ? "text-brand" : "text-ink-faint",
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

export function HoldingsTableNext({
  rows,
  selectedTicker,
  onSelect,
  sortColumn,
  sortDir,
  onSortColumn,
  performanceMode,
  onPerformanceMode,
  assetFilter,
  onAssetFilter,
  totalCount,
}: {
  rows: TickerDigest[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  sortColumn: HoldingsSortColumn;
  sortDir: "asc" | "desc";
  onSortColumn: (col: HoldingsSortColumn) => void;
  performanceMode: HoldingsSortMode;
  onPerformanceMode: (mode: HoldingsSortMode) => void;
  assetFilter: HoldingsAssetFilter;
  onAssetFilter: (f: HoldingsAssetFilter) => void;
  totalCount: number;
}) {
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
          <div className="flex rounded-lg border border-white/10 bg-white/[0.03] p-0.5">
            <button
              type="button"
              onClick={() => onPerformanceMode("total")}
              className={cn(
                "rounded-md px-2 py-1 text-[11px] font-semibold transition",
                performanceMode === "total"
                  ? "bg-brand/20 text-brand"
                  : "text-ink-faint hover:text-ink-muted",
              )}
              title="Sort ROI column by total unrealized %"
            >
              Total
            </button>
            <button
              type="button"
              onClick={() => onPerformanceMode("annualized")}
              className={cn(
                "rounded-md px-2 py-1 text-[11px] font-semibold transition",
                performanceMode === "annualized"
                  ? "bg-brand/20 text-brand"
                  : "text-ink-faint hover:text-ink-muted",
              )}
              title="Sort ROI column by annualized open ROI %"
            >
              Ann.
            </button>
          </div>
          <span className="badge bg-white/5 text-ink-muted">
            {rows.length}
            {rows.length !== totalCount ? ` / ${totalCount}` : ""} tickers
          </span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-left text-xs">
          <thead>
            <tr className="border-b border-white/10">
              <SortTh
                label="Ticker"
                col="ticker"
                activeCol={sortColumn}
                dir={sortDir}
                onSort={onSortColumn}
              />
              <SortTh
                label="MV"
                col="mv"
                activeCol={sortColumn}
                dir={sortDir}
                onSort={onSortColumn}
                align="right"
              />
              <SortTh
                label="Cost"
                col="cost"
                activeCol={sortColumn}
                dir={sortDir}
                onSort={onSortColumn}
                align="right"
              />
              <SortTh
                label={performanceMode === "annualized" ? "ROI ann." : "ROI"}
                col="unrealized"
                activeCol={sortColumn}
                dir={sortDir}
                onSort={onSortColumn}
                align="right"
                title={
                  performanceMode === "annualized"
                    ? "Annualized open ROI %"
                    : "Total unrealized ROI %"
                }
              />
              <SortTh
                label="Wt"
                col="weight"
                activeCol={sortColumn}
                dir={sortDir}
                onSort={onSortColumn}
                align="right"
              />
              <SortTh
                label="Grade"
                col="grade"
                activeCol={sortColumn}
                dir={sortDir}
                onSort={onSortColumn}
                align="right"
              />
              <SortTh
                label="Tax-free"
                col="unlock"
                activeCol={sortColumn}
                dir={sortDir}
                onSort={onSortColumn}
                align="right"
                title="Sort by tax-free share of MV (then next unlock date)"
              />
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-ink-faint">
                  No holdings match this filter.
                </td>
              </tr>
            ) : (
              rows.map((t) => {
                const active = selectedTicker === t.ticker;
                const roi =
                  performanceMode === "annualized"
                    ? t.annualized_unrealized_pct
                    : t.unrealized_pct;
                const freePct = taxFreeSharePct(t);
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
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold text-ink">{t.ticker}</span>
                        {t.multi_platform && (
                          <span title="Multi-platform">
                            <Layers className="h-3 w-3 text-ink-faint" />
                          </span>
                        )}
                        {t.missing_price && (
                          <span className="text-[10px] text-warn">no px</span>
                        )}
                      </div>
                      <div className="text-[10px] text-ink-faint">
                        {formatQty(t.quantity_total)}
                        {t.asset_class ? ` · ${t.asset_class}` : ""}
                      </div>
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums font-medium">
                      {t.market_value_usd != null ? (
                        formatUsd(t.market_value_usd)
                      ) : (
                        <span
                          className="text-ink-faint"
                          title="No live quote — showing cost basis, not market value"
                        >
                          <span className="block text-[10px] font-normal uppercase tracking-wide">
                            cost
                          </span>
                          {formatUsd(t.cost_basis_usd)}
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums text-ink-muted">
                      {formatUsd(t.cost_basis_usd)}
                    </td>
                    <td className="px-2 py-2 text-right">
                      {pctCell(roi)}
                      {t.unrealized_usd != null && performanceMode === "total" && (
                        <div className="text-[10px] text-ink-faint">
                          {d(t.unrealized_usd) >= 0 ? "+" : ""}
                          {formatUsd(t.unrealized_usd)}
                        </div>
                      )}
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums text-ink-muted">
                      {t.portfolio_weight_pct.toFixed(1)}%
                    </td>
                    <td className="px-2 py-2 text-right">
                      <span
                        className={cn(
                          "inline-flex h-6 min-w-[1.5rem] items-center justify-center rounded-md px-1 text-[11px] font-bold ring-1",
                          gradeStyleClass(t.roi_grade),
                        )}
                        title={t.roi_grade_label}
                      >
                        {t.roi_grade}
                      </span>
                    </td>
                    <td className="px-2 py-2 text-right text-[11px]">
                      {freePct != null ? (
                        <span
                          className={
                            freePct >= 100
                              ? "text-ok"
                              : freePct <= 0
                                ? "text-warn"
                                : "text-ink-muted"
                          }
                          title="Tax-free share of position (MV when priced)"
                        >
                          {freePct.toFixed(freePct % 1 === 0 ? 0 : 1)}%
                        </span>
                      ) : (
                        <span className="text-ink-faint">—</span>
                      )}
                      {t.next_unlock_date && (
                        <div className="text-[10px] text-warn tabular-nums">
                          {t.next_unlock_date}
                        </div>
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
