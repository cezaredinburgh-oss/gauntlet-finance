import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ExternalLink } from "lucide-react";
import { api, setupWizardUrl } from "../api/client";
import type { AlertItem, DashboardSummary, Health, PortfolioSnapshot } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageLoader } from "../components/Spinner";
import { SetupPromptModal } from "../components/SetupPromptModal";
import {
  canGoNextMonth,
  loadStoredSpendingTimeframe,
  saveStoredSpendingTimeframe,
  shiftCalendarMonth,
  type TimeframeValue,
} from "../lib/timeframe";
import {
  dismissOnboardingPrompt,
  migrateLegacyOnboardingIfNeeded,
  onboardingPath,
  shouldShowSetupPrompt,
} from "../lib/onboarding";
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
  const navigate = useNavigate();
  const { user } = useAuth();
  const [cashTf, setCashTf] = useState<TimeframeValue>(() => loadStoredSpendingTimeframe());
  const [dash, setDash] = useState<DashboardSummary | null>(null);
  const [snap, setSnap] = useState<PortfolioSnapshot | null>(null);
  const [digests, setDigests] = useState<TickerDigest[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [wealthRefreshing, setWealthRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [setupPromptOpen, setSetupPromptOpen] = useState(false);
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

  useEffect(() => {
    // Public demos never need the real-sheet setup wizard.
    if (user?.is_demo) {
      setSetupPromptOpen(false);
      return;
    }
    const multiTenant = Boolean(user?.multi_tenant ?? health?.multi_tenant);
    if (multiTenant) {
      setSetupPromptOpen(
        shouldShowSetupPrompt({
          spreadsheetConfigured: null,
          multiTenant: true,
          tenantReady: user?.tenant_ready ?? null,
        }),
      );
      return;
    }
    if (health == null) return;
    migrateLegacyOnboardingIfNeeded(health.spreadsheet_configured);
    setSetupPromptOpen(
      shouldShowSetupPrompt({
        spreadsheetConfigured: health.spreadsheet_configured,
        multiTenant: false,
      }),
    );
  }, [health, user?.multi_tenant, user?.tenant_ready, user?.is_demo]);

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

  const multiTenant = Boolean(user?.multi_tenant ?? health?.multi_tenant);
  const needsSheet = multiTenant
    ? user != null && user.tenant_ready === false
    : health != null && health.spreadsheet_configured === false;

  if (loading && !dash) return <PageLoader label="Loading executive snapshot…" />;
  if (error && !dash) {
    return (
      <div className="space-y-4">
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
      </div>
    );
  }
  if (!dash) return null;

  const cf = dash.cashflow;
  const net = d(cf.net_usd ?? cf.net);
  const comp = dash.comparison;

  return (
    <div className="space-y-6">
      <SetupPromptModal
        open={setupPromptOpen}
        onDismiss={() => {
          dismissOnboardingPrompt();
          setSetupPromptOpen(false);
        }}
        onContinue={() => {
          setSetupPromptOpen(false);
          navigate(onboardingPath());
        }}
      />
      {needsSheet && <SetupSheetsBanner multiTenant={multiTenant} />}
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

function SetupSheetsBanner({ multiTenant = false }: { multiTenant?: boolean }) {
  return (
    <div className="rounded-2xl border border-brand/35 bg-brand/10 px-4 py-4 sm:px-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
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
