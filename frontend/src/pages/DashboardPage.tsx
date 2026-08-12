import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink } from "lucide-react";
import { api, setupWizardUrl } from "../api/client";
import type { AlertItem, DashboardSummary, Health, PortfolioSnapshot } from "../api/types";
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
  const [health, setHealth] = useState<Health | null>(null);
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
        const [dsum, isnap, dig, al, h] = await Promise.all([
          api.dashboard({
            date_from: cashTf.from ?? undefined,
            date_to: cashTf.to,
            period_key: cashTf.key,
          }),
          api.investmentsSnapshot(),
          api.tickerDigests().catch(() => ({ tickers: [] as TickerDigest[] })),
          api.alerts().catch(() => ({ items: [] as AlertItem[], warn_count: 0, total: 0 })),
          api.health().catch(() => null),
        ]);
        if (gen !== loadGen.current) return;
        setDash(dsum);
        setSnap(isnap);
        setDigests(dig.tickers || []);
        setAlerts(al.items || []);
        if (h) setHealth(h);
      } catch (e) {
        if (gen !== loadGen.current) return;
        if (pricesOnly) return;
        setError(e instanceof Error ? e.message : "Failed to load");
        // Still try health so unconfigured sheet CTA can show
        void api.health().then(setHealth).catch(() => undefined);
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

  const needsSheet =
    health != null && health.spreadsheet_configured === false;

  if (loading && !dash) return <PageLoader label="Loading executive snapshot…" />;
  if (error && !dash) {
    return (
      <div className="space-y-4">
        {needsSheet && (
          <SetupSheetsBanner />
        )}
        <EmptyState
          title="Couldn’t load dashboard"
          description={
            needsSheet
              ? "Google Sheets is not linked yet. Use the setup wizard, then retry."
              : error
          }
          action={
            <div className="flex flex-wrap gap-2">
              {needsSheet && (
                <a
                  className="btn-primary inline-flex"
                  href={setupWizardUrl()}
                  target="_blank"
                  rel="noreferrer"
                >
                  Connect Google Sheets
                  <ExternalLink className="h-4 w-4" />
                </a>
              )}
              <button type="button" className="btn-secondary" onClick={() => void load()}>
                Retry
              </button>
            </div>
          }
        />
      </div>
    );
  }
  if (!dash) return null;

  const cf = dash.cashflow;
  const net = d(cf.net_usd ?? cf.net);
  const comp = dash.comparison;

  return (
    <div className="space-y-6">
      {needsSheet && <SetupSheetsBanner />}
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

function SetupSheetsBanner() {
  return (
    <div className="rounded-2xl border border-brand/35 bg-brand/10 px-4 py-4 sm:px-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-sm font-semibold text-brand">Connect Google Sheets</div>
          <p className="mt-1 max-w-xl text-xs text-ink-muted sm:text-sm">
            New here? Link a private spreadsheet so Gauntlet can store your ledger. A short
            guided wizard walks you through Cloud, key, sheet, and ledger tabs — no coding.
          </p>
        </div>
        <a
          className="btn-primary inline-flex shrink-0"
          href={setupWizardUrl()}
          target="_blank"
          rel="noreferrer"
        >
          Start setup
          <ExternalLink className="h-4 w-4" />
        </a>
      </div>
    </div>
  );
}
