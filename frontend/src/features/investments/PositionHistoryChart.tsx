import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  ReferenceLine,
} from "recharts";
import { ExternalLink } from "lucide-react";
import { api } from "../../api/client";
import type { PriceHistory, PriceHistoryRange, TickerDigest } from "../../api/types";
import { d, formatUsd } from "../../lib/money";
import { cn } from "../../lib/cn";

const RANGES: { key: PriceHistoryRange; label: string }[] = [
  { key: "1d", label: "1D" },
  { key: "1m", label: "1M" },
  { key: "3m", label: "3M" },
  { key: "6m", label: "6M" },
  { key: "ytd", label: "YTD" },
  { key: "1y", label: "1Y" },
  { key: "5y", label: "5Y" },
  { key: "max", label: "MAX" },
];

const RANGE_KEY = "gauntlet.priceHistory.range";

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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  const hasStock = digests.some((t) => (t.asset_class || "").toLowerCase() === "stock");
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
      setLoading(true);
      setError(null);
      try {
        const res = await fetchHistory();
        if (!cancelled) setData(res);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load history");
          setData(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchHistory, refreshTick]);

  // Soft refetch on prices-updated
  useEffect(() => {
    const onPrices = () => setRefreshTick((n) => n + 1);
    window.addEventListener("prices-updated", onPrices);
    return () => window.removeEventListener("prices-updated", onPrices);
  }, []);

  // Auto-refresh every 60s on 1D (watch mode)
  useEffect(() => {
    if (range !== "1d") return;
    const id = window.setInterval(() => setRefreshTick((n) => n + 1), 60_000);
    return () => window.clearInterval(id);
  }, [range]);

  const intraday = data?.interval === "5m" || data?.meta?.point_kind === "intraday";

  const rows = useMemo(() => {
    if (!data?.points?.length) return [];
    const cost =
      data.series_kind === "price" && data.meta.avg_cost_usd != null
        ? d(data.meta.avg_cost_usd)
        : data.series_kind === "market_value" && data.meta.cost_basis_usd != null
          ? d(data.meta.cost_basis_usd)
          : undefined;
    return data.points.map((p) => ({
      date: p.date,
      label: shortLabel(p.date, !!intraday),
      value: d(p.value),
      cost,
    }));
  }, [data, intraday]);

  const last = rows[rows.length - 1];
  const first = rows[0];
  const changePct = data?.meta.change_pct ?? null;
  const changeAbs =
    data?.meta.change_abs != null
      ? d(data.meta.change_abs)
      : last && first
        ? last.value - first.value
        : null;
  const dayPct = data?.meta.day_change_pct ?? null;
  const dayAbs = data?.meta.day_change_abs != null ? d(data.meta.day_change_abs) : null;
  const isPrice = data?.series_kind === "price";
  const costRef =
    isPrice && data?.meta.avg_cost_usd != null
      ? d(data.meta.avg_cost_usd)
      : !isPrice && data?.meta.cost_basis_usd != null
        ? d(data.meta.cost_basis_usd)
        : null;

  const missing = data?.meta.missing_tickers ?? [];
  const positive = changePct != null ? changePct >= 0 : true;
  const dayPositive = dayPct != null ? dayPct >= 0 : true;
  const stroke = positive ? "#2dd4a8" : "#f87171";

  const title =
    scope.kind === "ticker"
      ? scope.ticker
      : scope.kind === "all"
        ? "Portfolio"
        : scope.asset_class === "Crypto"
          ? "All crypto"
          : "All stocks";

  const fmt = (v: number) => (isPrice ? formatPrice(v) : formatUsd(v));
  const chartH = variant === "popout" ? "h-[min(70vh,28rem)]" : "h-64 sm:h-72";

  return (
    <div
      className={cn(
        "card space-y-4 p-5",
        variant === "popout" && "min-h-screen rounded-none border-0",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">
            {variant === "popout" ? "Live chart · " : "Price history · "}
            {title}
          </h2>
          <p className="text-xs text-ink-faint">
            {scope.kind === "ticker"
              ? intraday
                ? "Today · 5m bars (USD)"
                : "Daily close (USD) · avg cost from open lots"
              : "Current holdings marked at historical prices · free Yahoo data"}
            {range === "1d" && " · auto-refresh 60s"}
          </p>
        </div>
        <div className="flex flex-wrap items-start gap-3">
          {last && !loading && (
            <div className="text-right">
              <div className="text-lg font-semibold tabular-nums text-brand">
                {fmt(last.value)}
              </div>
              {changePct != null && (
                <div className={cn("text-xs", positive ? "text-ok" : "text-danger")}>
                  {changeAbs != null && (
                    <span className="mr-1.5 tabular-nums">
                      {changeAbs >= 0 ? "+" : ""}
                      {fmt(changeAbs)}
                    </span>
                  )}
                  {changePct >= 0 ? "+" : ""}
                  {changePct.toFixed(1)}% window
                </div>
              )}
              {dayPct != null && range !== "1d" && (
                <div
                  className={cn(
                    "text-[11px] tabular-nums",
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
                <div className="text-[11px] text-ink-faint">
                  {isPrice ? "Avg cost " : "Cost basis "}
                  {fmt(costRef)}
                </div>
              )}
            </div>
          )}
          {showPopOut && (
            <button
              type="button"
              title="Open chart in a separate window"
              onClick={() => openChartPopout(scope, range)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-white/5 px-2.5 py-1.5 text-xs font-medium text-ink-muted transition hover:bg-white/10 hover:text-ink"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Pop out
            </button>
          )}
        </div>
      </div>

      {/* Scope chips */}
      <div className="flex flex-wrap gap-1.5">
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
        {digests.map((t) => (
          <ScopeChip
            key={t.ticker}
            active={scope.kind === "ticker" && scope.ticker === t.ticker}
            onClick={() => onScopeChange({ kind: "ticker", ticker: t.ticker })}
            label={t.ticker}
          />
        ))}
      </div>

      {/* Range chips */}
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

      {loading && (
        <div className={cn("flex items-center justify-center text-sm text-ink-muted", chartH)}>
          Loading chart…
        </div>
      )}
      {error && !loading && (
        <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      )}
      {!loading && !error && rows.length === 0 && (
        <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-6 text-center text-sm text-ink-muted">
          No history returned for this scope. Yahoo may not cover this symbol, or markets
          may be closed.
        </div>
      )}
      {!loading && rows.length > 0 && (
        <div className={cn("w-full", chartH)}>
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
                interval="preserveStartEnd"
                minTickGap={intraday ? 36 : 28}
              />
              <YAxis
                domain={["auto", "auto"]}
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
                formatter={(value: number, name: string) => {
                  if (name === "cost") {
                    return [fmt(value), isPrice ? "Avg cost" : "Cost basis"];
                  }
                  return [fmt(value), isPrice ? "Price" : "Mark MV"];
                }}
                labelFormatter={(_, payload) => {
                  const row = payload?.[0]?.payload as { date?: string } | undefined;
                  const raw = row?.date ?? "";
                  if (raw.includes("T")) {
                    const d0 = new Date(raw);
                    if (!Number.isNaN(d0.getTime())) {
                      return d0.toLocaleString("en-US", {
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      });
                    }
                  }
                  return raw.slice(0, 10);
                }}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke={stroke}
                fill="url(#phFill)"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
                name="value"
              />
              {costRef != null && range !== "1d" && (
                <ReferenceLine
                  y={costRef}
                  stroke="rgba(251, 191, 36, 0.7)"
                  strokeDasharray="4 4"
                  strokeWidth={1.5}
                />
              )}
              {costRef != null && range !== "1d" && (
                <Line
                  type="monotone"
                  dataKey="cost"
                  stroke="rgba(251, 191, 36, 0.55)"
                  strokeWidth={1}
                  strokeDasharray="4 4"
                  dot={false}
                  isAnimationActive={false}
                  name="cost"
                  legendType="none"
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {missing.length > 0 && (
        <p className="text-[11px] text-warn">
          No Yahoo history for: {missing.slice(0, 12).join(", ")}
          {missing.length > 12 ? "…" : ""}
        </p>
      )}
      {(data?.meta.short_history_tickers?.length ?? 0) > 0 && (
        <p className="text-[11px] text-ink-muted">
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
        <p className="text-[11px] text-ink-faint">{data.meta.note}</p>
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
