import { useEffect, useMemo, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import type { UsdCzkSeries } from "../api/types";
import { TimeframePicker, type TimeframeValue } from "./TimeframePicker";
import { resolveTimeframe } from "../lib/timeframe";
import { d, formatCzk, formatUsd } from "../lib/money";
import { cn } from "../lib/cn";

type Props = {
  /** Current portfolio market value in USD (for CZK context) */
  portfolioUsd?: string | number | null;
};

const FX_TF_KEY = "gauntlet.fxUsdCzk.timeframe";

function loadFxTimeframe(): TimeframeValue {
  try {
    const raw = localStorage.getItem(FX_TF_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as TimeframeValue;
      if (parsed?.key && parsed?.to) return parsed;
    }
  } catch {
    /* ignore */
  }
  return resolveTimeframe("last_6m");
}

function saveFxTimeframe(v: TimeframeValue) {
  try {
    localStorage.setItem(FX_TF_KEY, JSON.stringify(v));
  } catch {
    /* ignore */
  }
}

function formatRate(n: number): string {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function shortDate(iso: string): string {
  // 2026-06-19 → Jun 19
  const d0 = new Date(iso + "T12:00:00");
  return d0.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/**
 * CNB USD/CZK rate chart with dashboard-style timeframe picker.
 * Optional portfolio context: revalue today's USD MV in CZK at each day's rate.
 */
export function FxUsdCzkChart({ portfolioUsd }: Props) {
  const [tf, setTf] = useState<TimeframeValue>(() => loadFxTimeframe());
  const [data, setData] = useState<UsdCzkSeries | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const onTf = (v: TimeframeValue) => {
    setTf(v);
    saveFxTimeframe(v);
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await api.fxUsdCzk({
          date_from: tf.from,
          date_to: tf.to,
          portfolio_usd: portfolioUsd ?? undefined,
        });
        if (!cancelled) setData(res);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load FX series");
          setData(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tf.from, tf.to, tf.key, portfolioUsd]);

  const chartRows = useMemo(() => {
    if (!data?.series?.length) return [];
    return data.series.map((p) => ({
      date: p.date,
      label: shortDate(p.date),
      rate: d(p.rate),
      portfolioCzk: p.portfolio_czk != null ? d(p.portfolio_czk) : undefined,
    }));
  }, [data]);

  const hasPortfolio =
    !!data?.portfolio &&
    chartRows.some((r) => r.portfolioCzk != null && Number.isFinite(r.portfolioCzk));

  const rateStart = d(data?.rate_start);
  const rateEnd = d(data?.rate_end);
  const changePct = data?.change_pct != null ? d(data.change_pct) : null;
  const changeAbs = data?.change_abs != null ? d(data.change_abs) : null;
  const fxDelta = data?.portfolio?.fx_delta_czk != null ? d(data.portfolio.fx_delta_czk) : null;

  const rateDomain = useMemo(() => {
    if (!chartRows.length) return [20, 25] as [number, number];
    const vals = chartRows.map((r) => r.rate);
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    const pad = Math.max(0.05, (hi - lo) * 0.12);
    return [lo - pad, hi + pad] as [number, number];
  }, [chartRows]);

  return (
    <div className="card p-5 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">CZK / USD exchange rate</h2>
          <p className="text-xs text-ink-faint">
            CNB mid-market · Kč per $1 · {tf.label}
            {data?.source ? ` · ${data.source}` : ""}
          </p>
        </div>
        {!loading && data && rateEnd > 0 && (
          <div className="text-right">
            <div className="text-lg font-semibold tabular-nums text-brand">
              {formatRate(rateEnd)}{" "}
              <span className="text-xs font-medium text-ink-muted">Kč/$</span>
            </div>
            {changePct != null && (
              <div
                className={cn(
                  "text-xs font-medium tabular-nums",
                  changePct > 0 ? "text-ok" : changePct < 0 ? "text-danger" : "text-ink-muted",
                )}
              >
                {changeAbs != null && changeAbs > 0 ? "+" : ""}
                {changeAbs != null ? formatRate(changeAbs) : "—"} Kč ·{" "}
                {changePct > 0 ? "+" : ""}
                {changePct.toFixed(2)}% in window
              </div>
            )}
          </div>
        )}
      </div>

      <TimeframePicker value={tf} onChange={onTf} />

      {/* Portfolio context */}
      {data?.portfolio && (
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5">
            <div className="text-[10px] font-medium uppercase tracking-wide text-ink-faint">
              Portfolio now (USD)
            </div>
            <div className="mt-0.5 text-sm font-semibold tabular-nums">
              {formatUsd(data.portfolio.portfolio_usd)}
            </div>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5">
            <div className="text-[10px] font-medium uppercase tracking-wide text-ink-faint">
              Same wealth in CZK (latest rate)
            </div>
            <div className="mt-0.5 text-sm font-semibold tabular-nums text-brand">
              {formatCzk(data.portfolio.portfolio_czk_now)}
            </div>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5">
            <div className="text-[10px] font-medium uppercase tracking-wide text-ink-faint">
              Pure FX on CZK reading
            </div>
            <div
              className={cn(
                "mt-0.5 text-sm font-semibold tabular-nums",
                fxDelta != null && fxDelta > 0
                  ? "text-ok"
                  : fxDelta != null && fxDelta < 0
                    ? "text-danger"
                    : "text-ink-muted",
              )}
            >
              {fxDelta == null
                ? "—"
                : `${fxDelta > 0 ? "+" : ""}${formatCzk(fxDelta)}`}
            </div>
            <div className="mt-0.5 text-[10px] text-ink-faint">
              vs start of window at fixed USD MV
              {rateStart > 0 && (
                <>
                  {" "}
                  ({formatRate(rateStart)} → {formatRate(rateEnd)} Kč/$)
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {loading && (
        <div className="flex h-56 items-center justify-center text-sm text-ink-muted">
          Loading CNB rates…
        </div>
      )}
      {error && !loading && (
        <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      )}
      {!loading && !error && chartRows.length === 0 && (
        <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-6 text-center text-sm text-ink-muted">
          No USD/CZK rates in this window. Run admin fetch-cnb / backfill-fx so FXRates is populated.
        </div>
      )}
      {!loading && chartRows.length > 0 && (
        <div className="h-64 w-full sm:h-72">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartRows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.12)" vertical={false} />
              <XAxis
                dataKey="label"
                tick={{ fill: "#64748b", fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: "rgba(148,163,184,0.2)" }}
                interval="preserveStartEnd"
                minTickGap={28}
              />
              <YAxis
                yAxisId="rate"
                domain={rateDomain}
                tick={{ fill: "#64748b", fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={48}
                tickFormatter={(v) => formatRate(Number(v))}
              />
              {hasPortfolio && (
                <YAxis
                  yAxisId="czk"
                  orientation="right"
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
              )}
              <Tooltip
                contentStyle={{
                  background: "#0f172a",
                  border: "1px solid rgba(148,163,184,0.25)",
                  borderRadius: 12,
                  fontSize: 12,
                }}
                labelStyle={{ color: "#94a3b8" }}
                formatter={(value: number, name: string) => {
                  if (name === "rate") return [`${formatRate(value)} Kč/$`, "CNB rate"];
                  if (name === "portfolioCzk") return [formatCzk(value), "Portfolio in CZK"];
                  return [value, name];
                }}
                labelFormatter={(_, payload) => {
                  const row = payload?.[0]?.payload as { date?: string } | undefined;
                  return row?.date ?? "";
                }}
              />
              {hasPortfolio && (
                <Area
                  yAxisId="czk"
                  type="monotone"
                  dataKey="portfolioCzk"
                  name="portfolioCzk"
                  stroke="rgba(56,189,248,0.55)"
                  fill="rgba(56,189,248,0.12)"
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
              )}
              <Line
                yAxisId="rate"
                type="monotone"
                dataKey="rate"
                name="rate"
                stroke="#34d399"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              {hasPortfolio && (
                <Legend
                  wrapperStyle={{ fontSize: 11, color: "#94a3b8" }}
                  formatter={(value) =>
                    value === "rate"
                      ? "CZK per USD"
                      : value === "portfolioCzk"
                        ? "Portfolio in CZK (fixed USD MV)"
                        : value
                  }
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {data?.portfolio?.note && (
        <p className="text-[11px] leading-relaxed text-ink-faint">{data.portfolio.note}</p>
      )}
    </div>
  );
}
