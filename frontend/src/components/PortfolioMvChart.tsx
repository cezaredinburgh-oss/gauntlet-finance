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
import type { MvSeries } from "../api/types";
import { TimeframePicker, type TimeframeValue } from "./TimeframePicker";
import { resolveTimeframe } from "../lib/timeframe";
import { d, formatUsd } from "../lib/money";

const TF_KEY = "gauntlet.mvSeries.timeframe";

function loadTf(): TimeframeValue {
  try {
    const raw = localStorage.getItem(TF_KEY);
    if (raw) {
      const p = JSON.parse(raw) as TimeframeValue;
      if (p?.key && p?.to) return p;
    }
  } catch {
    /* ignore */
  }
  return resolveTimeframe("last_6m");
}

function shortDate(iso: string): string {
  const d0 = new Date(iso + "T12:00:00");
  return d0.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function PortfolioMvChart() {
  const [tf, setTf] = useState<TimeframeValue>(() => loadTf());
  const [data, setData] = useState<MvSeries | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const onTf = (v: TimeframeValue) => {
    setTf(v);
    try {
      localStorage.setItem(TF_KEY, JSON.stringify(v));
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
        const res = await api.mvSeries({
          date_from: tf.from,
          date_to: tf.to,
        });
        if (!cancelled) setData(res);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load MV series");
          setData(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tf.from, tf.to, tf.key]);

  const rows = useMemo(() => {
    if (!data?.series?.length) return [];
    return data.series
      .filter((p) => p.total_market_value_usd != null)
      .map((p) => ({
        date: p.date,
        label: shortDate(p.date),
        mv: d(p.total_market_value_usd),
        cost: p.total_cost_basis_usd != null ? d(p.total_cost_basis_usd) : undefined,
      }));
  }, [data]);

  const last = rows[rows.length - 1];
  const first = rows[0];
  const delta =
    last && first && first.mv > 0 ? ((last.mv - first.mv) / first.mv) * 100 : null;

  return (
    <div className="card space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Portfolio market value</h2>
          <p className="text-xs text-ink-faint">
            Daily snapshots (recorded on price refresh) · {tf.label} · forward history only
          </p>
        </div>
        {last && (
          <div className="text-right">
            <div className="text-lg font-semibold tabular-nums text-brand">
              {formatUsd(last.mv)}
            </div>
            {delta != null && (
              <div
                className={
                  delta >= 0 ? "text-xs text-ok" : "text-xs text-danger"
                }
              >
                {delta >= 0 ? "+" : ""}
                {delta.toFixed(1)}% in window
              </div>
            )}
          </div>
        )}
      </div>

      <TimeframePicker value={tf} onChange={onTf} />

      {loading && (
        <div className="flex h-56 items-center justify-center text-sm text-ink-muted">
          Loading MV series…
        </div>
      )}
      {error && !loading && (
        <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      )}
      {!loading && !error && rows.length === 0 && (
        <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-6 text-center text-sm text-ink-muted">
          No snapshots yet. Use <strong className="text-ink">Update prices</strong> on the
          dashboard (or run the <code className="text-ink">portfolio-snapshot</code> job in
          Settings) to start the series.
        </div>
      )}
      {!loading && rows.length > 0 && (
        <div className="h-64 w-full sm:h-72">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
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
                contentStyle={{
                  background: "#0f172a",
                  border: "1px solid rgba(148,163,184,0.25)",
                  borderRadius: 12,
                  fontSize: 12,
                }}
                formatter={(value: number, name: string) => [
                  formatUsd(value),
                  name === "mv" ? "Market value" : "Cost basis",
                ]}
                labelFormatter={(_, payload) => {
                  const row = payload?.[0]?.payload as { date?: string } | undefined;
                  return row?.date ?? "";
                }}
              />
              <Area
                type="monotone"
                dataKey="mv"
                name="mv"
                stroke="#38bdf8"
                fill="rgba(56,189,248,0.15)"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="cost"
                name="cost"
                stroke="#94a3b8"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
              <Legend
                wrapperStyle={{ fontSize: 11, color: "#94a3b8" }}
                formatter={(v) =>
                  v === "mv" ? "Market value USD" : "Cost basis USD"
                }
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
