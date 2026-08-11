import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { PortfolioSnapshot } from "../api/types";
import { EmptyState, PageLoader } from "../components/Spinner";
import { FxUsdCzkChart } from "../components/FxUsdCzkChart";
import { DrawMetricsCard } from "../components/DrawMetricsCard";
import {
  CashflowMonthlyChart,
  FeesBreakdownSection,
  HealthBand,
  InvestmentsPageShell,
  StakingRewardsSection,
} from "../features/investments";

/**
 * Analysis tools desk: health, draw, cashflow, fees, staking, FX.
 * Live MV history lives on Holdings (single chart home).
 */
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

  useEffect(() => {
    const onPrices = () => {
      void api
        .investmentsSnapshot()
        .then((s) => {
          setSnap(s);
          setError(null);
        })
        .catch(() => {
          /* keep last snap */
        });
    };
    window.addEventListener("prices-updated", onPrices);
    return () => window.removeEventListener("prices-updated", onPrices);
  }, []);

  if (loading) return <PageLoader label="Loading analysis…" />;
  if (error) {
    return <EmptyState title="Couldn’t load analysis" description={error} />;
  }

  const hasHoldings = !!snap && snap.ticker_count > 0;

  return (
    <InvestmentsPageShell
      active="analysis"
      title="Investments analysis"
      subtitle="Portfolio health · living draw · cashflow · fees · staking · CZK/USD"
    >
      {!hasHoldings && (
        <EmptyState
          title="No holdings yet"
          description="Import statements first for health, fees, and staking. FX chart still loads when data exists."
        />
      )}

      {hasHoldings && snap.health && <HealthBand health={snap.health} />}

      {hasHoldings && <DrawMetricsCard />}

      {hasHoldings && snap.cashflow_monthly && snap.cashflow_monthly.length > 0 && (
        <CashflowMonthlyChart series={snap.cashflow_monthly} />
      )}

      {hasHoldings && snap.fees && <FeesBreakdownSection fees={snap.fees} />}
      {hasHoldings && snap.staking && <StakingRewardsSection staking={snap.staking} />}

      <FxUsdCzkChart portfolioUsd={snap?.total_market_value_usd} />
    </InvestmentsPageShell>
  );
}
