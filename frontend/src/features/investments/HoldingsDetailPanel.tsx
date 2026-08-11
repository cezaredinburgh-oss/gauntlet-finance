import {
  Cell,
  ResponsiveContainer,
  Tooltip,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import { Copy, Check } from "lucide-react";
import type { TickerDigest } from "../../api/types";
import { Money } from "../../components/Money";
import { d, formatQty, formatUsd } from "../../lib/money";
import { cn } from "../../lib/cn";
import { gradeStyleClass } from "./gradeStyles";

const TAX_TRANCHE_COLORS: Record<string, string> = {
  now: "#2dd4a8",
  later_this_year: "#38bdf8",
  next_year: "#fbbf24",
  year_after: "#f87171",
};

const PLATFORM_COLORS = ["#3d9cf0", "#a78bfa", "#fbbf24", "#2dd4a8", "#f87171", "#38bdf8"];

/**
 * Full ticker verify panel (platforms, tax tranches, ROI detail).
 * Migrated from former TickerDigestPanel — no data loss.
 */
export function HoldingsDetailPanel({
  digest,
  copied,
  onCopy,
}: {
  digest: TickerDigest;
  copied: boolean;
  onCopy: () => void;
}) {
  const platformData = digest.by_platform.map((p, i) => ({
    name: p.source,
    quantity: d(p.quantity),
    fill: PLATFORM_COLORS[i % PLATFORM_COLORS.length],
  }));

  const trancheTotalMv = digest.tax_tranches.reduce(
    (s, t) => s + d(t.market_value_usd),
    0,
  );

  const gradeCls = gradeStyleClass(digest.roi_grade);
  const growth = digest.growth_contribution_pp;
  const growthSign = growth != null && growth >= 0 ? "+" : "";

  return (
    <div className="card flex h-full flex-col">
      <div className="border-b border-white/5 px-4 py-3">
        <h2 className="text-sm font-semibold tracking-tight">Position detail</h2>
        <p className="text-xs text-ink-faint">
          Compare quantities with your broker apps
        </p>
      </div>
      <div className="space-y-5 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-xl font-bold tracking-tight">{digest.ticker}</h3>
              {digest.multi_platform && (
                <span className="badge bg-warn/15 text-warn">Multi-platform</span>
              )}
              {digest.missing_price && (
                <span className="badge bg-warn/15 text-warn">No price</span>
              )}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span className="text-2xl font-semibold tabular-nums text-ok">
                {formatQty(digest.quantity_total)}
              </span>
              <span className="text-sm text-ok/80">units owned</span>
              <button
                type="button"
                className="inline-flex items-center gap-1 rounded-md bg-white/5 px-2 py-0.5 text-[11px] text-ink-muted hover:bg-white/10 hover:text-ink"
                onClick={onCopy}
                title="Copy total quantity"
              >
                {copied ? <Check className="h-3 w-3 text-ok" /> : <Copy className="h-3 w-3" />}
                {copied ? "Copied" : "Copy qty"}
              </button>
            </div>
            <div className="mt-1 text-xs text-ink-faint">
              {digest.price_usd
                ? `Mark ${formatUsd(digest.price_usd)}${
                    digest.price_as_of ? ` · ${digest.price_as_of}` : ""
                  }`
                : "No market quote yet — use Update prices in the header"}
              {" · "}
              Avg cost {formatUsd(digest.avg_cost_usd)}
            </div>
            {digest.missing_price && (
              <div className="mt-2 rounded-lg border border-warn/25 bg-warn/10 px-2.5 py-1.5 text-[11px] text-warn">
                ROI, growth contribution, and market value need a live quote. Cost basis is
                shown below until prices load.
              </div>
            )}
          </div>
          <div
            className={cn(
              "flex h-16 w-16 flex-col items-center justify-center rounded-2xl ring-1",
              gradeCls,
            )}
          >
            <span className="text-2xl font-bold leading-none">{digest.roi_grade}</span>
            <span className="mt-0.5 text-[10px] font-medium opacity-80">
              {digest.roi_grade_label}
            </span>
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-1 xl:grid-cols-1">
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-faint">
              Quantity by platform
            </h4>
            <div className="mb-2 h-36">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={platformData}
                  layout="vertical"
                  margin={{ top: 0, right: 12, left: 4, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#2e3a4d" horizontal={false} />
                  <XAxis
                    type="number"
                    stroke="#6b7a90"
                    fontSize={11}
                    tickFormatter={(v: number) => formatQty(String(v))}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={72}
                    stroke="#6b7a90"
                    fontSize={11}
                  />
                  <Tooltip
                    cursor={false}
                    contentStyle={{
                      background: "#1a2332",
                      border: "1px solid #2e3a4d",
                      borderRadius: 12,
                    }}
                    labelStyle={{ color: "#94a3b8" }}
                    itemStyle={{ color: "#34d399" }}
                    formatter={(v: number) => [formatQty(String(v)), "Qty"]}
                  />
                  <Bar
                    dataKey="quantity"
                    radius={[0, 6, 6, 0]}
                    barSize={16}
                    activeBar={false}
                  >
                    {platformData.map((e) => (
                      <Cell key={e.name} fill={e.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-ink-faint">
                  <tr>
                    <th className="pb-1 font-medium">Platform</th>
                    <th className="pb-1 font-medium text-right">Qty</th>
                    <th className="pb-1 font-medium text-right">Cost</th>
                    <th className="pb-1 font-medium text-right">MV</th>
                    <th className="pb-1 font-medium text-right">Lots</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {digest.by_platform.map((p) => (
                    <tr key={p.source}>
                      <td className="py-1.5 font-medium">{p.source}</td>
                      <td className="py-1.5 text-right tabular-nums">
                        {formatQty(p.quantity)}
                      </td>
                      <td className="py-1.5 text-right tabular-nums">
                        {formatUsd(p.cost_basis_usd)}
                      </td>
                      <td className="py-1.5 text-right tabular-nums">
                        {formatUsd(p.market_value_usd)}
                      </td>
                      <td className="py-1.5 text-right text-ink-muted">{p.lot_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-faint">
                Market value by tax status
              </h4>
              {trancheTotalMv > 0 ? (
                <>
                  <div className="flex h-8 w-full overflow-hidden rounded-lg ring-1 ring-white/10">
                    {digest.tax_tranches.map((t) => {
                      const mv = d(t.market_value_usd);
                      if (mv <= 0) return null;
                      const pct = (mv / trancheTotalMv) * 100;
                      return (
                        <div
                          key={t.key}
                          title={`${t.label}: ${formatUsd(t.market_value_usd)} · ${formatQty(t.quantity)} units`}
                          style={{
                            width: `${Math.max(pct, 1.5)}%`,
                            background: TAX_TRANCHE_COLORS[t.key] || "#64748b",
                          }}
                          className="h-full transition"
                        />
                      );
                    })}
                  </div>
                  <ul className="mt-2 space-y-1">
                    {digest.tax_tranches.map((t) => {
                      const mv = d(t.market_value_usd);
                      if (mv <= 0) return null;
                      return (
                        <li
                          key={t.key}
                          className="flex items-center justify-between gap-2 text-xs"
                        >
                          <span className="flex items-center gap-1.5 text-ink-muted">
                            <span
                              className="inline-block h-2 w-2 rounded-full"
                              style={{
                                background: TAX_TRANCHE_COLORS[t.key] || "#64748b",
                              }}
                            />
                            {t.label}
                            <span className="text-ink-faint">
                              ({formatQty(t.quantity)})
                            </span>
                          </span>
                          <span className="font-medium tabular-nums">
                            {formatUsd(t.market_value_usd)}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </>
              ) : (
                <p className="text-xs text-ink-faint">No market value for tax split.</p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                <div className="label mb-1">Unrealized</div>
                {digest.unrealized_usd != null ? (
                  <>
                    <Money
                      amount={digest.unrealized_usd}
                      currency="USD"
                      secondaryMode="hover"
                      size="lg"
                      signed
                    />
                    {digest.unrealized_pct != null && (
                      <div
                        className={cn(
                          "text-xs",
                          digest.unrealized_pct >= 0 ? "text-ok" : "text-danger",
                        )}
                      >
                        {digest.unrealized_pct >= 0 ? "+" : ""}
                        {digest.unrealized_pct.toFixed(1)}% total
                      </div>
                    )}
                    {digest.annualized_unrealized_pct != null ? (
                      <div
                        className={cn(
                          "text-[11px] tabular-nums",
                          digest.annualized_unrealized_pct >= 0 ? "text-ok" : "text-danger",
                        )}
                        title="CAGR from cost→MV over cost-weighted holding years"
                      >
                        {digest.annualized_unrealized_pct >= 0 ? "+" : ""}
                        {digest.annualized_unrealized_pct.toFixed(1)}% ann.
                        {digest.holding_years != null && (
                          <span className="text-ink-faint">
                            {" "}
                            · {digest.holding_years.toFixed(1)}y wtd
                          </span>
                        )}
                      </div>
                    ) : digest.holding_years != null &&
                      digest.holding_years * 365.25 < 90 ? (
                      <div className="text-[11px] text-ink-faint">
                        Ann. n/a (&lt;90d wtd hold)
                      </div>
                    ) : null}
                  </>
                ) : (
                  <>
                    <span className="text-lg text-ink-faint">—</span>
                    <div className="text-[11px] text-ink-faint">Needs market quote</div>
                  </>
                )}
              </div>
              <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                <div className="label mb-1">
                  {digest.market_value_usd ? "Market value" : "Cost (no quote)"}
                </div>
                {digest.market_value_usd ? (
                  <Money
                    amount={digest.market_value_usd}
                    currency="USD"
                    secondaryMode="hover"
                    size="lg"
                  />
                ) : (
                  <Money
                    amount={digest.cost_basis_usd}
                    currency="USD"
                    secondaryMode="hover"
                    size="lg"
                  />
                )}
                <div className="text-xs text-ink-faint">
                  Cost {formatUsd(digest.cost_basis_usd)}
                </div>
              </div>
              <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                <div className="label mb-1">Portfolio weight</div>
                <div className="text-xl font-semibold tabular-nums">
                  {digest.portfolio_weight_pct.toFixed(1)}%
                </div>
                <div className="text-[11px] text-ink-faint">
                  {digest.missing_price ? "of portfolio (cost mix)" : "of portfolio MV"}
                </div>
              </div>
              <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                <div className="label mb-1">Growth contribution</div>
                <div
                  className={cn(
                    "text-xl font-semibold tabular-nums",
                    growth != null && growth >= 0
                      ? "text-ok"
                      : growth != null
                        ? "text-danger"
                        : "text-ink-faint",
                  )}
                >
                  {growth == null ? "—" : `${growthSign}${growth.toFixed(1)} pp`}
                </div>
                <div className="text-[11px] text-ink-faint">
                  {growth == null ? "Needs market quote" : "of portfolio return"}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-white/5 pt-3 text-[11px] text-ink-faint">
          <span>
            Open lots: <span className="text-ink-muted">{digest.open_lot_count}</span>
          </span>
          {digest.first_acquired && (
            <span>
              First: <span className="text-ink-muted">{digest.first_acquired}</span>
            </span>
          )}
          {digest.last_acquired && (
            <span>
              Last: <span className="text-ink-muted">{digest.last_acquired}</span>
            </span>
          )}
          {digest.next_unlock_date ? (
            <span>
              Next unlock:{" "}
              <span className="text-warn">
                {digest.next_unlock_date}
                {digest.next_unlock_quantity
                  ? ` (${formatQty(digest.next_unlock_quantity)})`
                  : ""}
              </span>
            </span>
          ) : (
            <span className="text-ok">All open qty tax-eligible</span>
          )}
          <span>
            Realized lifetime:{" "}
            <span className="text-ink-muted">
              {formatUsd(digest.realized_lifetime_usd)}
              {digest.realized_cost_basis_usd != null &&
                d(digest.realized_cost_basis_usd) > 0 && (
                  <>
                    {" "}
                    on {formatUsd(digest.realized_cost_basis_usd)} sold
                    {digest.realized_roi_pct != null && (
                      <>
                        {" "}
                        (
                        {digest.realized_roi_pct >= 0 ? "+" : ""}
                        {digest.realized_roi_pct.toFixed(0)}%)
                      </>
                    )}
                  </>
                )}
            </span>
          </span>
        </div>
      </div>
    </div>
  );
}
