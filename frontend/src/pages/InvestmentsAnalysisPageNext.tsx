import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { PortfolioSnapshot } from "../api/types";
import { EmptyState, PageLoader } from "../components/Spinner";
import { FxUsdCzkChart } from "../components/FxUsdCzkChart";
import { InvestmentsPageShell } from "../features/investments/InvestmentsPageShell";
import { AnalysisCapitalBridge } from "../features/investments/analysis-next/AnalysisCapitalBridge";
import { AnalysisCapitalHeroNext } from "../features/investments/analysis-next/AnalysisCapitalHeroNext";
import { AnalysisHonestyStrip } from "../features/investments/analysis-next/AnalysisHonestyStrip";
import { CashflowMonthlyChartNext } from "../features/investments/analysis-next/CashflowMonthlyChartNext";
import {
  loadCashflowMonthsPref,
  saveCashflowMonthsPref,
  type CashflowMonthsPref,
} from "../features/investments/analysis-next/cashflowNet";

function AnalysisFxWrap({ portfolioUsd }: { portfolioUsd: string | null }) {
  return (
    <div className="space-y-2">
      <FxUsdCzkChart portfolioUsd={portfolioUsd} />
      <p className="text-[11px] text-ink-faint">
        CNB USD/CZK · not a CZK portfolio value.
      </p>
    </div>
  );
}

export function InvestmentsAnalysisPageNext() {
  const [snap, setSnap] = useState<PortfolioSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [monthsPref, setMonthsPref] = useState<CashflowMonthsPref>(() =>
    loadCashflowMonthsPref(),
  );

  function onMonthsPrefChange(next: CashflowMonthsPref) {
    setMonthsPref(next);
    saveCashflowMonthsPref(next);
  }

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
  const cashflow = snap?.cashflow_monthly;
  const hasCashflow = !!cashflow && cashflow.length > 0;

  return (
    <InvestmentsPageShell
      active="analysis"
      title="Investments analysis"
      subtitle="Statement cash · living draw · fees · staking · stored CNB  (not a return %)"
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

      {snap && !hasHoldings && (
        <>
          <AnalysisHonestyStrip snap={snap} />
          <EmptyState
            title="No holdings yet"
            description="Import statements first for cashflow, fees, and staking. FX chart still loads when data exists."
          />
          <AnalysisFxWrap portfolioUsd={snap.total_market_value_usd} />
        </>
      )}

      {snap && hasHoldings && (
        <>
          <AnalysisHonestyStrip snap={snap} showLivingVsCashflow />
          <div className="hidden lg:block">
            <AnalysisCapitalBridge snap={snap} monthsPref={monthsPref} />
          </div>
          <div className="grid gap-6 lg:grid-cols-12">
            <div className="min-w-0 lg:col-span-7">
              {hasCashflow && cashflow ? (
                <CashflowMonthlyChartNext
                  series={cashflow}
                  monthsPref={monthsPref}
                  onMonthsPrefChange={onMonthsPrefChange}
                />
              ) : (
                <p className="text-sm text-ink-faint">
                  No buy/sell cash in the statement window
                </p>
              )}
            </div>
            <div className="lg:col-span-5">
              <AnalysisCapitalHeroNext snap={snap} monthsPref={monthsPref} />
            </div>
          </div>
          <AnalysisFxWrap portfolioUsd={snap.total_market_value_usd} />
        </>
      )}
    </InvestmentsPageShell>
  );
}
