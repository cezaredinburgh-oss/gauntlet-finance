import { useEffect, useMemo, useRef, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
  ReferenceLine,
} from "recharts";
import { ExternalLink } from "lucide-react";
import { api } from "../api/client";
import type { PriceHistory, PriceHistoryRange, PriceHistoryTrade } from "../api/types";
import { d, formatUsd } from "../lib/money";
import { cn } from "../lib/cn";
import {
  openChartPopout,
  type ChartScope,
} from "../features/investments/PositionHistoryChart";

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

const TF_KEY = "gauntlet.mvSeries.historyRange";
const TRADES_KEY = "gauntlet.priceHistory.showTrades";
const BUY_COLOR = "#2dd4a8";
const SELL_COLOR = "#f87171";

type BookScope = "all" | "Stock" | "Crypto";

function loadRange(): PriceHistoryRange {
  try {
    const raw = localStorage.getItem(TF_KEY);
    if (raw === "max") return "5y";
    if (raw && RANGES.some((r) => r.key === raw)) return raw as PriceHistoryRange;
  } catch {
    /* ignore */
  }
  return "1y";
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

function toChartScope(book: BookScope): ChartScope {
  if (book === "all") return { kind: "all" };
  return { kind: "asset_class", asset_class: book };
}

/**
 * Portfolio market-value series from yfinance history (holdings as-of each day).
 * Buy/sell markers from statement events.
 */
export function PortfolioMvChart() {
  const [range, setRange] = useState<PriceHistoryRange>(() => loadRange());
  const [book, setBook] = useState<BookScope>("all");
  const [data, setData] = useState<PriceHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [softUpdating, setSoftUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [showTrades, setShowTrades] = useState(() => {
    try {
      if (localStorage.getItem(TRADES_KEY) === "0") return false;
    } catch {
      /* ignore */
    }
    return true;
  });
  const hasDataRef = useRef(false);
  hasDataRef.current = data != null && (data.points?.length ?? 0) > 0;

  const onRange = (key: PriceHistoryRange) => {
    setRange(key);
    try {
      localStorage.setItem(TF_KEY, key);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const isSoft = hasDataRef.current;
      if (isSoft) setSoftUpdating(true);
      else {
        setLoading(true);
        setError(null);
      }
      try {
        const res =
          book === "all"
            ? await api.priceHistory({ scope: "all", range })
            : await api.priceHistory({
                scope: "asset_class",
                asset_class: book,
                range,
              });
        if (!cancelled) {
          setData(res);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          if (!isSoft) {
            setError(e instanceof Error ? e.message : "Failed to load MV series");
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
  }, [range, book, tick]);

  useEffect(() => {
    const onPrices = () => setTick((n) => n + 1);
    window.addEventListener("prices-updated", onPrices);
    return () => window.removeEventListener("prices-updated", onPrices);
  }, []);

  useEffect(() => {
    if (range !== "1d") return;
    const id = window.setInterval(() => setTick((n) => n + 1), 60_000);
    return () => window.clearInterval(id);
  }, [range]);

  const intraday = data?.interval === "5m" || data?.meta?.point_kind === "intraday";

  const rows = useMemo(() => {
    if (!data?.points?.length) return [];
    const cost =
      data.meta.cost_basis_usd != null ? d(data.meta.cost_basis_usd) : undefined;
    const trades = data.meta.trades ?? [];
    const byDay = new Map<string, PriceHistoryTrade[]>();
    for (const tr of trades) {
      const day = tr.date.slice(0, 10);
      const list = byDay.get(day) ?? [];
      list.push(tr);
      byDay.set(day, list);
    }
    return data.points.map((p) => {
      const day = p.date.slice(0, 10);
      const dayTrades = byDay.get(day) ?? [];
      const y = d(p.value);
      return {
        date: p.date,
        label: shortLabel(p.date, !!intraday),
        mv: y,
        cost,
        buyMark: dayTrades.some((t) => t.side === "buy") ? y : (null as number | null),
        sellMark: dayTrades.some((t) => t.side === "sell") ? y : (null as number | null),
        trades: dayTrades,
      };
    });
  }, [data, intraday]);

  const tradeCount = data?.meta.trades?.length ?? 0;

  const last = rows[rows.length - 1];
  const changePct = data?.meta.change_pct ?? null;
  const dayPct = data?.meta.day_change_pct ?? null;
  const dayAbs = data?.meta.day_change_abs != null ? d(data.meta.day_change_abs) : null;
  const costRef = data?.meta.cost_basis_usd != null ? d(data.meta.cost_basis_usd) : null;
  const positive = changePct != null ? changePct >= 0 : true;
  const dayPositive = dayPct != null ? dayPct >= 0 : true;
  const stroke = positive ? "#3d9cf0" : "#f87171";

  const title =
    book === "all" ? "Portfolio market value" : book === "Crypto" ? "Crypto book" : "Stock book";

  return (
    <div className="card space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          <p className="text-xs text-ink-faint">
            {data?.meta?.session_status === "prior_session"
              ? "Prior session · waiting for today’s open"
              : data?.meta?.session_status === "last_24h"
                ? "Last 24h · holdings as-of × market prices"
                : "Holdings as of each day × market prices · free Yahoo data"}
            {showTrades ? " · buy/sell markers" : ""}
            {range === "1d" ? " · auto-refresh 60s" : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-start gap-3">
          {last && (
            <div className="text-right">
              <div className="text-2xl font-semibold tabular-nums tracking-tight text-brand sm:text-3xl">
                {formatUsd(last.mv)}
              </div>
              {changePct != null && (
                <div className={cn("text-sm font-medium", positive ? "text-ok" : "text-danger")}>
                  {changePct >= 0 ? "+" : ""}
                  {changePct.toFixed(1)}% in window
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
                      {formatUsd(dayAbs)}{" "}
                    </span>
                  )}
                  ({dayPct >= 0 ? "+" : ""}
                  {dayPct.toFixed(1)}%)
                </div>
              )}
              {costRef != null && (
                <div className="text-sm text-ink-muted">
                  Cost basis{" "}
                  <span className="font-medium tabular-nums text-ink">
                    {formatUsd(costRef)}
                  </span>
                </div>
              )}
              {softUpdating && (
                <div className="text-[11px] text-ink-faint">Updating…</div>
              )}
            </div>
          )}
          <button
            type="button"
            title="Open chart in a separate window"
            onClick={() => openChartPopout(toChartScope(book), range)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-white/5 px-2.5 py-1.5 text-xs font-medium text-ink-muted transition hover:bg-white/10 hover:text-ink"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Pop out
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {(
          [
            ["all", "Portfolio"],
            ["Stock", "Stocks"],
            ["Crypto", "Crypto"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setBook(key)}
            className={cn(
              "rounded-lg px-2.5 py-1.5 text-xs font-medium transition",
              book === key
                ? "bg-brand/25 text-brand ring-1 ring-brand/50"
                : "bg-white/5 text-ink-muted hover:bg-white/10 hover:text-ink",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
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
        <button
          type="button"
          onClick={() => {
            setShowTrades((v) => {
              const next = !v;
              try {
                localStorage.setItem(TRADES_KEY, next ? "1" : "0");
              } catch {
                /* ignore */
              }
              return next;
            });
          }}
          className={cn(
            "rounded-md px-2 py-1 text-[11px] font-semibold tracking-wide transition",
            showTrades
              ? "bg-white/10 text-ink ring-1 ring-white/20"
              : "bg-white/5 text-ink-faint hover:bg-white/10 hover:text-ink-muted",
          )}
        >
          Trades{tradeCount > 0 ? ` (${tradeCount})` : ""}
        </button>
        {showTrades && tradeCount > 0 && (
          <span className="flex items-center gap-2 text-[11px] text-ink-faint">
            <span className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-full" style={{ background: BUY_COLOR }} />
              Buy
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-full" style={{ background: SELL_COLOR }} />
              Sell
            </span>
          </span>
        )}
      </div>

      {loading && rows.length === 0 && (
        <div className="flex h-56 items-center justify-center text-sm text-ink-muted">
          Loading market series…
        </div>
      )}
      {error && rows.length === 0 && !loading && (
        <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      )}
      {!loading && !error && rows.length === 0 && (
        <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-6 text-center text-sm text-ink-muted">
          {range === "1d"
            ? "No bars yet for this session — Yahoo may still be catching up after the open. Auto-refresh will retry."
            : "No market history yet. Import holdings and ensure yfinance can quote your tickers."}
        </div>
      )}
      {rows.length > 0 && (
        <div
          className={cn(
            "h-64 w-full sm:h-72 transition-opacity duration-300",
            softUpdating && "opacity-80",
          )}
        >
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="mvFill" x1="0" y1="0" x2="0" y2="1">
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
                interval="preserveStartEnd"
                minTickGap={28}
              />
              <YAxis
                tick={{ fill: "#64748b", fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={56}
                tickFormatter={(v) =>
                  new Intl.NumberFormat("en-US", {
                    notation: "compact",
                    maximumFractionDigits: 1,
                  }).format(Number(v))
                }
              />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const row = payload[0]?.payload as {
                    date?: string;
                    mv?: number;
                    trades?: PriceHistoryTrade[];
                  };
                  const trades = row?.trades ?? [];
                  return (
                    <div className="rounded-xl border border-white/15 bg-surface-raised px-3 py-2 text-xs shadow-card">
                      <div className="mb-1 font-medium text-ink">
                        {row?.date?.slice(0, 10) ?? ""}
                      </div>
                      {row?.mv != null && (
                        <div className="tabular-nums text-ink-muted">
                          Market value{" "}
                          <span className="font-medium text-ink">{formatUsd(row.mv)}</span>
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
                dataKey="mv"
                stroke={stroke}
                fill="url(#mvFill)"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              {costRef != null && range !== "1d" && (
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
                    name="buy"
                    isAnimationActive={false}
                    legendType="none"
                    shape="circle"
                  />
                  <Scatter
                    dataKey="sellMark"
                    fill={SELL_COLOR}
                    name="sell"
                    isAnimationActive={false}
                    legendType="none"
                    shape="circle"
                  />
                </>
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {data?.meta.note && (
        <p className="text-[11px] text-ink-faint">{data.meta.note}</p>
      )}
    </div>
  );
}
