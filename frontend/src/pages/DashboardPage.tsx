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
  ExecutiveHero,
  HomeDeepLinks,
  summarizeAlertBuckets,
} from "../features/dashboard";
import { buildKpiBreakdown } from "../features/investments";
import type { TickerDigest } from "../api/types";

/**
 * Home: portfolio desk hero (wealth + tax runway + cash dial + alert counts).
 * Detail lives on Investments / Spending / Alerts.
 */
export function DashboardPage() {
  const [cashTf, setCashTf] = useState<TimeframeValue>(() => loadStoredSpendingTimeframe());
  const [dash, setDash] = useState<DashboardSummary | null>(null);
  const [snap, setSnap] = useState<PortfolioSnapshot | null>(null);
  const [digests, setDigests] = useState<TickerDigest[]>([]);
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
          const [isnap, dig] = await Promise.all([
            api.investmentsSnapshot(),
            api.tickerDigests().catch(() => null),
          ]);
          if (gen !== loadGen.current) return;
          setSnap(isnap);
          if (dig) setDigests(dig.tickers);
          return;
        }
        const [dsum, isnap, dig, al] = await Promise.all([
          api.dashboard({
            date_from: cashTf.from ?? undefined,
            date_to: cashTf.to,
            period_key: cashTf.key,
          }),
          api.investmentsSnapshot(),
          api.tickerDigests().catch(() => ({ tickers: [] as TickerDigest[] })),
          api.alerts().catch(() => ({ items: [] as AlertItem[], warn_count: 0, total: 0 })),
        ]);
        if (gen !== loadGen.current) return;
        setDash(dsum);
        setSnap(isnap);
        setDigests(dig.tickers || []);
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

  const kpiBreakdown = useMemo(() => {
    if (!snap) return null;
    return buildKpiBreakdown(snap, digests);
  }, [snap, digests]);

  const alertBuckets = useMemo(
    () => summarizeAlertBuckets(alerts, digests),
    [alerts, digests],
  );

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

  return (
    <div className="space-y-6">
      {snap ? (
        <ExecutiveHero
          snap={snap}
          breakdown={kpiBreakdown}
          wealthRefreshing={wealthRefreshing}
          cashLabel={cashTf.label}
          netCashflow={net}
          netCzk={cf.net_czk}
          netChangePct={comp?.net_change_pct}
          canGoNext={canGoNextMonth(cashTf)}
          onShiftMonth={shiftCashMonth}
          alertBuckets={alertBuckets}
        />
      ) : (
        <div className="card p-5 text-sm text-ink-muted">
          Portfolio snapshot unavailable. Cash period: {cashTf.label}. Net{" "}
          {String(net)}.
        </div>
      )}

      <HomeDeepLinks />
    </div>
  );
}
