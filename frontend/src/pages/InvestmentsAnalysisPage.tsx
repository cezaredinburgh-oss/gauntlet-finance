import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { PortfolioSnapshot } from "../api/types";
import { EmptyState, PageLoader } from "../components/Spinner";
import { FxUsdCzkChart } from "../components/FxUsdCzkChart";
import {
  AnalysisCapitalHero,
  CashflowMonthlyChart,
  InvestmentsPageShell,
} from "../features/investments";

/**
 * Analysis tools desk: cashflow → capital flows hero (draw/fees/staking) → FX.
 * Live MV history lives on Holdings; health grade on Home.
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

  const hasHoldings = !!snap && snap.ticker_count > 0;

  return (
    <InvestmentsPageShell
      active="analysis"
      title="Investments analysis"
      subtitle="Buy vs sell cash · living draw · fees · staking · CZK/USD"
    >
      {loading && !snap && <PageLoader label="Loading analysis…" />}

      {error && !snap && (
        <EmptyState
          title="Couldn’t load analysis"
          description={error}
          action={
            <button
              type="button"
              className="btn-primary"
              onClick={() => {
                setLoading(true);
                void api
                  .investmentsSnapshot()
                  .then((s) => {
                    setSnap(s);
                    setError(null);
                  })
                  .catch((e) => setError(e instanceof Error ? e.message : "Failed"))
                  .finally(() => setLoading(false));
              }}
            >
              Retry
            </button>
          }
        />
      )}

      {snap && (
        <>
          {!hasHoldings && (
            <EmptyState
              title="No holdings yet"
              description="Import statements first for cashflow, fees, and staking. FX chart still loads when data exists."
            />
          )}

          {hasHoldings && snap.cashflow_monthly && snap.cashflow_monthly.length > 0 && (
            <CashflowMonthlyChart series={snap.cashflow_monthly} />
          )}

          {hasHoldings && (
            <AnalysisCapitalHero fees={snap.fees} staking={snap.staking} />
          )}

          <FxUsdCzkChart portfolioUsd={snap.total_market_value_usd} />
        </>
      )}
    </InvestmentsPageShell>
  );
}
