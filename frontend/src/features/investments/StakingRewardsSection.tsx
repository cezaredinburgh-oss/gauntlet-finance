import type { StakingSummary } from "../../api/types";
import { formatQty, formatUsd } from "../../lib/money";

export function StakingRewardsSection({ staking }: { staking: StakingSummary }) {
  const markNote: Record<string, string> = {
    broker: "broker USD at reward time",
    live: "≈ live mark (units × price now)",
    mixed: "broker + live marks combined",
    unknown: "no USD mark yet",
  };

  return (
    <div className="card p-5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">Staking rewards</h2>
        <span className="badge bg-ok/15 text-ok">
          Added value {formatUsd(staking.mark_usd_total)}
        </span>
        <span className="badge bg-white/5 text-ink-muted">
          {staking.reward_rows} reward events
        </span>
      </div>
      <p className="mb-3 text-xs text-ink-faint">
        Cumulative staking income marked in USD — not a cash deposit. Zero cost basis in holdings.
        Does not increase 12m living-draw “reinvested”.
      </p>

      {staking.by_ticker.length === 0 ? (
        <p className="text-xs text-ink-faint">No staking reward events imported.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[32rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-white/10 text-left text-[11px] uppercase tracking-wide text-ink-faint">
                <th className="px-2 py-2 font-medium">Asset</th>
                <th className="px-2 py-2 text-right font-medium">Added value</th>
                <th className="px-2 py-2 text-right font-medium">Units</th>
                <th className="px-2 py-2 text-right font-medium">Events</th>
                <th className="px-2 py-2 font-medium">Period</th>
                <th className="px-2 py-2 font-medium">How valued</th>
              </tr>
            </thead>
            <tbody>
              {staking.by_ticker.map((row) => (
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
                  <td className="px-2 py-2 text-ink-muted">
                    {row.first} → {row.last}
                  </td>
                  <td className="px-2 py-2 text-[11px] text-ink-faint">
                    {markNote[row.mark_source] || row.mark_source}
                    {row.platforms?.length
                      ? ` · ${row.platforms.join(", ")}`
                      : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
