import { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { api, ApiError } from "../../../api/client";
import type { TaxTranche, TickerDigest, WindowPerformanceItem } from "../../../api/types";
import { d, formatQty, formatUsd, hasMoneyValue } from "../../../lib/money";
import { cn } from "../../../lib/cn";
import { gradeStyleClass } from "../gradeStyles";
import {
  type HoldingsAssetFilter,
  type HoldingsSortMode,
  taxFreeSharePct,
} from "../holdingsSort";
import {
  compareNextHoldingsColumn,
  savePersistedNextSort,
  type NextSortColumn,
  type NextSortDir,
} from "./holdingsCompare";
import {
  type HoldingsColumnView,
  VIEW_TABS,
  filterTickersByQuery,
  loadPersistedColumnView,
  resolvePersistedSortForView,
  savePersistedColumnView,
  uniqueGradeKeyPairs,
  viewForTaxRunwayFocus,
} from "./holdingsViews";

/** Copied from classic HoldingsDetailPanel — do not import that frozen file. */
const TAX_TRANCHE_COLORS: Record<string, string> = {
  now: "#2dd4a8",
  later_this_year: "#38bdf8",
  next_year: "#fbbf24",
  year_after: "#f87171",
};

const TRANCHE_KEYS = ["now", "later_this_year", "next_year", "year_after"] as const;

function SortTh({
  label,
  col,
  activeCol,
  dir,
  onSort,
  align = "center",
  title,
  className,
}: {
  label: string;
  col: NextSortColumn;
  activeCol: NextSortColumn;
  dir: NextSortDir;
  onSort: (col: NextSortColumn) => void;
  align?: "left" | "right" | "center";
  title?: string;
  className?: string;
}) {
  const active = activeCol === col;
  return (
    <th
      className={cn(
        "cursor-pointer select-none px-2 py-2 font-medium transition hover:text-ink",
        align === "right"
          ? "text-right"
          : align === "center"
            ? "text-center"
            : "text-left",
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

function taxFreeTooltip(t: TickerDigest): string {
  if (!t.tax_tranches.length) return "Tax-free share of position (MV when priced)";
  return t.tax_tranches.map((x) => `${x.label}: ${formatQty(x.quantity)}`).join("\n");
}

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

function TrancheMiniBar({ tranches }: { tranches: TaxTranche[] }) {
  const sumMv = tranches.reduce((s, x) => s + d(x.market_value_usd), 0);
  const useQty = sumMv <= 0;
  const denom = useQty
    ? tranches.reduce((s, x) => s + d(x.quantity), 0)
    : sumMv;
  if (denom <= 0 || tranches.length === 0) {
    return <span className="text-ink-faint">—</span>;
  }
  const byKey = new Map(tranches.map((x) => [x.key, x]));
  const known = new Set<string>(TRANCHE_KEYS);
  const ordered: TaxTranche[] = [
    ...TRANCHE_KEYS.map((k) => byKey.get(k)).filter((x): x is TaxTranche => x != null),
    ...tranches.filter((x) => !known.has(x.key)),
  ];
  return (
    <div className="flex h-2 w-20 overflow-hidden rounded-sm ring-1 ring-white/10">
      {ordered.map((x) => {
        const part = useQty ? d(x.quantity) : d(x.market_value_usd);
        if (part <= 0) return null;
        const pct = (part / denom) * 100;
        if (pct <= 0) return null;
        return (
          <div
            key={x.key}
            title={`${x.label}: ${formatUsd(x.market_value_usd)} · ${formatQty(x.quantity)}`}
            style={{
              width: `${pct}%`,
              background: TAX_TRANCHE_COLORS[x.key] || "#64748b",
            }}
            className="h-full"
          />
        );
      })}
    </div>
  );
}

function TickerCell({ t, subtitle }: { t: TickerDigest; subtitle?: string }) {
  return (
    <td className="px-2 py-2 text-left">
      <div className="font-semibold text-ink">{t.ticker}</div>
      {t.asset_class ? (
        <div className="text-[10px] text-ink-faint">{t.asset_class}</div>
      ) : null}
      {subtitle ? <div className="text-[10px] text-ink-faint">{subtitle}</div> : null}
    </td>
  );
}

function HonestMvCell({ t }: { t: TickerDigest }) {
  return (
    <td className="px-2 py-2 text-center tabular-nums font-medium">
      {t.market_value_usd != null ? (
        formatUsd(t.market_value_usd)
      ) : (
        <span className="block text-ink-faint" title="No live quote — not market value">
          <span className="text-[10px] font-semibold uppercase tracking-wide">COST · </span>
          {formatUsd(t.cost_basis_usd)}
        </span>
      )}
    </td>
  );
}

function TaxFreeCell({
  t,
  highlight,
}: {
  t: TickerDigest;
  highlight?: boolean;
}) {
  const freePct = taxFreeSharePct(t);
  return (
    <td
      className={cn(
        "px-2 py-2 text-center text-xs",
        highlight && "ring-2 ring-brand/50",
      )}
    >
      {freePct != null ? (
        <span
          className={
            freePct >= 100 ? "text-ok" : freePct <= 0 ? "text-warn" : "text-ink-muted"
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
  );
}

function perfForTicker(
  t: TickerDigest,
  map: Readonly<Record<string, WindowPerformanceItem>>,
): WindowPerformanceItem | undefined {
  return map[t.ticker.toUpperCase()];
}

function dayPnlDisplay(
  t: TickerDigest,
  perf: WindowPerformanceItem | undefined,
): number | null {
  if (perf && hasMoneyValue(perf.pnl_usd)) return d(perf.pnl_usd);
  if (perf && hasMoneyValue(perf.change_abs)) return d(t.quantity_total) * d(perf.change_abs);
  return null;
}

function signedUsdCell(value: number | null) {
  if (value == null) return <span className="text-ink-faint">—</span>;
  return (
    <span className={cn("tabular-nums", value >= 0 ? "text-ok" : "text-danger")}>
      {value >= 0 ? "+" : ""}
      {formatUsd(value)}
    </span>
  );
}

function priorDaySubtitle(status: string | null | undefined): string | undefined {
  if (status === "prior_session" || status === "prior_local_day") return "Prior day";
  return undefined;
}

/**
 * Lab next table. Owns Verify / Wealth / Tax / Daily presets + sort so hidden
 * columns cannot remain the active sort key.
 */
export function HoldingsTableNext({
  rows,
  selectedTicker,
  onSelect,
  performanceMode,
  onPerformanceMode,
  assetFilter,
  onAssetFilter,
  totalCount,
  highlightTaxFree = false,
}: {
  rows: TickerDigest[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  performanceMode: HoldingsSortMode;
  onPerformanceMode: (mode: HoldingsSortMode) => void;
  assetFilter: HoldingsAssetFilter;
  onAssetFilter: (f: HoldingsAssetFilter) => void;
  totalCount: number;
  highlightTaxFree?: boolean;
}) {
  const [view, setView] = useState<HoldingsColumnView>(() =>
    viewForTaxRunwayFocus(loadPersistedColumnView(), highlightTaxFree),
  );
  const [sort, setSort] = useState(() => {
    const initialView = viewForTaxRunwayFocus(
      loadPersistedColumnView(),
      highlightTaxFree,
    );
    if (highlightTaxFree) return { column: "unlock" as const, dir: "desc" as const };
    return resolvePersistedSortForView(initialView);
  });
  const [tickerQuery, setTickerQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [perfByTicker, setPerfByTicker] = useState<
    Readonly<Record<string, WindowPerformanceItem>>
  >({});
  const [perfError, setPerfError] = useState<string | null>(null);
  const [perfRefreshTick, setPerfRefreshTick] = useState(0);
  const rowEls = useRef(new Map<string, HTMLTableRowElement>());
  const taxFocusApplied = useRef(highlightTaxFree);
  const { column: sortColumn, dir: sortDir } = sort;

  useEffect(() => {
    if (!highlightTaxFree || taxFocusApplied.current) return;
    taxFocusApplied.current = true;
    setView((prev) => viewForTaxRunwayFocus(prev, true));
    setSort({ column: "unlock", dir: "desc" });
  }, [highlightTaxFree]);

  useEffect(() => {
    if (view !== "daily") return;
    let cancelled = false;
    void (async () => {
      try {
        const res = await api.priceWindowPerformance({ range: "1d" });
        if (cancelled) return;
        const map: Record<string, WindowPerformanceItem> = {};
        for (const it of res.items || []) {
          map[it.ticker.toUpperCase()] = it;
        }
        setPerfByTicker(map);
        setPerfError(null);
      } catch (e) {
        if (cancelled) return;
        setPerfByTicker({});
        setPerfError(e instanceof ApiError ? e.detail : e instanceof Error ? e.message : "Failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [view, perfRefreshTick]);

  useEffect(() => {
    const onPrices = (ev: Event) => {
      const soft =
        typeof CustomEvent !== "undefined" &&
        ev instanceof CustomEvent &&
        Boolean((ev.detail as { soft?: boolean } | undefined)?.soft);
      if (soft || view !== "daily") return;
      setPerfRefreshTick((n) => n + 1);
    };
    window.addEventListener("prices-updated", onPrices);
    return () => window.removeEventListener("prices-updated", onPrices);
  }, [view]);

  function onView(next: HoldingsColumnView) {
    setView(next);
    savePersistedColumnView(next);
    setSort(resolvePersistedSortForView(next));
  }

  function onSort(col: NextSortColumn) {
    const nextDir: NextSortDir =
      sortColumn === col
        ? sortDir === "asc"
          ? "desc"
          : "asc"
        : col === "ticker" || col === "grade"
          ? "asc"
          : "desc";
    setSort({ column: col, dir: nextDir });
    savePersistedNextSort(col, nextDir);
  }

  function pickTicker(ticker: string) {
    onSelect(ticker);
    window.requestAnimationFrame(() => {
      rowEls.current.get(ticker)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }

  const sortedRows = useMemo(
    () =>
      [...rows].sort((a, b) =>
        compareNextHoldingsColumn(
          a,
          b,
          sortColumn,
          sortDir,
          performanceMode,
          view === "daily" ? perfByTicker : undefined,
        ),
      ),
    [rows, sortColumn, sortDir, performanceMode, view, perfByTicker],
  );

  const matches = useMemo(
    () => filterTickersByQuery(sortedRows, tickerQuery),
    [sortedRows, tickerQuery],
  );

  const visibleRows = tickerQuery.trim() ? matches : sortedRows;
  const gradePairs = useMemo(
    () => (view === "wealth" ? uniqueGradeKeyPairs(rows) : []),
    [view, rows],
  );
  const colSpan = view === "wealth" ? 6 : 5;

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
          <div
            className="flex rounded-lg border border-white/10 bg-white/[0.03] p-0.5"
            role="group"
            aria-label="Column view"
          >
            {VIEW_TABS.map(({ id, label }) => (
              <button
                key={id}
                type="button"
                onClick={() => onView(id)}
                aria-pressed={view === id}
                className={cn(
                  "rounded-md px-2 py-1 text-[11px] font-semibold transition",
                  view === id
                    ? "bg-brand/20 text-brand"
                    : "text-ink-faint hover:text-ink-muted",
                )}
              >
                {label}
              </button>
            ))}
          </div>
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
          {view === "wealth" ? (
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
                title="Show total unrealized %"
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
                title="Show annualized open ROI %"
              >
                Ann.
              </button>
            </div>
          ) : null}
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-ink-faint" />
            <input
              type="search"
              value={tickerQuery}
              onChange={(e) => {
                setTickerQuery(e.target.value);
                setSearchOpen(true);
              }}
              onFocus={() => setSearchOpen(true)}
              onBlur={() => {
                window.setTimeout(() => setSearchOpen(false), 120);
              }}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  setTickerQuery("");
                  setSearchOpen(false);
                  return;
                }
                if (e.key === "Enter" && matches[0]) {
                  e.preventDefault();
                  pickTicker(matches[0].ticker);
                  setSearchOpen(false);
                }
              }}
              placeholder="Find ticker"
              aria-label="Find ticker"
              className="h-7 w-32 rounded-md border border-white/10 bg-white/[0.03] pl-6 pr-2 text-[11px] text-ink placeholder:text-ink-faint focus:border-brand/40 focus:outline-none"
            />
            {searchOpen && tickerQuery.trim() && matches.length > 0 ? (
              <ul
                className="absolute right-0 z-30 mt-1 max-h-48 w-40 overflow-auto rounded-md border border-white/10 bg-surface py-1 shadow-lg"
                role="listbox"
              >
                {matches.slice(0, 12).map((t) => (
                  <li key={t.ticker}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={selectedTicker === t.ticker}
                      className={cn(
                        "flex w-full px-2 py-1 text-left text-[11px] font-semibold",
                        selectedTicker === t.ticker
                          ? "bg-brand/15 text-brand"
                          : "text-ink hover:bg-white/[0.06]",
                      )}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => {
                        pickTicker(t.ticker);
                        setSearchOpen(false);
                      }}
                    >
                      {t.ticker}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
          <span className="badge bg-white/5 text-ink-muted">
            {visibleRows.length}
            {visibleRows.length !== totalCount ? ` / ${totalCount}` : ""} tickers
          </span>
        </div>
      </div>

      {view === "daily" && perfError ? (
        <div className="border-b border-warn/30 bg-warn/10 px-4 py-2 text-xs text-warn">
          {perfError}
        </div>
      ) : null}

      <div>
        <table className="w-full table-fixed text-center text-xs">
          <thead>
            <tr className="border-b border-white/10">
              {view === "verify" ? (
                <>
                  <SortTh
                    label="Ticker"
                    col="ticker"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    align="left"
                  />
                  <SortTh
                    label="Qty"
                    col="qty"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    title="Fee-net quantity on open lots"
                  />
                  <SortTh
                    label="MV"
                    col="mv"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    title="Market value — unpriced rows show labeled cost, not a quote"
                  />
                  <SortTh
                    label="FIFO avg"
                    col="fifoAvg"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    title="Average cost per unit (FIFO)"
                  />
                  <SortTh
                    label="Tax-free"
                    col="unlock"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    className={cn(highlightTaxFree && "ring-2 ring-brand/50")}
                    title="Tax-free share of position (MV when priced)"
                  />
                </>
              ) : null}
              {view === "wealth" ? (
                <>
                  <SortTh
                    label="Ticker"
                    col="ticker"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    align="left"
                  />
                  <SortTh
                    label="MV"
                    col="mv"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    title="Market value — unpriced rows show labeled cost, not a quote"
                  />
                  <SortTh
                    label="FIFO cost"
                    col="cost"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    title="Open FIFO cost basis"
                  />
                  <SortTh
                    label={performanceMode === "annualized" ? "Unreal. ann." : "Unrealized"}
                    col="unrealized"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    title={
                      performanceMode === "annualized"
                        ? "Annualized open ROI %"
                        : "Total unrealized $ / %"
                    }
                  />
                  <SortTh
                    label="Weight"
                    col="weight"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                  />
                  <SortTh
                    label="Grade"
                    col="grade"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    title="Total ROI grade — not tied to Total/Ann"
                  />
                </>
              ) : null}
              {view === "tax" ? (
                <>
                  <SortTh
                    label="Ticker"
                    col="ticker"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    align="left"
                  />
                  <SortTh
                    label="Qty"
                    col="qty"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    title="Fee-net quantity on open lots"
                  />
                  <SortTh
                    label="Tax-free"
                    col="unlock"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    className={cn(highlightTaxFree && "ring-2 ring-brand/50")}
                    title="Tax-free share of position (MV when priced)"
                  />
                  <SortTh
                    label="Tranche"
                    col="tranche"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    title="Tax-status mix (MV, qty if unpriced)"
                  />
                  <th
                    className="px-2 py-2 text-center font-medium text-ink-faint"
                    title="Next 1095 unlock"
                  >
                    Next unlock
                  </th>
                </>
              ) : null}
              {view === "daily" ? (
                <>
                  <SortTh
                    label="Ticker"
                    col="ticker"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    align="left"
                  />
                  <SortTh
                    label="Last"
                    col="last"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                  />
                  <SortTh
                    label="Day Δ $"
                    col="dayPnl"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    title="Mark P/L on current open qty × DayPolicy price move."
                  />
                  <SortTh
                    label="Day %"
                    col="dayPct"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    title="Mark P/L on current open qty × DayPolicy price move."
                  />
                  <SortTh
                    label="MV"
                    col="mv"
                    activeCol={sortColumn}
                    dir={sortDir}
                    onSort={onSort}
                    title="Market value — unpriced rows show labeled cost, not a quote"
                  />
                </>
              ) : null}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {visibleRows.length === 0 ? (
              <tr>
                <td colSpan={colSpan} className="px-3 py-8 text-center text-ink-faint">
                  No holdings match this filter.
                </td>
              </tr>
            ) : (
              visibleRows.map((t) => {
                const active = selectedTicker === t.ticker;
                const roi =
                  performanceMode === "annualized"
                    ? t.annualized_unrealized_pct
                    : t.unrealized_pct;
                const perf = view === "daily" ? perfForTicker(t, perfByTicker) : undefined;
                return (
                  <tr
                    key={t.ticker}
                    ref={(el) => {
                      if (el) rowEls.current.set(t.ticker, el);
                      else rowEls.current.delete(t.ticker);
                    }}
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
                    {view === "verify" ? (
                      <>
                        <TickerCell t={t} />
                        <td className="px-2 py-2 text-center tabular-nums font-medium">
                          {formatQty(t.quantity_total)}
                        </td>
                        <HonestMvCell t={t} />
                        <td className="px-2 py-2 text-center tabular-nums text-ink-muted">
                          {formatUsd(t.avg_cost_usd)}
                        </td>
                        <TaxFreeCell t={t} highlight={highlightTaxFree} />
                      </>
                    ) : null}
                    {view === "wealth" ? (
                      <>
                        <TickerCell t={t} />
                        <HonestMvCell t={t} />
                        <td className="px-2 py-2 text-center tabular-nums text-ink-muted">
                          {formatUsd(t.cost_basis_usd)}
                        </td>
                        <td className="px-2 py-2 text-center">
                          {pctCell(roi ?? null)}
                          {t.unrealized_usd != null && performanceMode === "total" ? (
                            <div className="text-[10px] text-ink-faint">
                              {d(t.unrealized_usd) >= 0 ? "+" : ""}
                              {formatUsd(t.unrealized_usd)}
                            </div>
                          ) : null}
                        </td>
                        <td className="px-2 py-2 text-center tabular-nums text-ink-muted">
                          {t.portfolio_weight_pct.toFixed(1)}%
                        </td>
                        <td className="px-2 py-2 text-center">
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
                      </>
                    ) : null}
                    {view === "tax" ? (
                      <>
                        <TickerCell t={t} />
                        <td className="px-2 py-2 text-center tabular-nums font-medium">
                          {formatQty(t.quantity_total)}
                        </td>
                        <TaxFreeCell t={t} highlight={highlightTaxFree} />
                        <td className="px-2 py-2 text-center">
                          <div className="inline-flex justify-center">
                            <TrancheMiniBar tranches={t.tax_tranches} />
                          </div>
                        </td>
                        <td className="px-2 py-2 text-center">
                          {t.next_unlock_date ? (
                            <>
                              <div className="tabular-nums">{t.next_unlock_date}</div>
                              {t.next_unlock_quantity ? (
                                <div className="text-[10px] tabular-nums text-ink-faint">
                                  {formatQty(t.next_unlock_quantity)}
                                </div>
                              ) : null}
                            </>
                          ) : (
                            <span className="text-ok">All eligible</span>
                          )}
                        </td>
                      </>
                    ) : null}
                    {view === "daily" ? (
                      <>
                        <TickerCell t={t} subtitle={priorDaySubtitle(perf?.session_status)} />
                        <td className="px-2 py-2 text-center tabular-nums font-medium">
                          {hasMoneyValue(perf?.last_value) ? (
                            formatUsd(perf?.last_value)
                          ) : (
                            <span className="text-ink-faint">—</span>
                          )}
                        </td>
                        <td className="px-2 py-2 text-center">
                          {signedUsdCell(dayPnlDisplay(t, perf))}
                        </td>
                        <td className="px-2 py-2 text-center">
                          {pctCell(perf?.change_pct ?? null)}
                        </td>
                        <HonestMvCell t={t} />
                      </>
                    ) : null}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      {view === "wealth" && gradePairs.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5 border-t border-white/5 px-4 py-2">
          <span className="mr-1 text-[10px] font-medium uppercase tracking-wide text-ink-faint">
            Grade
          </span>
          {gradePairs.map((p) => (
            <span
              key={`${p.grade}\0${p.label}`}
              className={cn(
                "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-bold ring-1",
                gradeStyleClass(p.grade),
              )}
              title={p.label}
            >
              {p.grade}
              <span className="font-medium opacity-80">{p.label}</span>
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
