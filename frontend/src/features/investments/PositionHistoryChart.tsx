import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
  ReferenceLine,
} from "recharts";
import { ExternalLink } from "lucide-react";
import { api } from "../../api/client";
import type {
  PriceHistory,
  PriceHistoryRange,
  PriceHistoryTrade,
  TickerDigest,
  WindowPerformanceItem,
} from "../../api/types";
import { d, formatUsd, hasMoneyValue } from "../../lib/money";
import { cn } from "../../lib/cn";
import { indexTradesByPoint, tradesForPoint } from "../../lib/chartTrades";
import {
  BUY_COLOR,
  LegendBuyIcon,
  LegendSellIcon,
  SELL_COLOR,
  TradeBuyShape,
  TradeSellShape,
} from "../../lib/chartTradeMarkers";
import { RECON_THRESHOLD_USD, selectChartHeadline } from "../../lib/chartChangeHeadline";
import {
  COST_DOMAIN_PAD,
  chartYDomain,
  shouldShowCostBasis,
} from "../../lib/chartCostVisibility";
import { rthValuesOf, splitSessionSeries } from "../../lib/chartSessionSeries";
import {
  loadChartChangeMode,
  saveChartChangeMode,
  type ChartChangeMode,
} from "../../lib/chartChangeMode";

const RANGES: { key: PriceHistoryRange; label: string }[] = [
  { key: "1d", label: "1D" },
  { key: "7d", label: "7D" },
  { key: "1m", label: "1M" },
  { key: "3m", label: "3M" },
  { key: "6m", label: "6M" },
  { key: "ytd", label: "YTD" },
  { key: "1y", label: "1Y" },
  { key: "5y", label: "5Y" },
];

const RANGE_KEY = "gauntlet.priceHistory.range";
const TRADES_KEY = "gauntlet.priceHistory.showTrades";

export type ChartScope =
  | { kind: "all" }
  | { kind: "asset_class"; asset_class: "Stock" | "Crypto" }
  | { kind: "ticker"; ticker: string };

type Props = {
  digests: TickerDigest[];
  scope: ChartScope;
  onScopeChange: (scope: ChartScope) => void;
  /** Compact chrome for pop-out window */
  variant?: "embedded" | "popout";
  /** Hide pop-out button (already in pop-out) */
  showPopOut?: boolean;
  /** When true, default range to 1d if none stored */
  preferIntraday?: boolean;
};

function loadRange(preferIntraday?: boolean): PriceHistoryRange {
  try {
    const raw = localStorage.getItem(RANGE_KEY);
    if (raw === "max") return "5y";
    if (raw && RANGES.some((r) => r.key === raw)) return raw as PriceHistoryRange;
  } catch {
    /* ignore */
  }
  return preferIntraday ? "1d" : "1y";
}

function shortLabel(iso: string, intraday: boolean): string {
  if (intraday || iso.includes("T")) {
    const d0 = new Date(iso);
    if (!Number.isNaN(d0.getTime())) {
      return d0.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
    }
  }
  const day = iso.slice(0, 10);
  const d0 = new Date(day + "T12:00:00");
  return d0.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatPrice(v: number): string {
  if (v >= 1000) return formatUsd(v);
  if (v >= 1) {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    }).format(v);
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 4,
    maximumFractionDigits: 6,
  }).format(v);
}

function isLocalDayStatus(status: string | null | undefined): boolean {
  return status === "local_day" || status === "last_24h";
}

function tickerIntradayCaption(sessionStatus: string | null | undefined): string {
  if (sessionStatus === "overnight") {
    return "Overnight · prior RTH last · waiting for 4:00 ET pre-market";
  }
  if (sessionStatus === "pre_market") {
    return "Pre-market · 4:00–9:30 ET · Yahoo 5m path (not desk book)";
  }
  if (sessionStatus === "after_hours") {
    return "After-hours · 16:00–20:00 ET · Yahoo 5m path (not desk book)";
  }
  if (sessionStatus === "prior_session") {
    return "Prior session · market closed · Yahoo 5m path";
  }
  if (sessionStatus === "prior_local_day") {
    return "Prior day · waiting for today’s open · Yahoo 5m path";
  }
  if (isLocalDayStatus(sessionStatus)) {
    return "Today · Yahoo 5m path (not desk book)";
  }
  if (sessionStatus === "regular") {
    return "US regular session · pre/AH dashed · Yahoo 5m path (not desk book)";
  }
  return "Yahoo 5m path";
}

function chartPathCaption(
  scope: ChartScope,
  sessionStatus: string | null | undefined,
  intraday: boolean,
): string {
  if (scope.kind === "ticker") {
    if (intraday) return tickerIntradayCaption(sessionStatus);
    return "Daily close (USD) · avg cost from open lots";
  }
  if (sessionStatus === "overnight") {
    return "Overnight · prior RTH last · Yahoo path";
  }
  if (sessionStatus === "pre_market") {
    return "Pre-market · Yahoo path · desk book shown separately";
  }
  if (sessionStatus === "after_hours") {
    return "After-hours · Yahoo path · desk book shown separately";
  }
  if (sessionStatus === "prior_session") {
    return "Prior session · market closed · Yahoo path";
  }
  if (sessionStatus === "prior_local_day") {
    return "Prior day · waiting for today’s open · Yahoo path";
  }
  if (isLocalDayStatus(sessionStatus)) {
    return scope.kind === "all"
      ? "Today · Yahoo 5m path · desk book is the executive total"
      : "Today · Yahoo path · desk book shown separately";
  }
  if (sessionStatus === "regular") {
    return "US regular session · pre/AH dashed · Yahoo path · desk book shown separately";
  }
  return "Holdings as of each day × market prices · free Yahoo data";
}

export function scopeToQuery(scope: ChartScope): {
  scope: "ticker" | "asset_class" | "all";
  ticker?: string;
  asset_class?: string;
} {
  if (scope.kind === "ticker") return { scope: "ticker", ticker: scope.ticker };
  if (scope.kind === "asset_class")
    return { scope: "asset_class", asset_class: scope.asset_class };
  return { scope: "all" };
}

export function popoutUrl(scope: ChartScope, range: PriceHistoryRange): string {
  const q = new URLSearchParams();
  const sq = scopeToQuery(scope);
  q.set("scope", sq.scope);
  if (sq.ticker) q.set("ticker", sq.ticker);
  if (sq.asset_class) q.set("asset_class", sq.asset_class);
  q.set("range", range);
  return `${window.location.origin}/investments/chart?${q.toString()}`;
}

export function openChartPopout(scope: ChartScope, range: PriceHistoryRange) {
  const url = popoutUrl(scope, range);
  window.open(
    url,
    "gauntlet-price-chart",
    "popup=yes,width=980,height=680,menubar=no,toolbar=no,location=no,status=no",
  );
}

export function PositionHistoryChart({
  digests,
  scope,
  onScopeChange,
  variant = "embedded",
  showPopOut = true,
  preferIntraday = false,
}: Props) {
  const [range, setRange] = useState<PriceHistoryRange>(() => loadRange(preferIntraday));
  const [data, setData] = useState<PriceHistory | null>(null);
  const [perfByTicker, setPerfByTicker] = useState<Record<string, WindowPerformanceItem>>(
    {},
  );
  const [perfLoading, setPerfLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [softUpdating, setSoftUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);
  const [showTrades, setShowTrades] = useState(() => {
    try {
      const raw = localStorage.getItem(TRADES_KEY);
      if (raw === "0") return false;
    } catch {
      /* ignore */
    }
    return true;
  });
  const [changeMode, setChangeMode] = useState<ChartChangeMode>(() =>
    loadChartChangeMode(),
  );
  const hasDataRef = useRef(false);
  hasDataRef.current = data != null && (data.points?.length ?? 0) > 0;

  const toggleTrades = () => {
    setShowTrades((v) => {
      const next = !v;
      try {
        localStorage.setItem(TRADES_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  const hasStock = digests.some((t) => {
    const ac = (t.asset_class || "").toLowerCase();
    return ac === "stock" || ac === "etf" || ac === "equity";
  });
  const hasCrypto = digests.some((t) => (t.asset_class || "").toLowerCase() === "crypto");
  const hasAny = digests.length > 0;

  const onRange = (key: PriceHistoryRange) => {
    setRange(key);
    try {
      localStorage.setItem(RANGE_KEY, key);
    } catch {
      /* ignore */
    }
  };

  const fetchHistory = useCallback(async () => {
    const sq = scopeToQuery(scope);
    return api.priceHistory({
      scope: sq.scope,
      ticker: sq.ticker,
      asset_class: sq.asset_class,
      range,
    });
  }, [scope, range]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Keep prior series visible during 60s polls / scope flips (no blank flash)
      const isSoft = hasDataRef.current;
      if (isSoft) {
        setSoftUpdating(true);
      } else {
        setLoading(true);
        setError(null);
      }
      try {
        const res = await fetchHistory();
        if (!cancelled) {
          setData(res);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          if (!isSoft) {
            setError(e instanceof Error ? e.message : "Failed to load history");
            setData(null);
          }
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          setSoftUpdating(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchHistory, refreshTick]);

  // Per-ticker performance for selected range (strip under chart).
  // Tied to range only — not soft price ticks (window-perf is Yahoo-heavy).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setPerfLoading(true);
      try {
        const res = await api.priceWindowPerformance({ range });
        if (cancelled) return;
        const map: Record<string, WindowPerformanceItem> = {};
        for (const it of res.items || []) {
          map[it.ticker.toUpperCase()] = it;
        }
        setPerfByTicker(map);
      } catch {
        if (!cancelled) {
          /* keep prior strip */
        }
      } finally {
        if (!cancelled) setPerfLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [range]);

  // Soft mark updates: only rebuild path for 1D (live). Multi-day Yahoo history
  // does not need a full refetch every soft tick (was causing thrash + load fails).
  useEffect(() => {
    const onPrices = (ev: Event) => {
      const soft =
        typeof CustomEvent !== "undefined" &&
        ev instanceof CustomEvent &&
        Boolean((ev.detail as { soft?: boolean } | undefined)?.soft);
      if (soft && range !== "1d") return;
      setRefreshTick((n) => n + 1);
    };
    window.addEventListener("prices-updated", onPrices);
    return () => window.removeEventListener("prices-updated", onPrices);
  }, [range]);

  // Pop-out has no Layout coordinator; keep light 1D watch poll there only
  useEffect(() => {
    if (variant !== "popout" || range !== "1d") return;
    const id = window.setInterval(() => setRefreshTick((n) => n + 1), 90_000);
    return () => window.clearInterval(id);
  }, [range, variant]);

  const intraday = data?.interval === "5m" || data?.meta?.point_kind === "intraday";

  const rows = useMemo(() => {
    if (!data?.points?.length) return [];
    const cost =
      data.series_kind === "price" && data.meta.avg_cost_usd != null
        ? d(data.meta.avg_cost_usd)
        : data.series_kind === "market_value" && data.meta.cost_basis_usd != null
          ? d(data.meta.cost_basis_usd)
          : undefined;
    const trades = data.meta.trades ?? [];
    const isIntra = !!intraday;
    const byKey = indexTradesByPoint(
      trades,
      isIntra,
      data.points.map((p) => p.date),
    );
    const split = splitSessionSeries(data.points);
    const splitByDate = new Map(split.map((r) => [r.date, r]));
    return data.points.map((p) => {
      const pointTrades = tradesForPoint(byKey, p.date, isIntra);
      const y = d(p.value);
      const buyCount = pointTrades.filter((t) => t.side === "buy").length;
      const sellCount = pointTrades.filter((t) => t.side === "sell").length;
      const sess = splitByDate.get(p.date);
      return {
        date: p.date,
        label: shortLabel(p.date, isIntra),
        value: y,
        rthValue: sess?.rthValue ?? null,
        extValue: sess?.extValue ?? null,
        session: p.session,
        cost,
        buyMark: buyCount > 0 ? y : (null as number | null),
        sellMark: sellCount > 0 ? y : (null as number | null),
        buyCount,
        sellCount,
        trades: pointTrades,
      };
    });
  }, [data, intraday]);

  const tradeCount = data?.meta.trades?.length ?? 0;

  /** Tickers in strip: filter by book when Stocks/Crypto selected; else all. */
  const stripTickers = useMemo(() => {
    let list = digests.slice();
    if (scope.kind === "asset_class") {
      const want = scope.asset_class.toLowerCase();
      list = list.filter((t) => {
        const ac = (t.asset_class || "").toLowerCase();
        if (want === "stock") return ac === "stock" || ac === "etf" || ac === "equity";
        return ac === want;
      });
    }
    // Prefer API sort (best first); fall back to digest order with perf overlay
    return list
      .map((t) => {
        const p = perfByTicker[t.ticker.toUpperCase()];
        return { digest: t, perf: p };
      })
      .sort((a, b) => {
        // Strip stays since-close (change_pct). RTH vs-open is Daily/headline only.
        const ap = a.perf?.change_pct;
        const bp = b.perf?.change_pct;
        if (ap == null && bp == null) return a.digest.ticker.localeCompare(b.digest.ticker);
        if (ap == null) return 1;
        if (bp == null) return -1;
        if (bp !== ap) return bp - ap;
        return a.digest.ticker.localeCompare(b.digest.ticker);
      });
  }, [digests, scope, perfByTicker]);

  const last = rows[rows.length - 1];
  const first = rows[0];
  const changePct = data?.meta.change_pct ?? null;
  const changeAbs =
    data?.meta.change_abs != null
      ? d(data.meta.change_abs)
      : last && first
        ? last.value - first.value
        : null;
  const markPnlAbs =
    data?.meta.mark_pnl_abs != null ? d(data.meta.mark_pnl_abs) : null;
  const markPnlPct = data?.meta.mark_pnl_pct ?? null;
  const netCapitalAbs =
    data?.meta.net_capital_abs != null ? d(data.meta.net_capital_abs) : null;
  const isPrice = data?.series_kind === "price";
  const rthAbsRaw = data?.meta.change_rth_abs;
  const changeRthAbs = hasMoneyValue(rthAbsRaw) ? d(rthAbsRaw) : null;
  const changeRthPct = data?.meta.change_rth_pct ?? null;
  const headline = selectChartHeadline({
    seriesKind: data?.series_kind ?? (isPrice ? "price" : "market_value"),
    mode: changeMode,
    changeAbs,
    changePct,
    markPnlAbs,
    markPnlPct,
    netCapitalAbs,
    range,
    sessionStatus: data?.meta.session_status ?? null,
    changeRthAbs,
    changeRthPct,
  });
  const primaryAbs = headline.primaryAbs;
  const primaryPct = headline.primaryPct;
  const dayPct = data?.meta.day_change_pct ?? null;
  const dayAbs = data?.meta.day_change_abs != null ? d(data.meta.day_change_abs) : null;
  const costRef =
    isPrice && data?.meta.avg_cost_usd != null
      ? d(data.meta.avg_cost_usd)
      : !isPrice && data?.meta.cost_basis_usd != null
        ? d(data.meta.cost_basis_usd)
        : null;
  const priceValues = rows.map((r) => r.value);
  const rthValues = rthValuesOf(
    rows.map((r) => ({
      date: r.date,
      value: r.value,
      rthValue: r.rthValue,
      extValue: r.extValue,
      session: r.session,
    })),
  );
  const showCost =
    costRef != null && Number.isFinite(costRef)
      ? shouldShowCostBasis(costRef, rthValues)
      : false;
  const yDomain = chartYDomain(priceValues, {
    cost: costRef ?? undefined,
    showCost,
    pad: COST_DOMAIN_PAD,
  });
  const dayOpenY =
    data != null && hasMoneyValue(data.meta.day_open) ? d(data.meta.day_open) : null;

  const wc = data?.meta.window_components;
  /** Legs follow active mode: Book → MV Δ; Performance → mark performance. */
  const bookMode = headline.effectiveMode === "book";
  const stockWin = bookMode
    ? wc?.stocks?.mv_change_usd != null
      ? d(wc.stocks.mv_change_usd)
      : wc?.stocks?.change_usd != null
        ? d(wc.stocks.change_usd)
        : null
    : wc?.stocks?.change_usd != null
      ? d(wc.stocks.change_usd)
      : null;
  const cryptoWin = bookMode
    ? wc?.crypto?.mv_change_usd != null
      ? d(wc.crypto.mv_change_usd)
      : wc?.crypto?.change_usd != null
        ? d(wc.crypto.change_usd)
        : null
    : wc?.crypto?.change_usd != null
      ? d(wc.crypto.change_usd)
      : null;
  // Book legs: derive % from first/last when present; else fall back to mark %
  const stockWinPct = bookMode
    ? wc?.stocks?.first_usd != null &&
      wc?.stocks?.last_usd != null &&
      d(wc.stocks.first_usd) !== 0
      ? ((d(wc.stocks.last_usd) - d(wc.stocks.first_usd)) / Math.abs(d(wc.stocks.first_usd))) *
        100
      : null
    : (wc?.stocks?.change_pct ?? null);
  const cryptoWinPct = bookMode
    ? wc?.crypto?.first_usd != null &&
      wc?.crypto?.last_usd != null &&
      d(wc.crypto.first_usd) !== 0
      ? ((d(wc.crypto.last_usd) - d(wc.crypto.first_usd)) / Math.abs(d(wc.crypto.first_usd))) *
        100
      : null
    : (wc?.crypto?.change_pct ?? null);
  const legsResidual =
    primaryAbs != null && (stockWin != null || cryptoWin != null)
      ? primaryAbs - (stockWin ?? 0) - (cryptoWin ?? 0)
      : null;
  const showLegsResidual =
    legsResidual != null && Math.abs(legsResidual) > RECON_THRESHOLD_USD;

  const missing = data?.meta.missing_tickers ?? [];
  // Series is always market value — paint stroke from book endpoints so green/red matches the line
  const bookStrokeAbs =
    changeAbs != null
      ? changeAbs
      : last && first
        ? last.value - first.value
        : null;
  const seriesPositive =
    changePct != null
      ? changePct >= 0
      : bookStrokeAbs != null
        ? bookStrokeAbs >= 0
        : true;
  const dayPositive = dayPct != null ? dayPct >= 0 : true;
  const stroke = seriesPositive ? "#2dd4a8" : "#f87171";
  const showModeToggle = !isPrice && scope.kind !== "ticker";
  /** Highlight the mode that is actually driving the primary number (fallback → Book). */
  const modeChipActive: "performance" | "book" =
    headline.effectiveMode === "performance" ? "performance" : "book";

  const title =
    scope.kind === "ticker"
      ? scope.ticker
      : scope.kind === "all"
        ? "Portfolio"
        : scope.asset_class === "Crypto"
          ? "All crypto"
          : "All stocks";

  const fmt = (v: number) => (isPrice ? formatPrice(v) : formatUsd(v));
  const isPopout = variant === "popout";
  /** Embedded: fixed band. Popout: flex-fills remaining viewport (parent is flex column). */
  const chartH = isPopout
    ? "min-h-[10rem] flex-1 basis-0"
    : "h-64 sm:h-72 shrink-0";

  return (
    <div
      className={cn(
        "card",
        isPopout
          ? "flex h-full min-h-0 flex-col gap-2 rounded-none border-0 p-2 sm:gap-3 sm:p-3"
          : "space-y-4 p-5",
      )}
    >
      {/*
        Two rows so a 2xl last-price cannot overflow Pop out in the narrow column.
        Values stay ml-auto / justify-end so Portfolio legs do not park left of the title.
      */}
      <div className={cn("flex w-full min-w-0 flex-col gap-2", isPopout && "shrink-0")}>
        <div className="flex w-full min-w-0 items-start gap-2">
          <div className="min-w-0 flex-1">
            <h2 className={cn("font-semibold", isPopout ? "text-xs sm:text-sm" : "text-sm")}>
              {isPopout ? "Live chart · " : "Price history · "}
              {title}
            </h2>
            <p className={cn("text-ink-faint", isPopout ? "text-[10px] sm:text-xs" : "text-xs")}>
              {chartPathCaption(scope, data?.meta?.session_status, !!intraday)}
              {showTrades ? " · buy/sell markers" : ""}
              {range === "1d" && " · auto-refresh 60s"}
            </p>
          </div>
          {showPopOut && (
            <button
              type="button"
              title="Open chart in a separate window"
              onClick={() => openChartPopout(scope, range)}
              className="inline-flex shrink-0 items-center gap-1.5 self-start rounded-lg bg-white/5 px-2.5 py-1.5 text-xs font-medium text-ink-muted transition hover:bg-white/10 hover:text-ink"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Pop out
            </button>
          )}
        </div>
        {last && (
          <div className="ml-auto flex w-full min-w-0 flex-wrap items-start justify-end text-right">
            <div className="relative min-w-0">
              <div
                className={cn(
                  "text-[11px] uppercase tracking-wide text-ink-faint",
                  softUpdating && "invisible",
                )}
              >
                {range === "1d"
                  ? isPrice
                    ? "Chart last"
                    : "Chart MV"
                  : isPrice
                    ? "Last price"
                    : "Market value"}
              </div>
              <div
                className={cn(
                  "font-semibold tabular-nums tracking-tight text-brand",
                  isPopout ? "text-2xl sm:text-3xl" : "text-xl sm:text-2xl",
                )}
              >
                {fmt(last.value)}
              </div>
              {range === "1d" &&
                (() => {
                  const bookRaw = isPrice
                    ? data?.meta?.book_price_usd
                    : data?.meta?.book_market_value_usd;
                  if (bookRaw == null || bookRaw === "") return null;
                  const bookN = d(bookRaw);
                  const pathN = last.value;
                  const delta =
                    data?.meta?.book_vs_path_abs != null
                      ? d(data.meta.book_vs_path_abs)
                      : pathN - bookN;
                  return (
                    <div
                      className="mt-0.5 max-w-[16rem] text-[11px] leading-snug text-ink-faint"
                      title="Desk book uses Prices-tab marks × open lots (same as Home portfolio). Chart tip is the last Yahoo 5m bar on the path — they can differ without either being wrong."
                    >
                      <span className="text-ink-muted">Desk book </span>
                      <span className="tabular-nums text-ink-muted">
                        {isPrice ? formatPrice(bookN) : formatUsd(bookN)}
                      </span>
                      <span className="text-ink-faint">
                        {" "}
                        · path Δ{" "}
                        <span
                          className={cn(
                            "tabular-nums",
                            delta >= 0 ? "text-ok/80" : "text-danger/80",
                          )}
                        >
                          {delta >= 0 ? "+" : ""}
                          {isPrice ? formatPrice(delta) : formatUsd(delta)}
                        </span>
                      </span>
                    </div>
                  );
                })()}
              {primaryAbs != null && (
                <div
                  className={cn(
                    "font-medium tabular-nums",
                    isPopout ? "text-xs sm:text-sm" : "text-sm",
                    primaryAbs >= 0 ? "text-ok" : "text-danger",
                  )}
                  title={headline.primaryTitle}
                >
                  {primaryAbs >= 0 ? "+" : ""}
                  {fmt(primaryAbs)}
                  {primaryPct != null && (
                    <span>
                      {" "}
                      ({primaryPct >= 0 ? "+" : ""}
                      {primaryPct.toFixed(1)}%)
                    </span>
                  )}
                  <span className="font-normal text-ink-faint">
                    {" "}
                    {headline.primaryLabel}
                  </span>
                </div>
              )}
              {headline.performanceUnavailable && (
                <div className="text-[11px] text-ink-faint">
                  Performance unavailable for this window
                </div>
              )}
              {headline.secondary && (
                <div
                  className="mt-0.5 space-y-0.5 text-[11px] tabular-nums text-ink-faint"
                  title={
                    headline.secondary.netCapitalAbs != null
                      ? `${headline.secondary.otherTitle}. Cash/qty effect is market value Δ minus performance (buys/sells and residual).`
                      : headline.secondary.otherTitle
                  }
                >
                  <div>
                    {headline.secondary.otherAbs != null && (
                      <span
                        className={cn(
                          headline.secondary.otherAbs >= 0 ? "text-ok" : "text-danger",
                        )}
                      >
                        {headline.secondary.otherLabel}{" "}
                        {headline.secondary.otherAbs >= 0 ? "+" : ""}
                        {fmt(headline.secondary.otherAbs)}
                      </span>
                    )}
                    {headline.secondary.otherPct != null && (
                      <span>
                        {" "}
                        ({headline.secondary.otherPct >= 0 ? "+" : ""}
                        {headline.secondary.otherPct.toFixed(1)}%)
                      </span>
                    )}
                    {headline.secondary.netCapitalAbs != null && (
                      <span>
                        {" · Cash/qty effect "}
                        {headline.secondary.netCapitalAbs >= 0 ? "+" : ""}
                        {formatUsd(headline.secondary.netCapitalAbs)}
                      </span>
                    )}
                  </div>
                </div>
              )}
              {scope.kind === "all" && (stockWin != null || cryptoWin != null) && (
                <div className="mt-0.5 space-y-0.5 text-right">
                  <div className="flex flex-wrap justify-end gap-x-2 gap-y-0.5 text-[11px] tabular-nums text-ink-faint">
                    {stockWin != null && (
                      <span
                        className={cn(
                          stockWin >= 0 ? "text-ok" : "text-danger",
                        )}
                        title={
                          bookMode
                            ? range === "1d"
                              ? "Stocks market value Δ this session (leg; may not match headline on 1D)"
                              : "Stocks market value Δ over this range"
                            : range === "1d"
                              ? "Stocks US session performance (leg; not the chart headline on 1D)"
                              : "Stocks performance over this range"
                        }
                      >
                        Stocks
                        {range === "1d"
                          ? bookMode
                            ? " (session MV)"
                            : " (session)"
                          : bookMode
                            ? " MV Δ"
                            : " performance"}{" "}
                        {stockWin >= 0 ? "+" : ""}
                        {formatUsd(stockWin)}
                        {stockWinPct != null && (
                          <span className="text-ink-faint">
                            {" "}
                            ({stockWinPct >= 0 ? "+" : ""}
                            {stockWinPct.toFixed(1)}%)
                          </span>
                        )}
                      </span>
                    )}
                    {cryptoWin != null && (
                      <span
                        className={cn(
                          cryptoWin >= 0 ? "text-ok" : "text-danger",
                        )}
                        title={
                          bookMode
                            ? range === "1d"
                              ? "Crypto market value Δ today (leg; may not match headline on 1D)"
                              : "Crypto market value Δ over this range"
                            : range === "1d"
                              ? "Crypto today performance (leg; not the chart headline on 1D)"
                              : "Crypto performance over this range"
                        }
                      >
                        Crypto
                        {range === "1d"
                          ? bookMode
                            ? " (today MV)"
                            : " (today)"
                          : bookMode
                            ? " MV Δ"
                            : " performance"}{" "}
                        {cryptoWin >= 0 ? "+" : ""}
                        {formatUsd(cryptoWin)}
                        {cryptoWinPct != null && (
                          <span className="text-ink-faint">
                            {" "}
                            ({cryptoWinPct >= 0 ? "+" : ""}
                            {cryptoWinPct.toFixed(1)}%)
                          </span>
                        )}
                      </span>
                    )}
                  </div>
                  {showLegsResidual && legsResidual != null && (
                    <p className="max-w-[16rem] text-[10px] leading-snug text-ink-faint/90">
                      Residual {legsResidual >= 0 ? "+" : ""}
                      {formatUsd(legsResidual)}
                    </p>
                  )}
                </div>
              )}
              {dayPct != null && range !== "1d" && (
                <div
                  className={cn(
                    "text-xs tabular-nums",
                    dayPositive ? "text-ok" : "text-danger",
                  )}
                >
                  Today{" "}
                  {dayAbs != null && (
                    <span>
                      {dayAbs >= 0 ? "+" : ""}
                      {fmt(dayAbs)}{" "}
                    </span>
                  )}
                  ({dayPct >= 0 ? "+" : ""}
                  {dayPct.toFixed(1)}%)
                </div>
              )}
              {costRef != null && (
                <div className="text-sm text-ink-muted">
                  {isPrice ? "Avg cost " : "Cost basis "}
                  <span className="font-medium tabular-nums text-ink">
                    {fmt(costRef)}
                  </span>
                </div>
              )}
              {softUpdating && (
                <span
                  className="pointer-events-none absolute right-0 top-0 text-[11px] leading-tight text-ink-faint"
                  aria-live="polite"
                >
                  Updating…
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Book filters only — tickers live under the chart with range performance */}
      <div className={cn("flex flex-wrap gap-1.5", isPopout && "shrink-0")}>
        {hasAny && (
          <ScopeChip
            active={scope.kind === "all"}
            onClick={() => onScopeChange({ kind: "all" })}
            label="Portfolio"
          />
        )}
        {hasStock && (
          <ScopeChip
            active={scope.kind === "asset_class" && scope.asset_class === "Stock"}
            onClick={() => onScopeChange({ kind: "asset_class", asset_class: "Stock" })}
            label="Stocks"
          />
        )}
        {hasCrypto && (
          <ScopeChip
            active={scope.kind === "asset_class" && scope.asset_class === "Crypto"}
            onClick={() => onScopeChange({ kind: "asset_class", asset_class: "Crypto" })}
            label="Crypto"
          />
        )}
      </div>

      {/* Range chips + change mode + trades toggle */}
      <div className={cn("flex flex-wrap items-center gap-2", isPopout && "shrink-0")}>
        <div className="flex flex-wrap gap-1">
          {RANGES.map((r) => (
            <button
              key={r.key}
              type="button"
              onClick={() => onRange(r.key)}
              className={cn(
                "rounded-md px-2 py-1 text-[11px] font-semibold tracking-wide transition",
                range === r.key
                  ? "bg-brand/20 text-brand ring-1 ring-brand/40"
                  : "bg-white/5 text-ink-muted hover:bg-white/10 hover:text-ink",
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
        {showModeToggle && (
          <div
            role="radiogroup"
            aria-label="Chart return basis"
            className="flex rounded-md bg-white/5 p-0.5 ring-1 ring-white/10"
            title="Performance = price move on qty at chart start. Book = market value Δ (last − first on the line)."
          >
            {(
              [
                ["performance", "Performance"],
                ["book", "Book"],
              ] as const
            ).map(([key, label]) => {
              const pressed = modeChipActive === key;
              const perfDisabled =
                key === "performance" && headline.performanceUnavailable;
              return (
                <button
                  key={key}
                  type="button"
                  role="radio"
                  aria-checked={pressed}
                  aria-pressed={pressed}
                  disabled={perfDisabled}
                  title={
                    perfDisabled
                      ? "Performance (mark) unavailable for this window — showing Book"
                      : undefined
                  }
                  onClick={() => {
                    if (perfDisabled) return;
                    setChangeMode(key);
                    saveChartChangeMode(key);
                  }}
                  className={cn(
                    "rounded px-2 py-1 text-[11px] font-semibold tracking-wide transition",
                    pressed
                      ? "bg-brand/25 text-brand"
                      : "text-ink-muted hover:text-ink",
                    perfDisabled && "cursor-not-allowed opacity-50",
                  )}
                >
                  {label}
                </button>
              );
            })}
          </div>
        )}
        <button
          type="button"
          onClick={toggleTrades}
          className={cn(
            "rounded-md px-2 py-1 text-[11px] font-semibold tracking-wide transition",
            showTrades
              ? "bg-white/10 text-ink ring-1 ring-white/20"
              : "bg-white/5 text-ink-faint hover:bg-white/10 hover:text-ink-muted",
          )}
          title="Show statement buys and sells on the chart"
        >
          Trades{tradeCount > 0 ? ` (${tradeCount})` : ""}
        </button>
        {showTrades && tradeCount > 0 && (
          <span className="flex items-center gap-2 text-[11px] text-ink-faint">
            <span className="inline-flex items-center gap-1">
              <LegendBuyIcon />
              Buy
            </span>
            <span className="inline-flex items-center gap-1">
              <LegendSellIcon />
              Sell
            </span>
            <span className="text-ink-faint/80">· badge = multi</span>
          </span>
        )}
      </div>

      {loading && rows.length === 0 && (
        <div
          className={cn(
            "flex w-full items-center justify-center text-sm text-ink-muted",
            chartH,
          )}
        >
          Loading chart…
        </div>
      )}
      {error && rows.length === 0 && !loading && (
        <div
          className={cn(
            "rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger",
            isPopout && "shrink-0",
          )}
        >
          {error}
        </div>
      )}
      {!loading && !error && rows.length === 0 && (
        <div
          className={cn(
            "flex w-full items-center justify-center rounded-xl border border-white/10 bg-white/[0.03] px-3 py-6 text-center text-sm text-ink-muted",
            chartH,
          )}
        >
          {range === "1d"
            ? data?.meta?.session_status === "overnight" ||
              data?.meta?.session_status === "pre_market" ||
              data?.meta?.session_status === "prior_session"
              ? "No Yahoo prints yet for this session. Auto-refresh will retry."
              : "No bars yet for this session — Yahoo may still be catching up after the open. Auto-refresh will retry."
            : "No history returned for this scope. Yahoo may not cover this symbol, or markets may be closed."}
        </div>
      )}
      {rows.length > 0 && (
        <div
          className={cn(
            "w-full min-h-0 transition-opacity duration-300",
            chartH,
            softUpdating && "opacity-80",
          )}
        >
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="phFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={stroke} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={stroke} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="rgba(148,163,184,0.12)"
                vertical={false}
              />
              <XAxis
                dataKey="label"
                tick={{ fill: "#64748b", fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: "rgba(148,163,184,0.2)" }}
                /* Short daily windows: show every day label (avoid skipping mid dates). */
                interval={
                  !intraday && (range === "7d" || range === "1m")
                    ? 0
                    : "preserveStartEnd"
                }
                minTickGap={
                  !intraday && (range === "7d" || range === "1m")
                    ? 0
                    : intraday
                      ? 36
                      : 28
                }
              />
              <YAxis
                domain={yDomain}
                tick={{ fill: "#64748b", fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={64}
                tickFormatter={(v) =>
                  isPrice && Number(v) < 10
                    ? Number(v).toFixed(2)
                    : new Intl.NumberFormat("en-US", {
                        notation: "compact",
                        maximumFractionDigits: 1,
                      }).format(Number(v))
                }
              />
              <Tooltip
                contentStyle={{
                  background: "#0f172a",
                  border: "1px solid rgba(148,163,184,0.25)",
                  borderRadius: 12,
                  fontSize: 12,
                }}
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null;
                  const row = payload[0]?.payload as {
                    date?: string;
                    value?: number;
                    cost?: number;
                    buyCount?: number;
                    sellCount?: number;
                    trades?: PriceHistoryTrade[];
                  };
                  const raw = row?.date ?? String(label ?? "");
                  let title = raw.slice(0, 10);
                  if (raw.includes("T")) {
                    const d0 = new Date(raw);
                    if (!Number.isNaN(d0.getTime())) {
                      title = d0.toLocaleString("en-US", {
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      });
                    }
                  }
                  const trades = row?.trades ?? [];
                  const bc = row?.buyCount ?? 0;
                  const sc = row?.sellCount ?? 0;
                  return (
                    <div className="rounded-xl border border-white/15 bg-surface-raised px-3 py-2 text-xs shadow-card">
                      <div className="mb-1 font-medium text-ink">{title}</div>
                      {row?.value != null && (
                        <div className="tabular-nums text-ink-muted">
                          {isPrice ? "Price" : "Mark MV"}{" "}
                          <span className="font-medium text-ink">{fmt(row.value)}</span>
                        </div>
                      )}
                      {row?.cost != null && (
                        <div className="tabular-nums text-ink-faint">
                          {isPrice ? "Avg cost" : "Cost basis"} {fmt(row.cost)}
                        </div>
                      )}
                      {showTrades && trades.length > 0 && (bc > 0 || sc > 0) && (
                        <div className="mt-1 text-[11px] text-ink-faint">
                          {[
                            bc > 0 ? `${bc} buy${bc === 1 ? "" : "s"}` : null,
                            sc > 0 ? `${sc} sell${sc === 1 ? "" : "s"}` : null,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </div>
                      )}
                      {showTrades &&
                        trades.map((tr, i) => (
                          <div
                            key={`${tr.ticker}-${tr.side}-${i}`}
                            className={cn(
                              "mt-0.5 tabular-nums",
                              tr.side === "buy" ? "text-ok" : "text-danger",
                            )}
                          >
                            {tr.side === "buy" ? "BUY" : "SELL"} {tr.ticker} ·{" "}
                            {Number(tr.quantity).toLocaleString(undefined, {
                              maximumFractionDigits: 6,
                            })}
                            {tr.value_usd != null && tr.value_usd !== ""
                              ? ` · ${formatUsd(tr.value_usd)}`
                              : ""}
                          </div>
                        ))}
                    </div>
                  );
                }}
              />
              <Area
                type="monotone"
                dataKey="rthValue"
                stroke={stroke}
                fill="url(#phFill)"
                strokeWidth={2}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
                name="value"
              />
              <Line
                type="monotone"
                dataKey="extValue"
                stroke={stroke}
                strokeWidth={1.5}
                strokeDasharray="4 4"
                strokeOpacity={0.75}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
                legendType="none"
                name="extended"
              />
              {dayOpenY != null && (
                <ReferenceLine
                  y={dayOpenY}
                  stroke="rgba(148,163,184,0.55)"
                  strokeDasharray="2 3"
                  strokeWidth={1}
                />
              )}
              {showCost && costRef != null && (
                <ReferenceLine
                  y={costRef}
                  stroke="rgba(251, 191, 36, 0.7)"
                  strokeDasharray="4 4"
                  strokeWidth={1.5}
                />
              )}
              {showTrades && (
                <>
                  <Scatter
                    dataKey="buyMark"
                    fill={BUY_COLOR}
                    stroke={BUY_COLOR}
                    name="buy"
                    isAnimationActive={false}
                    legendType="none"
                    shape={TradeBuyShape}
                  />
                  <Scatter
                    dataKey="sellMark"
                    fill={SELL_COLOR}
                    stroke={SELL_COLOR}
                    name="sell"
                    isAnimationActive={false}
                    legendType="none"
                    shape={TradeSellShape}
                  />
                </>
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {missing.length > 0 && (
        <p className={cn("text-[11px] text-warn", isPopout && "shrink-0")}>
          No Yahoo history for: {missing.slice(0, 12).join(", ")}
          {missing.length > 12 ? "…" : ""}
        </p>
      )}
      {(data?.meta.short_history_tickers?.length ?? 0) > 0 && (
        <p className={cn("text-[11px] text-ink-muted", isPopout && "shrink-0 line-clamp-2")}>
          Late listings (join series when listed):{" "}
          {data!.meta.short_history_tickers!.slice(0, 8).map((s, i) => (
            <span key={s.ticker}>
              {i > 0 ? ", " : ""}
              {s.ticker} from {s.first_bar.slice(0, 10)}
            </span>
          ))}
          {data!.meta.short_history_tickers!.length > 8 ? "…" : ""}
        </p>
      )}
      {data?.meta.note && (
        <p className={cn("text-[11px] text-ink-faint", isPopout && "shrink-0 line-clamp-2")}>
          {data.meta.note}
        </p>
      )}

      {/* Ticker strip: dense square tiles · select series + window % */}
      {hasAny && (
        <div
          className={cn(
            "space-y-1.5 border-t border-white/5 pt-2",
            isPopout && "min-h-0 shrink-0",
          )}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-[10px] font-semibold uppercase tracking-wide text-ink-faint sm:text-xs">
              Holdings · {range.toUpperCase()} price move
            </h3>
            {/* Reserved label width so strip header does not jump */}
            <span
              className={cn(
                "w-[7.5rem] text-right text-[10px] text-ink-faint sm:text-[11px]",
                perfLoading ? "visible" : "invisible",
              )}
            >
              Updating returns…
            </span>
          </div>
          <div
            className={cn(
              "flex flex-wrap content-start justify-start gap-1",
              isPopout && "max-h-[min(28vh,12rem)] overflow-y-auto overscroll-contain",
            )}
          >
            {stripTickers.map(({ digest: t, perf }) => {
              const active = scope.kind === "ticker" && scope.ticker === t.ticker;
              const pct = perf?.change_pct;
              const up = pct != null && pct >= 0;
              const down = pct != null && pct < 0;
              const priceHint =
                perf?.last_value != null && perf.last_value !== ""
                  ? ` · ${formatPrice(d(perf.last_value))}`
                  : "";
              return (
                <button
                  key={t.ticker}
                  type="button"
                  onClick={() => onScopeChange({ kind: "ticker", ticker: t.ticker })}
                  className={cn(
                    "flex aspect-square w-[3.15rem] shrink-0 flex-col items-center justify-center rounded-md px-0.5 text-center transition sm:w-[3.35rem]",
                    active
                      ? "bg-brand/20 ring-1 ring-brand/50"
                      : "bg-white/[0.04] hover:bg-white/[0.09]",
                  )}
                  title={
                    pct != null
                      ? `${t.ticker}: ${pct >= 0 ? "+" : ""}${pct.toFixed(2)}% price move over ${range}${priceHint}`
                      : `${t.ticker}: no price series for ${range}`
                  }
                >
                  <span
                    className={cn(
                      "w-full truncate px-0.5 font-mono text-[10px] font-bold leading-none tracking-tight sm:text-[11px]",
                      active ? "text-brand" : "text-ink",
                    )}
                  >
                    {t.ticker}
                  </span>
                  <span
                    className={cn(
                      "mt-1 w-full tabular-nums text-[10px] font-semibold leading-none sm:text-[11px]",
                      pct == null && "text-ink-faint",
                      up && "text-ok",
                      down && "text-danger",
                    )}
                  >
                    {pct == null
                      ? "—"
                      : `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function ScopeChip({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-lg px-2.5 py-1.5 text-xs font-medium transition",
        active
          ? "bg-brand/25 text-brand ring-1 ring-brand/50"
          : "bg-white/5 text-ink-muted hover:bg-white/10 hover:text-ink",
      )}
    >
      {label}
    </button>
  );
}
