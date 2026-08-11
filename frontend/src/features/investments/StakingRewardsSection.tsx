import type { StakingByTicker, StakingSummary } from "../../api/types";
import { d, formatQty, formatUsd } from "../../lib/money";

/**
 * Inclusive calendar months between first and last reward date (min 1).
 * Used for rough average monthly mark-value of staking rewards.
 */
export function stakingSpanMonths(first: string, last: string): number {
  const parse = (s: string) => {
    const raw = s.length === 10 ? `${s}T00:00:00Z` : s;
    return new Date(raw);
  };
  const a = parse(first);
  const b = parse(last);
  if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return 1;
  const start = a <= b ? a : b;
  const end = a <= b ? b : a;
  const months =
    (end.getUTCFullYear() - start.getUTCFullYear()) * 12 +
    (end.getUTCMonth() - start.getUTCMonth()) +
    1;
  return Math.max(1, months);
}

export function avgMonthlyStakingUsd(row: StakingByTicker): number {
  const total = d(row.mark_usd);
  const months = stakingSpanMonths(row.first, row.last);
  return total / months;
}

export function StakingRewardsSection({
  staking,
  embedded = false,
}: {
  staking: StakingSummary;
  embedded?: boolean;
}) {
  return (
    <div className={embedded ? "p-0" : "card p-5"}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2
          className={
            embedded
              ? "text-sm font-semibold tracking-wide text-brand"
              : "text-sm font-semibold"
          }
        >
          Staking rewards
        </h2>
        <span className="badge bg-ok/15 text-ok">
          Added value {formatUsd(staking.mark_usd_total)}
        </span>
        <span className="badge bg-white/5 text-ink-muted">
          {staking.reward_rows} reward events
        </span>
      </div>
      <p className="mb-3 text-xs text-ink-faint">
        Cumulative staking income marked in USD — not a cash deposit. Zero cost basis in
        holdings. Avg $/mo ≈ total mark ÷ inclusive months from first to last reward.
      </p>

      {staking.by_ticker.length === 0 ? (
        <p className="text-xs text-ink-faint">No staking reward events imported.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[28rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-white/10 text-left text-[11px] uppercase tracking-wide text-ink-faint">
                <th className="px-2 py-2 font-medium">Asset</th>
                <th className="px-2 py-2 text-right font-medium">Added value</th>
                <th className="px-2 py-2 text-right font-medium">Units</th>
                <th className="px-2 py-2 text-right font-medium">Events</th>
                <th
                  className="px-2 py-2 text-right font-medium"
                  title="Total mark USD ÷ inclusive months between first and last reward"
                >
                  Avg $/mo
                </th>
              </tr>
            </thead>
            <tbody>
              {staking.by_ticker.map((row) => {
                const avgMo = avgMonthlyStakingUsd(row);
                const months = stakingSpanMonths(row.first, row.last);
                return (
                  <tr key={row.ticker} className="border-b border-white/5">
                    <td className="px-2 py-2 font-semibold">{row.ticker}</td>
                    <td className="px-2 py-2 text-right tabular-nums">
                      {formatUsd(row.mark_usd)}
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums text-ink-muted">
                      {formatQty(row.units)}
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums text-ink-muted">
                      {row.events}
                    </td>
                    <td
                      className="px-2 py-2 text-right tabular-nums text-ok"
                      title={`${months} month${months === 1 ? "" : "s"} (${row.first} → ${row.last})`}
                    >
                      {formatUsd(avgMo)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
