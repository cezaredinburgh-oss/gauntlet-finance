import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ExternalLink } from "lucide-react";
import { api, setupWizardUrl } from "../api/client";
import type { AlertItem, DashboardSummary, Health, PortfolioSnapshot } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { HOME_DESK } from "../auth/labDesk";
import { EmptyState, PageLoader } from "../components/Spinner";
import {
  canGoNextMonth,
  loadStoredSpendingTimeframe,
  saveStoredSpendingTimeframe,
  shiftCalendarMonth,
  type TimeframeValue,
} from "../lib/timeframe";
import { onboardingPath } from "../lib/onboarding";
import { d } from "../lib/money";
import { summarizeAlertBuckets } from "../features/dashboard";
import { HomeAlertCounts } from "../features/dashboard-next/HomeAlertCounts";
import { HomeExecutiveNext } from "../features/dashboard-next/HomeExecutiveNext";
import { TaxRunwayCard } from "../features/investments/TaxRunwayCard";
import { LabNextChrome } from "../lab-chrome/LabNextChrome";
import type { TickerDigest } from "../api/types";

/** Lab next Home: wealth + cash + runway + work counts. Same five fetches as classic. */
export function DashboardPageNext() {
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
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

  const alertBuckets = useMemo(
    () => summarizeAlertBuckets(alerts, digests),
    [alerts, digests],
  );

  const multiTenant = Boolean(user?.multi_tenant ?? health?.multi_tenant);
  const needsSheet = multiTenant
    ? user != null && user.tenant_ready === false
    : health != null && health.spreadsheet_configured === false;

  const taxFocus =
    searchParams.get("focus") === "tax_runway" ? "tax_runway" : undefined;
  const hasTaxBuckets = Boolean(snap?.tax_runway?.buckets?.length);

  return (
    <LabNextChrome config={HOME_DESK} label="Home desk">
      {loading && !dash && <PageLoader label="Loading executive snapshot…" />}

      {error && !dash && (
        <>
          {needsSheet && <SetupSheetsBanner multiTenant={multiTenant} />}
          <EmptyState
            title="Couldn’t load dashboard"
            description={
              needsSheet
                ? multiTenant
                  ? "Your tenant ledger is not provisioned yet. Complete setup, then retry."
                  : "Google Sheets is not linked yet. Complete setup, then retry."
                : error
            }
            action={
              <div className="flex flex-wrap gap-2">
                {needsSheet && (
                  <Link className="btn-primary inline-flex" to={onboardingPath()}>
                    Start setup
                  </Link>
                )}
                <button type="button" className="btn-secondary" onClick={() => void load()}>
                  Retry
                </button>
              </div>
            }
          />
        </>
      )}

      {dash && (
        <>
          {needsSheet && <SetupSheetsBanner multiTenant={multiTenant} />}
          <HomeExecutiveNext
            dash={dash}
            snap={snap}
            wealthRefreshing={wealthRefreshing}
            cashLabel={cashTf.label}
            netCashflow={d(dash.cashflow.net_usd ?? dash.cashflow.net)}
            netCzk={dash.cashflow.net_czk}
            netChangePct={dash.comparison?.net_change_pct}
            canGoNext={canGoNextMonth(cashTf)}
            onShiftMonth={shiftCashMonth}
          />
          {snap && hasTaxBuckets && (
            <TaxRunwayCard snap={snap} embedded={false} focus={taxFocus} />
          )}
          <HomeAlertCounts buckets={alertBuckets} />
        </>
      )}
    </LabNextChrome>
  );
}

function SetupSheetsBanner({ multiTenant = false }: { multiTenant?: boolean }) {
  return (
    <div className="min-w-0 rounded-2xl border border-brand/35 bg-brand/10 px-4 py-4 sm:px-5">
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-brand">Finish setup</div>
          <p className="mt-1 max-w-xl text-xs text-ink-muted sm:text-sm">
            {multiTenant
              ? "Your account needs a private ledger sheet. Open setup to provision it, then upload statements and set spending rules."
              : "New here? Guided path: welcome, connect your private Google Sheet, upload bank statements, and set spending rules — about 10–15 minutes."}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Link
            className="btn-primary inline-flex"
            to={onboardingPath({ step: multiTenant ? "sheets" : "welcome" })}
          >
            {multiTenant ? "Provision ledger" : "Start setup"}
          </Link>
          {!multiTenant && (
            <a
              className="btn-secondary inline-flex text-sm"
              href={setupWizardUrl()}
              target="_blank"
              rel="noreferrer"
            >
              Sheets only
              <ExternalLink className="h-4 w-4" />
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
