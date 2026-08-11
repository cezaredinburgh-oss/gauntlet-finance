import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { AlertItem, DashboardSummary, PortfolioSnapshot } from "../api/types";
import { EmptyState, PageLoader } from "../components/Spinner";
import {
  canGoNextMonth,
  loadStoredSpendingTimeframe,
  saveStoredSpendingTimeframe,
  shiftCalendarMonth,
  type TimeframeValue,
} from "../lib/timeframe";
import { d } from "../lib/money";
import {
  buildTriageItems,
  CashInsight,
  compactDrawFromSnap,
  HomeDeepLinks,
  HomeHero,
  SignalStrip,
  TriageList,
} from "../features/dashboard";

/**
 * Home = two dials (portfolio MV + month net cash) + triage + secondary signals.
 * Depth lives on Investments / Spending / Analysis — not a second portfolio annex.
 */
export function DashboardPage() {
  const [cashTf, setCashTf] = useState<TimeframeValue>(() => loadStoredSpendingTimeframe());
  const [dash, setDash] = useState<DashboardSummary | null>(null);
  const [snap, setSnap] = useState<PortfolioSnapshot | null>(null);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [wealthRefreshing, setWealthRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadGen = useRef(0);

  const load = useCallback(
    async (opts?: { quiet?: boolean; pricesOnly?: boolean }) => {
      const quiet = opts?.quiet ?? false;
      const pricesOnly = opts?.pricesOnly ?? false;
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

  const triage = useMemo(() => {
    if (!dash) return [];
    return buildTriageItems({
      alerts,
      health: snap?.health,
      uncategorizedPct: dash.spending?.uncategorized_pct ?? 0,
    });
  }, [alerts, snap?.health, dash]);

  const drawStatus = useMemo(() => compactDrawFromSnap(snap), [snap]);

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
  const net = d(cf.net_usd ?? cf.net);
  const comp = dash.comparison;
  const pace = dash.pace;
  const health = snap?.health;
  const grade = health?.grade ?? "—";
  const asOf = snap?.as_of || new Date().toISOString().slice(0, 10);
  const priceNote = snap?.price_status?.note;
  const taxFree =
    snap?.tax_runway?.available_usd ?? snap?.tax_free_now_usd ?? null;

  return (
    <div className="space-y-6">
      <HomeHero
        asOf={asOf}
        cashLabel={cashTf.label}
        priceNote={priceNote}
        wealthRefreshing={wealthRefreshing}
        grade={grade}
        healthScore={health?.score}
        healthSummary={health?.summary}
        marketValueUsd={snap?.total_market_value_usd}
        unrealizedPct={snap?.unrealized_pct}
        netCashflow={net}
        netCzk={cf.net_czk}
        netChangePct={comp?.net_change_pct}
        canGoNext={canGoNextMonth(cashTf)}
        onShiftMonth={shiftCashMonth}
      />

      <TriageList items={triage} max={5} />

      <SignalStrip
        unrealizedPct={snap?.unrealized_pct}
        pacePct={pace?.pace_pct}
        pacePctLiving={pace?.pace_pct_living}
        draw={drawStatus}
        taxFreeNowUsd={taxFree}
      />

      <CashInsight dash={dash} periodLabel={cashTf.label} />

      <HomeDeepLinks />
    </div>
  );
}
