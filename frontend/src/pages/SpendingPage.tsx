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
import { TrendingDown, TrendingUp, Wallet } from "lucide-react";
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

type CategoryBar = {
  id: string;
  name: string;
  value: number;
  life_domain: string;
  necessity: string;
  pct: number;
  /** For Other rollup: underlying category ids */
  rollupIds?: string[];
};

/** Build /expenses/categorize query matching dashboard category-chart filters. */
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

const CATEGORY_TOP_N = 20;

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

/** Full cash analysis — timeframe KPIs, pace, category chart (moved from home Dashboard). */
export function SpendingPage() {
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
      // Keep showing previous numbers while refreshing (no full-page blank)
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
        name: `Other (${rest.length})`,
        value: otherVal,
        life_domain: "Other",
        necessity: "Discretionary",
        pct: Math.round(otherPct * 10) / 10,
        rollupIds: rest.map((r) => r.id),
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
  const pacePctLiving = pace?.pace_pct_living;
  const invShare30 = pace?.investments_share_30d_pct;
  const invShare6m = pace?.investments_share_6m_avg_pct;

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

      {/* 1) Timeframe / month selector */}
      <TimeframePicker value={tf} onChange={onTimeframeChange} />

      {/* 2) Spending by category */}
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
        <div className="mb-1 flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold">Spending by category</h2>
            <p className="text-xs text-ink-faint">
              USD · {tf.label} · excludes internal transfers · bars colored by necessity
              · click a bar to open matching transactions
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
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
                  width={120}
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

      {/* 3) Cash KPI cards */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <Kpi
          label="Net cash flow"
          icon={net >= 0 ? TrendingUp : TrendingDown}
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
                  { label: "CZK net", value: `${d(cf.net_czk).toLocaleString("cs-CZ")} Kč` },
                ]}
              />
              <HoverList
                title="By currency (native)"
                rows={(cf.by_currency || []).map((r) => ({
                  label: r.currency,
                  value: `${r.net} ${r.currency}`,
                }))}
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
            size="lg"
            signed
          />
        </Kpi>

        <Kpi
          label="Income"
          icon={Wallet}
          tone="ok"
          delta={incomeDelta}
          hover={
            <>
              <HoverList
                title="Top sources"
                rows={(cf.top_income || []).map((t) => ({
                  label: t.label,
                  value: formatUsd(t.amount_usd),
                }))}
              />
              <HoverList
                title="By currency"
                rows={(cf.by_currency || [])
                  .filter((r) => d(r.income) > 0)
                  .map((r) => ({ label: r.currency, value: `${r.income} ${r.currency}` }))}
              />
              <div className="text-xs text-ink-faint">
                CZK ≈ {d(cf.income_czk).toLocaleString("cs-CZ")} Kč · {cf.transaction_count} txs
              </div>
            </>
          }
        >
          <Money
            amount={income}
            currency="USD"
            amountCzk={cf.income_czk}
            secondaryMode="hover"
            size="lg"
          />
        </Kpi>

        <Kpi
          label="Expenses"
          icon={TrendingDown}
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
              <HoverList
                title="Top domains"
                rows={(cf.top_expense_domains || []).map((t) => ({
                  label: t.label,
                  value: formatUsd(t.amount_usd),
                }))}
              />
              <div className="text-xs text-ink-faint">
                CZK ≈ {d(cf.expense_czk).toLocaleString("cs-CZ")} Kč
                {cf.unconverted_count > 0 && ` · ${cf.unconverted_count} unconverted`}
              </div>
            </>
          }
        >
          <Money
            amount={expense}
            currency="USD"
            amountCzk={cf.expense_czk}
            secondaryMode="hover"
            size="lg"
          />
        </Kpi>
      </div>

      {/* 4) Rolling 30-day pace strip */}
      <div className="card grid gap-4 p-5 sm:grid-cols-3">
        <div>
          <div className="label">Rolling 30-day spend</div>
          <Money
            amount={pace?.spend_30d_usd}
            currency="USD"
            secondaryMode="hover"
            size="lg"
          />
          <div className="mt-1 space-y-0.5 text-[11px] text-ink-faint">
            <div>
              Investments:{" "}
              <span className="font-medium text-ink-muted">
                {formatUsd(pace?.spend_30d_investments_usd ?? "0")}
              </span>
              {invShare30 != null && (
                <span className="text-ink-faint"> ({invShare30.toFixed(0)}%)</span>
              )}
            </div>
            <div>
              Living:{" "}
              <span className="font-medium text-ink-muted">
                {formatUsd(pace?.spend_30d_living_usd ?? "0")}
              </span>
            </div>
          </div>
        </div>
        <div>
          <div className="label">6‑mo avg monthly spend</div>
          <Money
            amount={pace?.avg_monthly_6m_usd}
            currency="USD"
            secondaryMode="hover"
            size="lg"
          />
          <div className="mt-0.5 text-[11px] text-ink-faint">Last 180 days ÷ 6</div>
          <div className="mt-1 space-y-0.5 text-[11px] text-ink-faint">
            <div>
              Investments:{" "}
              <span className="font-medium text-ink-muted">
                {formatUsd(pace?.avg_monthly_6m_investments_usd ?? "0")}/mo
              </span>
              {invShare6m != null && (
                <span className="text-ink-faint"> ({invShare6m.toFixed(0)}%)</span>
              )}
            </div>
            <div>
              Living:{" "}
              <span className="font-medium text-ink-muted">
                {formatUsd(pace?.avg_monthly_6m_living_usd ?? "0")}/mo
              </span>
            </div>
          </div>
        </div>
        <div>
          <div className="label">30d vs monthly avg</div>
          <div
            className={`text-2xl font-semibold ${
              pacePct != null && pacePct > 10
                ? "text-warn"
                : pacePct != null && pacePct < -10
                  ? "text-ok"
                  : "text-ink"
            }`}
          >
            {pacePct == null
              ? "—"
              : `${pacePct >= 0 ? "+" : ""}${pacePct.toFixed(0)}%`}
          </div>
          <div className="mt-0.5 text-[11px] text-ink-faint">Total spend pace</div>
          <div className="mt-1 text-[11px] text-ink-muted">
            Living only:{" "}
            <span
              className={
                pacePctLiving != null && pacePctLiving > 10
                  ? "text-warn"
                  : pacePctLiving != null && pacePctLiving < -10
                    ? "text-ok"
                    : "text-ink"
              }
            >
              {pacePctLiving == null
                ? "—"
                : `${pacePctLiving >= 0 ? "+" : ""}${pacePctLiving.toFixed(0)}%`}
            </span>
          </div>
        </div>
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

function Kpi({
  label,
  children,
  icon: Icon,
  tone,
  delta,
  hover,
}: {
  label: string;
  children: React.ReactNode;
  icon: React.ComponentType<{ className?: string }>;
  tone: "ok" | "danger" | "brand";
  delta?: { text: string; cls: string };
  hover?: React.ReactNode;
}) {
  const toneCls =
    tone === "ok"
      ? "text-ok bg-ok/10"
      : tone === "danger"
        ? "text-danger bg-danger/10"
        : "text-brand bg-brand/10";

  const body = (
    <div className="card p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="label mb-0">{label}</span>
        <span className={`rounded-lg p-1.5 ${toneCls}`}>
          <Icon className="h-4 w-4" />
        </span>
      </div>
      {children}
      {delta && <div className={`mt-1 text-xs ${delta.cls}`}>{delta.text}</div>}
    </div>
  );

  if (!hover) return body;
  return (
    <HoverPanel content={hover} className="h-full">
      {body}
    </HoverPanel>
  );
}
