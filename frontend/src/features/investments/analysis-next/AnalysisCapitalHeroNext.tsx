import type { PortfolioSnapshot } from "../../../api/types";
import { DrawMetricsCard } from "../../../components/DrawMetricsCard";
import { FeesBreakdownSection } from "../FeesBreakdownSection";
import { StakingRewardsSection } from "../StakingRewardsSection";
import { AnalysisCapitalBridge } from "./AnalysisCapitalBridge";
import type { CashflowMonthsPref } from "./cashflowNet";

/**
 * Slimmer capital hero. First child is the mobile capital-bridge site.
 */
export function AnalysisCapitalHeroNext({
  snap,
  monthsPref,
}: {
  snap: PortfolioSnapshot;
  monthsPref: CashflowMonthsPref;
}) {
  const fees = snap.fees;
  const staking = snap.staking;

  return (
    <section className="min-w-0 max-w-full space-y-6 lg:sticky lg:top-12 lg:self-start">
      <div className="lg:hidden">
        <AnalysisCapitalBridge snap={snap} monthsPref={monthsPref} />
      </div>
      <div className="card min-w-0 max-w-full space-y-6 overflow-x-hidden border-white/10 p-5">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
            Capital flows
          </div>
          <p className="mt-0.5 text-xs leading-snug text-ink-faint">
            Living draw vs safe capacity · lifetime fees · staking rewards
          </p>
        </div>

        <DrawMetricsCard embedded narrow />

        {(fees || staking) && (
          <div className="min-w-0 space-y-6 border-t border-white/10 pt-5">
            {fees ? (
              <div className="min-w-0">
                <FeesBreakdownSection fees={fees} embedded />
              </div>
            ) : null}
            {staking ? (
              <div className="min-w-0 overflow-x-auto">
                <StakingRewardsSection staking={staking} embedded />
              </div>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}
