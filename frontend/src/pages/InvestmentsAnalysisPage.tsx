import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { PortfolioSnapshot } from "../api/types";
import { EmptyState, PageLoader } from "../components/Spinner";
import { FxUsdCzkChart } from "../components/FxUsdCzkChart";
import {
  CashflowMonthlyChart,
  FeesBreakdownSection,
  HealthBand,
  InvestmentsSubNav,
  StakingRewardsSection,
} from "./InvestmentsPage";

/** Portfolio health, cashflow, fees, staking, FX — split from main Holdings page. */
export function InvestmentsAnalysisPage() {
  const [snap, setSnap] = useState<PortfolioSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const s = await api.investmentsSnapshot();
        if (!cancelled) {
          setSnap(s);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) return <PageLoader label="Loading analysis…" />;
  if (error) {
    return <EmptyState title="Couldn’t load analysis" description={error} />;
  }

  const hasHoldings = !!snap && snap.ticker_count > 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Investments analysis</h1>
        <p className="text-sm text-ink-muted">
          Portfolio health · cashflow · fees · staking · CZK/USD
        </p>
        <InvestmentsSubNav active="analysis" />
      </div>

      {!hasHoldings && (
        <EmptyState
          title="No holdings yet"
          description="Import statements first for health, fees, and staking. FX rates still chart below when available."
        />
      )}

      {hasHoldings && snap.health && <HealthBand health={snap.health} />}

      {hasHoldings && snap.cashflow_monthly && snap.cashflow_monthly.length > 0 && (
        <CashflowMonthlyChart series={snap.cashflow_monthly} />
      )}

      {hasHoldings && snap.fees && <FeesBreakdownSection fees={snap.fees} />}
      {hasHoldings && snap.staking && <StakingRewardsSection staking={snap.staking} />}

      <FxUsdCzkChart portfolioUsd={snap?.total_market_value_usd} />
    </div>
  );
}
