import { useEffect, useState } from "react";
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
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { DashboardSummary } from "../api/types";
import { Money } from "../components/Money";
import { HoverPanel } from "../components/HoverPanel";
import { TimeframePicker, type TimeframeValue } from "../components/TimeframePicker";
import {
  loadStoredSpendingTimeframe,
  saveStoredSpendingTimeframe,
} from "../lib/timeframe";
import { EmptyState, PageLoader } from "../components/Spinner";
import { d, formatUsd } from "../lib/money";
import { cn } from "../lib/cn";

type CategoryBar = {
  id: string;
  name: string;
  value: number;
  life_domain: string;
  necessity: string;
  pct: number;
  rollupIds?: string[];
  rollupNames?: string[];
};

/** Drill into Categorize with the same filters as the chart bar. */
function transactionsDrilldownUrl(
  tf: TimeframeValue,
  bar: CategoryBar,
): string | null {
  if (!bar.id || bar.value <= 0) return null;
  const params = new URLSearchParams();
  if (tf.from) params.set("date_from", tf.from);
  if (tf.to) params.set("date_to", tf.to);
  params.set("hide_transfers", "1");
  params.set("expenses_only", "1");
  if (bar.id === "other_rollup") {
    const ids = bar.rollupIds?.filter(Boolean) ?? [];
    if (!ids.length) return null;
    params.set("category_ids", ids.join(","));
  } else {
    params.set("category_id", bar.id);
  }
  return `/expenses/categorize?${params.toString()}`;
}

const NECESSITY_COLORS: Record<string, string> = {
  Fixed: "#38bdf8",
  VariableNecessity: "#a78bfa",
  Discretionary: "#fbbf24",
};

const NECESSITY_LABEL: Record<string, string> = {
  Fixed: "Fixed",
  VariableNecessity: "Variable",
  Discretionary: "Discretionary",
};

const CATEGORY_TOP_N = 25;

function deltaText(pct: number | null | undefined, invertGood = false): { text: string; cls: string } {
  if (pct === null || pct === undefined) return { text: "vs prior: —", cls: "text-ink-faint" };
  const good = invertGood ? pct < 0 : pct > 0;
  const bad = invertGood ? pct > 0 : pct < 0;
  const cls = good ? "text-ok" : bad ? "text-danger" : "text-ink-muted";
  const sign = pct >= 0 ? "+" : "";
  return { text: `vs prior: ${sign}${pct.toFixed(0)}%`, cls };
}

function HoverList({
  title,
  rows,
}: {
  title: string;
  rows: Array<{ label: string; value: string }>;
}) {
  if (!rows.length) return <div className="text-xs text-ink-faint">{title}: none</div>;
  return (
    <div className="mb-2">
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
        {title}
      </div>
      <ul className="space-y-0.5">
        {rows.map((r) => (
          <li key={r.label} className="flex justify-between gap-3 text-xs">
            <span className="truncate text-ink-muted">{r.label}</span>
            <span className="shrink-0 font-medium">{r.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Expense Tracking — Spending. */
export function NewEtSpendingPage() {
  const navigate = useNavigate();
  const [tf, setTf] = useState<TimeframeValue>(() => loadStoredSpendingTimeframe());
  const [dash, setDash] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const onTimeframeChange = (next: TimeframeValue) => {
    setTf(next);
    saveStoredSpendingTimeframe(next);
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const dsum = await api.dashboard({
          date_from: tf.from ?? undefined,
          date_to: tf.to,
          period_key: tf.key,
        });
        if (!cancelled) setDash(dsum);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tf]);

  if (loading && !dash) return <PageLoader label="Loading spending…" />;
  if (error && !dash) {
    return (
      <EmptyState
        title="Couldn’t load spending"
        description={error}
        action={
          <button type="button" className="btn-primary" onClick={() => window.location.reload()}>
            Retry
          </button>
        }
      />
    );
  }
  if (!dash) return null;

  const cf = dash.cashflow;
  const income = d(cf.income_usd ?? cf.income);
  const expense = d(cf.expense_usd ?? cf.expense);
  const net = d(cf.net_usd ?? cf.net);
  const comp = dash.comparison;
  const pace = dash.pace;
  const spending = dash.spending;

  const categoryRows = spending?.by_category || [];
  const categoryMapped: CategoryBar[] = categoryRows.map((e) => ({
    id: e.id,
    name: e.name,
    value: d(e.amount_usd),
    life_domain: e.life_domain,
    necessity: e.necessity,
    pct: e.pct_of_spend,
  }));
  let categoryData = categoryMapped;
  if (categoryMapped.length > CATEGORY_TOP_N) {
    const top = categoryMapped.slice(0, CATEGORY_TOP_N);
    const rest = categoryMapped.slice(CATEGORY_TOP_N);
    const otherVal = rest.reduce((s, r) => s + r.value, 0);
    const otherPct = rest.reduce((s, r) => s + r.pct, 0);
    categoryData = [
      ...top,
      {
        id: "other_rollup",
        name: `Smaller categories (${rest.length})`,
        value: otherVal,
        life_domain: "Mixed",
        necessity: "Discretionary",
        pct: Math.round(otherPct * 10) / 10,
        rollupIds: rest.map((r) => r.id),
        rollupNames: rest.map((r) => r.name),
      },
    ];
  }
  const chartHeight = Math.max(280, categoryData.length * 32 + 40);

  function openCategoryTransactions(bar: CategoryBar) {
    const url = transactionsDrilldownUrl(tf, bar);
    if (url) navigate(url);
  }

  const uncatPct = spending?.uncategorized_pct ?? 0;
  const netDelta = deltaText(comp?.net_change_pct ?? null);
  const incomeDelta = deltaText(comp?.income_change_pct ?? null);
  const expenseDelta = deltaText(comp?.expense_change_pct ?? null, true);
  const pacePct = pace?.pace_pct;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Spending</h1>
          <p className="text-sm text-ink-muted">
            {tf.label} · cash income &amp; expenses · USD primary · hover for CZK
            {loading && <span className="ml-2 text-ink-faint">Updating…</span>}
          </p>
        </div>
      </div>

      <TimeframePicker value={tf} onChange={onTimeframeChange} />

      {uncatPct >= 70 && (
        <div className="rounded-xl border border-warn/30 bg-warn/10 px-4 py-3 text-sm text-warn">
          Most spend is uncategorized ({uncatPct.toFixed(0)}%). Category bars will improve after
          categorization.{" "}
          <Link to="/expenses/categorize" className="font-semibold underline">
            Open Categorize
          </Link>
        </div>
      )}

      <div className="card p-5">
        <div className="mb-1 flex w-full flex-wrap items-start gap-2 sm:gap-3">
          <div className="min-w-0 max-w-full flex-1 basis-[12rem]">
            <h2 className="text-sm font-semibold">Spending by category</h2>
            <p className="text-xs text-ink-faint">
              USD · {tf.label} · excludes internal transfers · bars by necessity
              · top {CATEGORY_TOP_N} · click a bar for transactions
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
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
          </div>
          <div className="ml-auto flex shrink-0 flex-wrap items-start justify-end gap-2 sm:gap-3">
            <CompactCashMetric
              label="Net"
              tone={net >= 0 ? "ok" : "danger"}
              delta={netDelta}
              hover={
                <>
                  <HoverList
                    title="Summary"
                    rows={[
                      { label: "Income", value: formatUsd(income) },
                      { label: "Expenses", value: formatUsd(expense) },
                      { label: "Net", value: formatUsd(net) },
                      {
                        label: "CZK net",
                        value: `${d(cf.net_czk).toLocaleString("cs-CZ")} Kč`,
                      },
                    ]}
                  />
                  {comp && (
                    <div className="text-xs text-ink-faint">
                      Prior {comp.prior_from} → {comp.prior_to}: {formatUsd(comp.net_usd)}
                    </div>
                  )}
                </>
              }
            >
              <Money
                amount={net}
                currency="USD"
                amountCzk={cf.net_czk}
                secondaryMode="hover"
                size="md"
                signed
              />
            </CompactCashMetric>
            <CompactCashMetric
              label="Income"
              tone="ok"
              delta={incomeDelta}
              hover={
                <HoverList
                  title="Top sources"
                  rows={(cf.top_income || []).map((t) => ({
                    label: t.label,
                    value: formatUsd(t.amount_usd),
                  }))}
                />
              }
            >
              <Money
                amount={income}
                currency="USD"
                amountCzk={cf.income_czk}
                secondaryMode="hover"
                size="md"
              />
            </CompactCashMetric>
            <CompactCashMetric
              label="Expenses"
              tone="danger"
              delta={expenseDelta}
              hover={
                <>
                  <HoverList
                    title="Top merchants"
                    rows={(cf.top_expense_merchants || []).map((t) => ({
                      label: t.label,
                      value: formatUsd(t.amount_usd),
                    }))}
                  />
                  <div className="text-xs text-ink-faint">
                    30d spend {formatUsd(pace?.spend_30d_usd ?? "0")}
                    {pacePct != null && (
                      <>
                        {" "}
                        · pace{" "}
                        <span
                          className={
                            pacePct > 10
                              ? "text-warn"
                              : pacePct < -10
                                ? "text-ok"
                                : ""
                          }
                        >
                          {pacePct >= 0 ? "+" : ""}
                          {pacePct.toFixed(0)}%
                        </span>
                      </>
                    )}
                  </div>
                </>
              }
            >
              <Money
                amount={expense}
                currency="USD"
                amountCzk={cf.expense_czk}
                secondaryMode="hover"
                size="md"
              />
            </CompactCashMetric>
          </div>
        </div>
        {categoryData.length === 0 ? (
          <EmptyState
            title="No expense data"
            description="Upload statements or pick another range."
          />
        ) : (
          <div style={{ height: chartHeight }} className="mt-4 w-full">
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
                      const list = names.length
                        ? ` · ${names.join(", ")}${more}`
                        : "";
                      return [
                        `${formatUsd(v)} · ${p.pct}% · outside top ${CATEGORY_TOP_N} by spend (not Uncategorized)${list}`,
                        "Spend",
                      ];
                    }
                    const nec = p ? NECESSITY_LABEL[p.necessity] || p.necessity : "";
                    const domain = p?.life_domain || "";
                    const pct = p?.pct != null ? `${p.pct}%` : "";
                    return [
                      `${formatUsd(v)} · ${pct} · ${domain} · ${nec}`,
                      "Spend",
                    ];
                  }}
                />
                <Bar
                  dataKey="value"
                  radius={[0, 6, 6, 0]}
                  barSize={18}
                  cursor="pointer"
                  onClick={(state) => {
                    const payload = (state as { payload?: CategoryBar })?.payload;
                    if (payload) openCategoryTransactions(payload);
                  }}
                >
                  {categoryData.map((e) => (
                    <Cell
                      key={e.id}
                      fill={NECESSITY_COLORS[e.necessity] || "#64748b"}
                      cursor="pointer"
                      onClick={() => openCategoryTransactions(e)}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-3 text-xs">
        <Link to="/expenses/categorize" className="font-medium text-brand hover:underline">
          Categorize transactions →
        </Link>
        <Link to="/" className="text-ink-muted hover:text-ink hover:underline">
          Executive dashboard
        </Link>
      </div>
    </div>
  );
}

function CompactCashMetric({
  label,
  children,
  tone,
  delta,
  hover,
}: {
  label: string;
  children: React.ReactNode;
  tone: "ok" | "danger" | "brand";
  delta?: { text: string; cls: string };
  hover?: React.ReactNode;
}) {
  const toneText =
    tone === "ok" ? "text-ok" : tone === "danger" ? "text-danger" : "text-brand";

  const body = (
    <div className="min-w-[5.5rem] text-right">
      <div className="text-[11px] uppercase tracking-wide text-ink-faint">{label}</div>
      <div className={cn("font-semibold tabular-nums tracking-tight", toneText)}>
        {children}
      </div>
      {delta && (
        <div className={cn("text-[11px] font-medium tabular-nums", delta.cls)}>
          {delta.text}
        </div>
      )}
    </div>
  );

  if (!hover) return body;
  return (
    <HoverPanel content={hover} className="shrink-0">
      {body}
    </HoverPanel>
  );
}
