import { useEffect, useMemo, useState } from "react";
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
import { api } from "../../api/client";
import type { PriceHistory, PriceHistoryRange, TickerDigest } from "../../api/types";
import { d, formatUsd } from "../../lib/money";
import { cn } from "../../lib/cn";

const RANGES: { key: PriceHistoryRange; label: string }[] = [
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
  | { kind: "asset_class"; asset_class: "Stock" | "Crypto" }
  | { kind: "ticker"; ticker: string };

type Props = {
  digests: TickerDigest[];
  /** Controlled scope from parent (sync with selected ticker). */
  scope: ChartScope;
  onScopeChange: (scope: ChartScope) => void;
};

function loadRange(): PriceHistoryRange {
  try {
    const raw = localStorage.getItem(RANGE_KEY);
    if (raw && RANGES.some((r) => r.key === raw)) return raw as PriceHistoryRange;
  } catch {
    /* ignore */
  }
  return "1y";
}

function shortDate(iso: string): string {
  const d0 = new Date(iso + "T12:00:00");
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

export function PositionHistoryChart({ digests, scope, onScopeChange }: Props) {
  const [range, setRange] = useState<PriceHistoryRange>(() => loadRange());
  const [data, setData] = useState<PriceHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const hasStock = digests.some((t) => (t.asset_class || "").toLowerCase() === "stock");
  const hasCrypto = digests.some((t) => (t.asset_class || "").toLowerCase() === "crypto");

  const onRange = (key: PriceHistoryRange) => {
    setRange(key);
    try {
      localStorage.setItem(RANGE_KEY, key);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res =
          scope.kind === "ticker"
            ? await api.priceHistory({
                scope: "ticker",
                ticker: scope.ticker,
                range,
              })
            : await api.priceHistory({
                scope: "asset_class",
                asset_class: scope.asset_class,
                range,
              });
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
  }, [scope, range]);

  // Soft refetch when prices updated (cache usually hits)
  useEffect(() => {
    const onPrices = () => {
      // Force remount of fetch by touching range via noop setState pattern —
      // re-run effect by cloning scope dependency through a light refetch.
      void (async () => {
        try {
          const res =
            scope.kind === "ticker"
              ? await api.priceHistory({
                  scope: "ticker",
                  ticker: scope.ticker,
                  range,
                })
              : await api.priceHistory({
                  scope: "asset_class",
                  asset_class: scope.asset_class,
                  range,
                });
          setData(res);
          setError(null);
        } catch {
          /* keep previous series */
        }
      })();
    };
    window.addEventListener("prices-updated", onPrices);
    return () => window.removeEventListener("prices-updated", onPrices);
  }, [scope, range]);

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
      label: shortDate(p.date),
      value: d(p.value),
      cost,
    }));
  }, [data]);

  const last = rows[rows.length - 1];
  const first = rows[0];
  const changePct = data?.meta.change_pct ?? null;
  const changeAbs =
    last && first ? last.value - first.value : null;
  const isPrice = data?.series_kind === "price";
  const costRef =
    isPrice && data?.meta.avg_cost_usd != null
      ? d(data.meta.avg_cost_usd)
      : !isPrice && data?.meta.cost_basis_usd != null
        ? d(data.meta.cost_basis_usd)
        : null;

  const missing = data?.meta.missing_tickers ?? [];
  const positive = changePct != null ? changePct >= 0 : true;
  const stroke = positive ? "#2dd4a8" : "#f87171";

  const title =
    scope.kind === "ticker"
      ? scope.ticker
      : scope.asset_class === "Crypto"
        ? "All crypto"
        : "All stocks";

  return (
    <div className="card space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Price history · {title}</h2>
          <p className="text-xs text-ink-faint">
            {scope.kind === "asset_class"
              ? "Current holdings marked at historical closes · free Yahoo data"
              : "Daily close (USD) · avg cost from open lots"}
          </p>
        </div>
        {last && !loading && (
          <div className="text-right">
            <div className="text-lg font-semibold tabular-nums text-brand">
              {isPrice ? formatPrice(last.value) : formatUsd(last.value)}
            </div>
            {changePct != null && (
              <div className={cn("text-xs", positive ? "text-ok" : "text-danger")}>
                {changeAbs != null && (
                  <span className="mr-1.5 tabular-nums">
                    {changeAbs >= 0 ? "+" : ""}
                    {isPrice ? formatPrice(changeAbs) : formatUsd(changeAbs)}
                  </span>
                )}
                {changePct >= 0 ? "+" : ""}
                {changePct.toFixed(1)}%
              </div>
            )}
            {costRef != null && (
              <div className="text-[11px] text-ink-faint">
                {isPrice ? "Avg cost " : "Cost basis "}
                {isPrice ? formatPrice(costRef) : formatUsd(costRef)}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Scope chips */}
      <div className="flex flex-wrap gap-1.5">
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
        <div className="flex h-56 items-center justify-center text-sm text-ink-muted">
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
          No history returned for this scope. Yahoo may not cover this symbol.
        </div>
      )}
      {!loading && rows.length > 0 && (
        <div className="h-64 w-full sm:h-72">
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
                minTickGap={28}
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
                    return [
                      isPrice ? formatPrice(value) : formatUsd(value),
                      isPrice ? "Avg cost" : "Cost basis",
                    ];
                  }
                  return [
                    isPrice ? formatPrice(value) : formatUsd(value),
                    isPrice ? "Close" : "Mark MV",
                  ];
                }}
                labelFormatter={(_, payload) => {
                  const row = payload?.[0]?.payload as { date?: string } | undefined;
                  return row?.date ?? "";
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
              {costRef != null && (
                <ReferenceLine
                  y={costRef}
                  stroke="rgba(251, 191, 36, 0.7)"
                  strokeDasharray="4 4"
                  strokeWidth={1.5}
                />
              )}
              {costRef != null && (
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
