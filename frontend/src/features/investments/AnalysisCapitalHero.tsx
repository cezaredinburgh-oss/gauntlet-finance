import type { FeesSummary, StakingSummary } from "../../api/types";
import { DrawMetricsCard } from "../../components/DrawMetricsCard";
import { FeesBreakdownSection } from "./FeesBreakdownSection";
import { StakingRewardsSection } from "./StakingRewardsSection";

/**
 * Analysis hero: living draw + fees + staking in one glass block.
 */
export function AnalysisCapitalHero({
  fees,
  staking,
}: {
  fees?: FeesSummary | null;
  staking?: StakingSummary | null;
}) {
  return (
    <section
      className="relative overflow-hidden rounded-2xl border p-5 sm:p-6"
      style={{
        background:
          "linear-gradient(135deg, rgba(59,130,246,0.12), rgba(16,185,129,0.08) 50%, rgba(15,23,42,0.9))",
        borderColor: "rgba(52,211,153,0.28)",
        boxShadow: "0 16px 40px rgba(0,0,0,0.3)",
      }}
    >
      <div className="pointer-events-none absolute -right-12 -top-12 h-40 w-40 rounded-full bg-brand/10 blur-3xl" />
      <div className="relative space-y-6">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
            Capital flows
          </div>
          <p className="mt-0.5 text-xs text-ink-faint">
            Living draw vs safe capacity · lifetime fees · staking rewards
          </p>
        </div>

        <DrawMetricsCard embedded />

        {(fees || staking) && (
          <div className="grid gap-6 border-t border-white/10 pt-5 lg:grid-cols-2">
            {fees && (
              <div className={staking ? "" : "lg:col-span-2"}>
                <FeesBreakdownSection fees={fees} embedded />
              </div>
            )}
            {staking && (
              <div className={fees ? "" : "lg:col-span-2"}>
                <StakingRewardsSection staking={staking} embedded />
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
