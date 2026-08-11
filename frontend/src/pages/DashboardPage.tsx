import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  TrendingDown,
  TrendingUp,
  LineChart,
  Wallet,
  ArrowRight,
  AlertTriangle,
  ShieldAlert,
  Info,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { api } from "../api/client";
import type { AlertItem, DashboardSummary, PortfolioSnapshot } from "../api/types";
import { Money } from "../components/Money";
import { HoverPanel } from "../components/HoverPanel";
import { EmptyState, PageLoader } from "../components/Spinner";
import { DrawMetricsCard } from "../components/DrawMetricsCard";
import { d, formatUsd } from "../lib/money";
import {
  canGoNextMonth,
  loadStoredSpendingTimeframe,
  saveStoredSpendingTimeframe,
  shiftCalendarMonth,
  type TimeframeValue,
} from "../lib/timeframe";
import { cn } from "../lib/cn";

const GRADE_STYLE: Record<string, string> = {
  A: "bg-ok/20 text-ok ring-ok/40",
  B: "bg-brand/20 text-brand ring-brand/40",
  C: "bg-white/10 text-ink ring-white/20",
  D: "bg-warn/20 text-warn ring-warn/40",
  F: "bg-danger/20 text-danger ring-danger/40",
  "N/A": "bg-white/5 text-ink-faint ring-white/10",
  "—": "bg-white/5 text-ink-faint ring-white/10",
};

function deltaText(
  pct: number | null | undefined,
  invertGood = false,
): { text: string; cls: string } {
  if (pct === null || pct === undefined)
    return { text: "vs prior: —", cls: "text-ink-faint" };
  const good = invertGood ? pct < 0 : pct > 0;
  const bad = invertGood ? pct > 0 : pct < 0;
  const cls = good ? "text-ok" : bad ? "text-danger" : "text-ink-muted";
  const sign = pct >= 0 ? "+" : "";
  return { text: `vs prior: ${sign}${pct.toFixed(0)}%`, cls };
}

/**
 * Home = flashy executive snapshot: wealth + cash highlights.
 * Full spending analysis lives on /expenses/spending.
 */
export function DashboardPage() {
  const [cashTf, setCashTf] = useState<TimeframeValue>(() => loadStoredSpendingTimeframe());
  const [dash, setDash] = useState<DashboardSummary | null>(null);
  const [snap, setSnap] = useState<PortfolioSnapshot | null>(null);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [wealthRefreshing, setWealthRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** H12: ignore stale responses when cashTf / loads race */
  const loadGen = useRef(0);

  const load = useCallback(
    async (opts?: { quiet?: boolean; pricesOnly?: boolean }) => {
      const quiet = opts?.quiet ?? false;
      const pricesOnly = opts?.pricesOnly ?? false;
      // pricesOnly must not invalidate an in-flight full load; full loads bump gen
      const gen = pricesOnly ? loadGen.current : ++loadGen.current;
      if (!quiet && !pricesOnly) setLoading(true);
      if (pricesOnly) setWealthRefreshing(true);
      if (!pricesOnly) setError(null);
      try {
        if (pricesOnly) {
          const isnap = await api.investmentsSnapshot();
          if (gen !== loadGen.current) return;
          setSnap(isnap);
          return;
        }
        const [dsum, isnap, al] = await Promise.all([
          api.dashboard({
            date_from: cashTf.from ?? undefined,
            date_to: cashTf.to,
            period_key: cashTf.key,
          }),
          api.investmentsSnapshot(),
          api.alerts().catch(() => ({ items: [] as AlertItem[], warn_count: 0, total: 0 })),
        ]);
        if (gen !== loadGen.current) return;
        setDash(dsum);
        setSnap(isnap);
        setAlerts(al.items || []);
      } catch (e) {
        if (gen !== loadGen.current) return;
        // Keep last good dashboard on quiet/partial failures when data exists
        if (pricesOnly) return;
        setError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        if (gen !== loadGen.current) return;
        if (!quiet && !pricesOnly) setLoading(false);
        if (pricesOnly) setWealthRefreshing(false);
      }
    },
    [cashTf.from, cashTf.to, cashTf.key],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // Update prices button (Layout) → refresh wealth KPIs without full remount
  useEffect(() => {
    const onPrices = () => {
      void load({ quiet: true, pricesOnly: true });
    };
    window.addEventListener("prices-updated", onPrices);
    return () => window.removeEventListener("prices-updated", onPrices);
  }, [load]);

  function shiftCashMonth(delta: number) {
    const next = shiftCalendarMonth(cashTf, delta);
    setCashTf(next);
    saveStoredSpendingTimeframe(next);
  }

  if (loading && !dash) return <PageLoader label="Loading executive snapshot…" />;
  if (error && !dash) {
    return (
      <EmptyState
        title="Couldn’t load dashboard"
        description={error}
        action={
          <button type="button" className="btn-primary" onClick={() => void load()}>
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
  const uncatPct = dash.spending?.uncategorized_pct ?? 0;
  const pacePct = pace?.pace_pct;
  const pacePctLiving = pace?.pace_pct_living;

  const health = snap?.health;
  const grade = health?.grade ?? "—";
  const conc = health?.concentration;
  const focus = (health?.issues || [])
    .filter((i) => i.severity === "high" || i.severity === "medium")
    .slice(0, 3);

  const mv = snap?.total_market_value_usd;
  const unreal = snap?.unrealized_usd;
  const unrealPct = snap?.unrealized_pct;
  const cost = snap?.total_cost_basis_usd ?? "0";
  const realized = snap?.realized_lifetime_usd ?? "0";
  const draw = snap?.living_draw_12m;
  const runway = snap?.tax_runway;
  const topHoldings = (snap?.positions || [])
    .slice()
    .sort((a, b) => {
      const av = a.market_value != null ? d(a.market_value) : d(a.cost_basis_usd);
      const bv = b.market_value != null ? d(b.market_value) : d(b.cost_basis_usd);
      return bv - av;
    })
    .slice(0, 5);

  const alertStrip = alerts
    .filter((a) => a.level === "danger" || a.level === "warn")
    .slice(0, 3);

  const asOf = snap?.as_of || new Date().toISOString().slice(0, 10);
  const priceNote = snap?.price_status?.note;

  return (
    <div className="space-y-6">
      {/* Hero */}
      <section
        className="relative overflow-hidden rounded-2xl border p-5 sm:p-7"
        style={{
          background:
            "linear-gradient(135deg, rgba(59,130,246,0.16), rgba(16,185,129,0.10) 45%, rgba(15,23,42,0.85))",
          borderColor: "rgba(52,211,153,0.35)",
          boxShadow: "0 20px 50px rgba(0,0,0,0.35)",
        }}
      >
        <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-brand/10 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-20 left-1/3 h-40 w-40 rounded-full bg-ok/10 blur-3xl" />

        <div className="relative">
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
            Executive snapshot · {asOf}
            <span className="ml-2 text-brand">Statements · CNB FX</span>
          </div>

          <div className="mt-3 flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
            <div className="flex min-w-0 flex-1 gap-4">
              <div
                className={cn(
                  "flex h-20 w-20 shrink-0 flex-col items-center justify-center rounded-2xl ring-2",
                  GRADE_STYLE[grade] || GRADE_STYLE["—"],
                )}
              >
                <span className="text-3xl font-black leading-none">{grade}</span>
                <span className="mt-0.5 text-[11px] font-semibold opacity-80">
                  {health?.score ?? "—"}/100
                </span>
              </div>
              <div className="min-w-0">
                <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
                  Gauntlet Finance
                </h1>
                <p className="mt-1 max-w-xl text-sm leading-relaxed text-ink-muted">
                  {health?.summary ||
                    "Your combined wealth and cash pulse — investments and spending in one view."}
                </p>
                {conc && (
                  <p className="mt-2 text-xs text-ink-faint">
                    {conc.largest_position_line}
                    {" · "}
                    Top3 {conc.top3_weight_pct?.toFixed?.(0) ?? conc.top3_weight_pct}%
                    {" · "}
                    Crypto {conc.crypto_weight_pct?.toFixed?.(0) ?? conc.crypto_weight_pct}%
                    {" · "}
                    Tax-free basis{" "}
                    {conc.tax_free_basis_pct?.toFixed?.(0) ?? conc.tax_free_basis_pct}%
                  </p>
                )}
                {(snap?.fees || snap?.staking) && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {snap.fees && (
                      <span className="pill-warn">
                        Fees {formatUsd(snap.fees.total_fees_usd)}
                      </span>
                    )}
                    {snap.fees && (
                      <span className="pill-info">
                        Deposits {formatUsd(snap.fees.deposits_usd)}
                      </span>
                    )}
                    {snap.staking && (
                      <span className="pill-good">
                        Staking ≈ {formatUsd(snap.staking.mark_usd_total)}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>

            {focus.length > 0 && (
              <div className="w-full max-w-md shrink-0 rounded-xl border border-white/10 bg-black/20 p-3 backdrop-blur-sm lg:w-80">
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
                  Focus
                </div>
                <ul className="space-y-2">
                  {focus.map((iss) => (
                    <li key={iss.title} className="text-xs">
                      <span
                        className={cn(
                          "mr-1.5 inline-block rounded px-1 py-0.5 text-[10px] font-bold uppercase",
                          iss.severity === "high" && "bg-danger/20 text-danger",
                          iss.severity === "medium" && "bg-warn/20 text-warn",
                        )}
                      >
                        {iss.severity}
                      </span>
                      <span className="font-medium text-ink">{iss.title}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {priceNote && (
            <p className="mt-4 text-[11px] text-ink-faint">{priceNote}</p>
          )}
        </div>
      </section>

      {/* Wealth | Cash twin grids */}
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold tracking-wide text-ok">Wealth</h2>
              <p className="text-[11px] text-ink-faint">
                Portfolio as of {asOf}
                {wealthRefreshing && (
                  <span className="ml-2 text-brand">Refreshing prices…</span>
                )}
              </p>
            </div>
            <Link
              to="/investments"
              className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
            >
              Holdings <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <ExecStat label="Market value" icon={LineChart} tone="brand">
              {mv ? (
                <Money amount={mv} currency="USD" secondaryMode="hover" size="lg" />
              ) : (
                <span className="text-lg text-ink-faint">Update prices</span>
              )}
            </ExecStat>
            <ExecStat label="Unrealized" icon={TrendingUp} tone="ok">
              {unreal != null ? (
                <>
                  <Money
                    amount={unreal}
                    currency="USD"
                    secondaryMode="hover"
                    size="lg"
                    signed
                  />
                  {unrealPct != null && (
                    <div
                      className={cn(
                        "text-xs font-medium",
                        unrealPct >= 0 ? "text-ok" : "text-danger",
                      )}
                    >
                      {unrealPct >= 0 ? "+" : ""}
                      {unrealPct.toFixed(1)}% vs cost
                    </div>
                  )}
                </>
              ) : (
                <span className="text-lg text-ink-faint">—</span>
              )}
            </ExecStat>
            <ExecStat label="Open cost" icon={Wallet} tone="brand">
              <Money amount={cost} currency="USD" secondaryMode="hover" size="lg" />
            </ExecStat>
            <ExecStat label="12m living draw" icon={TrendingDown} tone="warn">
              {draw ? (
                <>
                  <Money
                    amount={draw.draw_usd}
                    currency="USD"
                    secondaryMode="hover"
                    size="lg"
                    signed
                  />
                  <div className="text-[11px] text-ink-faint">
                    Sold {formatUsd(draw.sold_usd)} · rein {formatUsd(draw.bought_usd)}
                  </div>
                </>
              ) : (
                <span className="text-lg text-ink-faint">—</span>
              )}
            </ExecStat>
            <ExecStat label="Realized (lifetime)" icon={TrendingUp} tone="ok">
              <Money
                amount={realized}
                currency="USD"
                secondaryMode="hover"
                size="lg"
                signed
              />
              {snap?.realized_cost_basis_usd != null &&
                d(snap.realized_cost_basis_usd) > 0 && (
                  <div className="text-[11px] text-ink-faint">
                    on {formatUsd(snap.realized_cost_basis_usd)} sold
                    {snap.realized_roi_pct != null && (
                      <>
                        {" "}
                        · {snap.realized_roi_pct >= 0 ? "+" : ""}
                        {snap.realized_roi_pct.toFixed(0)}% total
                      </>
                    )}
                  </div>
                )}
              {snap?.realized_annualized_pct != null ? (
                <div
                  className={cn(
                    "text-[11px] tabular-nums",
                    snap.realized_annualized_pct >= 0 ? "text-ok" : "text-danger",
                  )}
                  title="CAGR of realized sells over cost-weighted holding years"
                >
                  {snap.realized_annualized_pct >= 0 ? "+" : ""}
                  {snap.realized_annualized_pct.toFixed(1)}% ann.
                  {snap.realized_holding_years != null && (
                    <span className="text-ink-faint">
                      {" "}
                      · {snap.realized_holding_years.toFixed(1)}y wtd
                    </span>
                  )}
                </div>
              ) : snap?.realized_holding_years != null &&
                snap.realized_holding_years * 365.25 < 90 ? (
                <div className="text-[11px] text-ink-faint">
                  Ann. n/a (&lt;90d wtd hold)
                </div>
              ) : null}
            </ExecStat>
            <ExecStat label="Tax-free now" icon={ShieldAlert} tone="ok">
              <Money
                amount={runway?.available_usd ?? snap?.tax_free_now_usd ?? "0"}
                currency="USD"
                secondaryMode="hover"
                size="lg"
              />
              {runway && (
                <div className="text-[11px] text-ink-faint">
                  Locked {formatUsd(runway.locked_usd)}
                </div>
              )}
            </ExecStat>
          </div>
        </section>

        <section className="card p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold tracking-wide text-brand">Cash</h2>
              <div className="mt-1 flex items-center gap-0.5 rounded-lg border border-white/10 bg-white/[0.03] p-0.5">
                <button
                  type="button"
                  aria-label="Previous month"
                  className="rounded-md p-1 text-ink-muted transition hover:bg-white/10 hover:text-ink"
                  onClick={() => shiftCashMonth(-1)}
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="min-w-[7.5rem] px-1 text-center text-xs font-semibold tabular-nums text-ink">
                  {cashTf.label}
                </span>
                <button
                  type="button"
                  aria-label="Next month"
                  disabled={!canGoNextMonth(cashTf)}
                  className={cn(
                    "rounded-md p-1 transition",
                    canGoNextMonth(cashTf)
                      ? "text-ink-muted hover:bg-white/10 hover:text-ink"
                      : "cursor-not-allowed text-ink-faint opacity-40",
                  )}
                  onClick={() => shiftCashMonth(1)}
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
            <Link
              to="/expenses/spending"
              className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
            >
              Full spending <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <ExecStat
              label="Net cashflow"
              icon={net >= 0 ? TrendingUp : TrendingDown}
              tone={net >= 0 ? "ok" : "danger"}
            >
              <Money
                amount={net}
                currency="USD"
                amountCzk={cf.net_czk}
                secondaryMode="hover"
                size="lg"
                signed
              />
              <div className={cn("text-xs", deltaText(comp?.net_change_pct).cls)}>
                {deltaText(comp?.net_change_pct).text}
              </div>
            </ExecStat>
            <ExecStat label="Income" icon={Wallet} tone="ok">
              <Money
                amount={income}
                currency="USD"
                amountCzk={cf.income_czk}
                secondaryMode="hover"
                size="lg"
              />
              <div className={cn("text-xs", deltaText(comp?.income_change_pct).cls)}>
                {deltaText(comp?.income_change_pct).text}
              </div>
            </ExecStat>
            <ExecStat label="Expenses" icon={TrendingDown} tone="danger">
              <Money
                amount={expense}
                currency="USD"
                amountCzk={cf.expense_czk}
                secondaryMode="hover"
                size="lg"
              />
              <div
                className={cn("text-xs", deltaText(comp?.expense_change_pct, true).cls)}
              >
                {deltaText(comp?.expense_change_pct, true).text}
              </div>
            </ExecStat>
            <ExecStat label="Spend pace (30d)" icon={TrendingDown} tone="warn">
              <div
                className={cn(
                  "text-2xl font-semibold",
                  pacePct != null && pacePct > 10
                    ? "text-warn"
                    : pacePct != null && pacePct < -10
                      ? "text-ok"
                      : "text-ink",
                )}
              >
                {pacePct == null
                  ? "—"
                  : `${pacePct >= 0 ? "+" : ""}${pacePct.toFixed(0)}%`}
              </div>
              <div className="text-[11px] text-ink-faint">
                vs 6‑mo monthly avg
                {pacePctLiving != null && (
                  <>
                    {" · "}
                    living{" "}
                    {pacePctLiving >= 0 ? "+" : ""}
                    {pacePctLiving.toFixed(0)}%
                  </>
                )}
              </div>
            </ExecStat>
          </div>
          {uncatPct >= 20 && (
            <div className="mt-3 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
              {uncatPct.toFixed(0)}% of period spend uncategorized / Other.{" "}
              <Link to="/expenses/categorize" className="font-semibold underline">
                Categorize
              </Link>
            </div>
          )}
        </section>
      </div>

      {snap && snap.ticker_count > 0 && (
        <DrawMetricsCard compact />
      )}

      {/* Tax runway */}
      {runway && runway.buckets?.length > 0 && (
        <section className="card p-5">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold">Tax-free runway</h2>
            <span className="pill-good">Available {formatUsd(runway.available_usd)}</span>
            <span className="pill-warn">Locked {formatUsd(runway.locked_usd)}</span>
            <Link
              to="/investments"
              className="ml-auto text-xs font-medium text-brand hover:underline"
            >
              Holdings detail →
            </Link>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {runway.buckets.map((b, i) => (
              <HoverPanel
                key={b.key}
                content={
                  b.tickers.length === 0 ? (
                    <div className="text-xs text-ink-faint">No lots</div>
                  ) : (
                    <ul className="space-y-1">
                      {b.tickers.slice(0, 12).map((t) => (
                        <li
                          key={t.ticker}
                          className="flex justify-between gap-3 text-xs"
                        >
                          <span>{t.ticker}</span>
                          <span className="font-medium">{formatUsd(t.amount_usd)}</span>
                        </li>
                      ))}
                    </ul>
                  )
                }
              >
                <div
                  className={cn(
                    "rounded-xl border p-3 transition hover:border-brand/40",
                    i === 0 ? "border-ok/35 bg-ok/10" : "border-white/10 bg-black/15",
                  )}
                >
                  <div className="label mb-1">{b.label}</div>
                  <Money
                    amount={b.amount_usd}
                    currency="USD"
                    secondaryMode="none"
                    size="lg"
                  />
                </div>
              </HoverPanel>
            ))}
          </div>
        </section>
      )}

      {/* Top holdings */}
      {topHoldings.length > 0 && (
        <section className="card p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Top holdings</h2>
            <Link to="/investments" className="text-xs text-brand hover:underline">
              Verify →
            </Link>
          </div>
          <div className="flex flex-wrap gap-2">
            {topHoldings.map((p) => {
              const val =
                p.market_value != null ? d(p.market_value) : d(p.cost_basis_usd);
              const u = p.unrealized_usd != null ? d(p.unrealized_usd) : null;
              return (
                <div
                  key={p.ticker}
                  className="min-w-[7.5rem] rounded-xl border border-slate-500/25 bg-black/20 px-3 py-2"
                >
                  <div className="text-sm font-bold">{p.ticker}</div>
                  <div className="text-xs text-ink-muted">{formatUsd(val)}</div>
                  {u != null && (
                    <div
                      className={cn(
                        "text-[11px] font-medium",
                        u >= 0 ? "text-ok" : "text-danger",
                      )}
                    >
                      {u >= 0 ? "+" : ""}
                      {formatUsd(u)}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Alerts strip */}
      {alertStrip.length > 0 && (
        <section className="card p-4">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Needs attention</h2>
            <Link
              to="/expenses/alerts"
              className="text-xs font-medium text-brand hover:underline"
            >
              All alerts →
            </Link>
          </div>
          <ul className="space-y-2">
            {alertStrip.map((a) => (
              <li key={a.id}>
                <Link
                  to={a.href || "/expenses/alerts"}
                  className={cn(
                    "flex gap-2 rounded-lg border px-3 py-2 text-sm transition hover:border-brand/40",
                    a.level === "danger"
                      ? "border-danger/30 bg-danger/5"
                      : "border-warn/30 bg-warn/5",
                  )}
                >
                  {a.level === "danger" ? (
                    <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
                  ) : a.level === "warn" ? (
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
                  ) : (
                    <Info className="mt-0.5 h-4 w-4 shrink-0 text-ink-muted" />
                  )}
                  <div className="min-w-0">
                    <div className="font-medium">{a.title}</div>
                    <div className="truncate text-xs text-ink-muted">{a.body}</div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Quick links */}
      <div className="flex flex-wrap gap-2">
        <QuickLink to="/expenses/spending" label="Spending analysis" />
        <QuickLink to="/expenses/categorize" label="Categorize" />
        <QuickLink to="/investments" label="Holdings" />
        <QuickLink to="/investments/analysis" label="Investments analysis" />
        <QuickLink to="/investments/tax" label="Tax report" />
        <QuickLink to="/expenses/alerts" label="Alerts" />
      </div>
    </div>
  );
}

function ExecStat({
  label,
  children,
  icon: Icon,
  tone,
}: {
  label: string;
  children: React.ReactNode;
  icon: React.ComponentType<{ className?: string }>;
  tone: "ok" | "danger" | "brand" | "warn";
}) {
  const toneCls =
    tone === "ok"
      ? "text-ok bg-ok/10"
      : tone === "danger"
        ? "text-danger bg-danger/10"
        : tone === "warn"
          ? "text-warn bg-warn/10"
          : "text-brand bg-brand/10";
  return (
    <div className="rounded-xl border border-white/10 bg-black/20 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="label mb-0">{label}</span>
        <span className={cn("rounded-lg p-1.5", toneCls)}>
          <Icon className="h-3.5 w-3.5" />
        </span>
      </div>
      {children}
    </div>
  );
}

function QuickLink({ to, label }: { to: string; label: string }) {
  return (
    <Link
      to={to}
      className="inline-flex items-center gap-1 rounded-full border border-slate-500/30 bg-surface-raised/80 px-3 py-1.5 text-xs font-medium text-ink-muted transition hover:border-brand/40 hover:text-brand"
    >
      {label}
      <ArrowRight className="h-3 w-3" />
    </Link>
  );
}
