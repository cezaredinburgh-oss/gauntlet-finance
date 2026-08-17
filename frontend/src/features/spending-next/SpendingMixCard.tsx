import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Link } from "react-router-dom";
import type { DashboardSummary } from "../../api/types";
import { EmptyState } from "../../components/Spinner";
import { TimeframePicker, type TimeframeValue } from "../../components/TimeframePicker";
import { formatUsd } from "../../lib/money";
import {
  CATEGORY_TOP_N,
  NECESSITY_COLORS,
  NECESSITY_LABEL,
  buildCategoryBars,
  categoryChartHeight,
  truncateCategoryName,
  type CategoryBar,
} from "./categoryBars";
import type { HonestyChip } from "./honestyChips";
import { SpendingPulseMetrics } from "./SpendingPulseMetrics";

export function SpendingMixCard({
  tf,
  onTimeframeChange,
  dash,
  loading,
  chips,
  onBarClick,
}: {
  tf: TimeframeValue;
  onTimeframeChange: (next: TimeframeValue) => void;
  dash: DashboardSummary;
  loading: boolean;
  chips: HonestyChip[];
  onBarClick: (bar: CategoryBar) => void;
}) {
  const categoryData = useMemo(
    () => buildCategoryBars(dash.spending?.by_category ?? []),
    [dash.spending?.by_category],
  );
  const chartHeight = categoryChartHeight(categoryData.length);

  return (
    <div className="card min-w-0 max-w-full space-y-4 p-5">
      <div className="min-w-0 max-w-full space-y-2">
        <div className="flex min-w-0 max-w-full flex-wrap items-start gap-2">
          <div className="min-w-0 max-w-full flex-1 basis-full sm:basis-[20rem]">
            <TimeframePicker value={tf} onChange={onTimeframeChange} />
          </div>
          {chips.length > 0 ? (
            <div className="flex min-w-0 flex-wrap gap-1.5">
              {chips.map((chip) => (
                <span key={chip.kind} className="badge bg-white/5 text-ink-muted">
                  {chip.label}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <p className="min-w-0 max-w-full break-words text-xs text-ink-faint">
          {tf.label} · excludes internal transfers · USD · CZK hover
          {loading ? <span className="ml-2">Updating…</span> : null}
        </p>
      </div>

      <SpendingPulseMetrics dash={dash} />

      <div className="min-w-0 max-w-full">
        <div className="mb-2 flex flex-wrap gap-2">
          {Object.entries(NECESSITY_LABEL).map(([key, label]) => (
            <span key={key} className="badge bg-white/5 text-ink-muted">
              <span
                className="mr-1.5 inline-block h-2 w-2 rounded-full"
                style={{ background: NECESSITY_COLORS[key] || "#64748b" }}
              />
              {label}
            </span>
          ))}
        </div>
        {categoryData.length === 0 ? (
          <EmptyState
            title="No expense data"
            action={
              <Link to="/upload" className="font-medium text-brand hover:underline">
                Upload statements or pick another range
              </Link>
            }
          />
        ) : (
          <div style={{ height: chartHeight }} className="mt-2 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={categoryData}
                layout="vertical"
                margin={{ top: 4, right: 24, left: 8, bottom: 4 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#2e3a4d" horizontal={false} />
                <XAxis
                  type="number"
                  stroke="#6b7a90"
                  fontSize={11}
                  tickFormatter={(v: number) => `$${Math.round(v).toLocaleString()}`}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  stroke="#6b7a90"
                  fontSize={11}
                  width={148}
                  tick={{ fill: "#9aa8bc" }}
                  tickFormatter={(v: string) => truncateCategoryName(String(v))}
                />
                <Tooltip
                  cursor={{ fill: "rgba(255,255,255,0.06)" }}
                  contentStyle={{
                    background: "#0f1419",
                    border: "1px solid #3d4f66",
                    borderRadius: 12,
                    color: "#f1f5f9",
                    boxShadow: "0 12px 40px rgba(0,0,0,0.45)",
                    padding: "10px 12px",
                  }}
                  labelStyle={{
                    color: "#e2e8f0",
                    fontWeight: 600,
                    marginBottom: 4,
                  }}
                  itemStyle={{
                    color: "#f8fafc",
                    fontWeight: 500,
                  }}
                  formatter={(v: number, _n: string, item: { payload?: CategoryBar }) => {
                    const p = item?.payload;
                    if (p?.id === "other_rollup") {
                      const names = p.rollupNames?.slice(0, 8) ?? [];
                      const more =
                        (p.rollupNames?.length ?? 0) > 8
                          ? ` +${(p.rollupNames!.length - 8)} more`
                          : "";
                      const list = names.length ? ` · ${names.join(", ")}${more}` : "";
                      return [
                        `${formatUsd(v)} · ${p.pct}% · outside top ${CATEGORY_TOP_N} by spend (not Uncategorized)${list}`,
                        "Spend",
                      ];
                    }
                    const nec = p ? NECESSITY_LABEL[p.necessity] || p.necessity : "";
                    const domain = p?.life_domain || "";
                    const pct = p?.pct != null ? `${p.pct}%` : "";
                    return [`${formatUsd(v)} · ${pct} · ${domain} · ${nec}`, "Spend"];
                  }}
                />
                <Bar
                  dataKey="value"
                  radius={[0, 6, 6, 0]}
                  barSize={18}
                  cursor="pointer"
                  onClick={(state) => {
                    const payload = (state as { payload?: CategoryBar })?.payload;
                    if (payload) onBarClick(payload);
                  }}
                >
                  {categoryData.map((e) => (
                    <Cell
                      key={e.id}
                      fill={NECESSITY_COLORS[e.necessity] || "#64748b"}
                      cursor="pointer"
                      onClick={() => onBarClick(e)}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}
