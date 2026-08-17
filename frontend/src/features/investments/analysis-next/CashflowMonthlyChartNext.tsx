import { useMemo } from "react";
import {
  ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Legend,
} from "recharts";
import type { PortfolioSnapshot } from "../../../api/types";
import { d, formatUsd } from "../../../lib/money";
import { cn } from "../../../lib/cn";
import {
  netSecurityCashUsd,
  sliceCashflowWindow,
  type CashflowMonthsPref,
} from "./cashflowNet";

function formatMonthLabel(ym: string): string {
  const [ys, ms] = ym.split("-");
  const y = Number(ys);
  const m = Number(ms);
  if (!y || !m) return ym;
  const d0 = new Date(y, m - 1, 1);
  return d0.toLocaleDateString("en-GB", { month: "short", year: "2-digit" });
}

const CASHFLOW_BOUGHT = "#34d399";
const CASHFLOW_SOLD = "#e07a5f";

function CashflowTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ dataKey?: string; value?: number; payload?: Record<string, unknown> }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload as
    | {
        monthFull?: string;
        bought?: number;
        sold?: number;
        net?: number;
      }
    | undefined;
  if (!row) return null;
  return (
    <div className="rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-xs shadow-xl">
      <div className="mb-1.5 font-semibold text-ink">{row.monthFull || label}</div>
      <div className="space-y-0.5 text-ink-muted">
        <div className="flex justify-between gap-6">
          <span style={{ color: CASHFLOW_BOUGHT }}>Bought</span>
          <span className="font-medium text-ink">{formatUsd(row.bought ?? 0)}</span>
        </div>
        <div className="flex justify-between gap-6">
          <span style={{ color: CASHFLOW_SOLD }}>Sold</span>
          <span className="font-medium text-ink">{formatUsd(row.sold ?? 0)}</span>
        </div>
        <div className="flex justify-between gap-6">
          <span>Net (bought − sold)</span>
          <span className="font-medium text-ink">{formatUsd(row.net ?? 0)}</span>
        </div>
      </div>
    </div>
  );
}

export function CashflowMonthlyChartNext({
  series,
  monthsPref,
  onMonthsPrefChange,
}: {
  series: NonNullable<PortfolioSnapshot["cashflow_monthly"]>;
  monthsPref: CashflowMonthsPref;
  onMonthsPrefChange: (pref: CashflowMonthsPref) => void;
}) {
  const fullData = useMemo(
    () =>
      series.map((r) => {
        const bought = d(r.bought_usd);
        const sold = d(r.sold_usd);
        return {
          month: formatMonthLabel(r.month),
          monthFull: r.month,
          bought,
          sold,
          net: bought - sold,
        };
      }),
    [series],
  );

  const windowRows = useMemo(
    () => sliceCashflowWindow(series, monthsPref),
    [series, monthsPref],
  );

  const data = useMemo(
    () =>
      windowRows.map((r) => {
        const bought = d(r.bought_usd);
        const sold = d(r.sold_usd);
        return {
          month: formatMonthLabel(r.month),
          monthFull: r.month,
          bought,
          sold,
          net: bought - sold,
        };
      }),
    [windowRows],
  );

  const windowCum = useMemo(() => netSecurityCashUsd(windowRows), [windowRows]);

  const lastRow = fullData[fullData.length - 1];
  const maxCash = Math.max(
    1,
    ...data.map((r) => Math.max(r.bought, r.sold)),
  );

  const rangeLabel =
    monthsPref === "all"
      ? data.length <= 1
        ? "all history"
        : `all history · ${data.length} months`
      : `last ${monthsPref} months`;

  const prefOptions: { id: CashflowMonthsPref; label: string }[] = [
    { id: "6", label: "6m" },
    { id: "12", label: "12m" },
    { id: "24", label: "24m" },
    { id: "all", label: "All" },
  ];

  return (
    <div className="card p-5">
      <div className="mb-1 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Buy vs sell cash</h2>
          <p className="text-xs text-ink-faint">
            Monthly investment cash (Buy/Sell value_usd) · {rangeLabel}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div
            role="group"
            aria-label="Cashflow timeframe"
            className="inline-flex rounded-full border border-white/10 p-0.5"
          >
            {prefOptions.map((opt) => (
              <button
                key={opt.id}
                type="button"
                aria-pressed={monthsPref === opt.id}
                onClick={() => onMonthsPrefChange(opt.id)}
                className={cn(
                  "rounded-full px-2.5 py-1 text-[11px] transition-colors",
                  monthsPref === opt.id
                    ? "bg-white/10 text-ink"
                    : "text-ink-faint hover:text-ink-muted",
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>
          {data.length > 0 && (
            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-right text-[11px]">
              <span className="text-ink-faint">Invested (cum.)</span>
              <span className="font-medium" style={{ color: CASHFLOW_BOUGHT }}>
                {formatUsd(windowCum.invested)}
              </span>
              <span className="text-ink-faint">Proceeds (cum.)</span>
              <span className="font-medium" style={{ color: CASHFLOW_SOLD }}>
                {formatUsd(windowCum.proceeds)}
              </span>
              <span className="text-ink-faint">Net capital (cum.)</span>
              <span className="font-medium text-ink">
                {formatUsd(windowCum.netDeployed)}
              </span>
            </div>
          )}
        </div>
      </div>

      {lastRow && (
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <div className="rounded-lg border border-white/10 bg-slate-950/50 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wide text-ink-faint">
              Last month bought
            </div>
            <div className="text-sm font-semibold" style={{ color: CASHFLOW_BOUGHT }}>
              {formatUsd(lastRow.bought)}
            </div>
          </div>
          <div className="rounded-lg border border-white/10 bg-slate-950/50 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wide text-ink-faint">
              Last month sold
            </div>
            <div className="text-sm font-semibold" style={{ color: CASHFLOW_SOLD }}>
              {formatUsd(lastRow.sold)}
            </div>
          </div>
          <div className="rounded-lg border border-white/10 bg-slate-950/50 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wide text-ink-faint">
              Last month net
            </div>
            <div className="text-sm font-semibold text-ink">
              {formatUsd(lastRow.net)}
            </div>
          </div>
        </div>
      )}

      <div className="mt-4 h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            margin={{ top: 12, right: 12, left: 4, bottom: 4 }}
            barGap={2}
            barCategoryGap="18%"
          >
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" vertical={false} />
            <XAxis
              dataKey="month"
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              interval="preserveStartEnd"
              minTickGap={16}
              axisLine={{ stroke: "rgba(148,163,184,0.25)" }}
              tickLine={false}
            />
            <YAxis
              domain={[0, Math.ceil(maxCash * 1.1)]}
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              tickFormatter={(v: number) =>
                v >= 1000 ? `$${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}k` : `$${v}`
              }
              axisLine={false}
              tickLine={false}
              width={52}
            />
            <Tooltip content={<CashflowTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Legend
              wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
              formatter={(value) => <span className="text-ink-muted">{value}</span>}
            />
            <Bar
              dataKey="bought"
              name="Bought"
              fill={CASHFLOW_BOUGHT}
              fillOpacity={0.85}
              radius={[3, 3, 0, 0]}
              maxBarSize={28}
            />
            <Bar
              dataKey="sold"
              name="Sold"
              fill={CASHFLOW_SOLD}
              fillOpacity={0.85}
              radius={[3, 3, 0, 0]}
              maxBarSize={28}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ul className="mt-3 space-y-0.5 text-[11px] text-ink-faint">
        <li>
          <span className="font-medium text-ink-muted">Bought</span>
          {" — "}
          statement Buy value_usd, FX-filled when missing.
        </li>
        <li>
          <span className="font-medium text-ink-muted">Sold</span>
          {" — "}
          statement Sell value_usd, FX-filled when missing.
        </li>
        <li>
          <span className="font-medium text-ink-muted">Net capital</span>
          {" — "}
          bought − sold over the selected window.
        </li>
        <li>
          <span className="font-medium text-ink-muted">Not a return.</span>
          {" "}
          Marks live on Holdings.
        </li>
      </ul>
      <p className="mt-2 text-[11px] text-ink-faint">
        Net capital = bought − sold (cash deployed). Positive = more bought than sold.
      </p>
    </div>
  );
}
