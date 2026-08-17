import type { PortfolioSnapshot } from "../../../api/types";
import { Money } from "../../../components/Money";
import {
  cashflowWindowCaption,
  netSecurityCashUsd,
  sliceCashflowWindow,
  type CashflowMonthsPref,
} from "./cashflowNet";

const SIGN_CAPTION =
  "Net security cash is bought − sold (deployed). Living draw is sells − buys (drawn). Opposite signs by job.";

function Figure({
  label,
  caption,
  value,
}: {
  label: string;
  caption?: string;
  value: string | number | null | undefined;
}) {
  const missing = value === null || value === undefined || value === "";
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-ink-faint">{label}</div>
      {caption ? <div className="text-[10px] text-ink-faint">{caption}</div> : null}
      <div className="mt-0.5 text-sm font-semibold tabular-nums text-ink">
        {missing ? (
          "—"
        ) : (
          <Money amount={value} currency="USD" secondaryMode="none" size="sm" />
        )}
      </div>
    </div>
  );
}

/**
 * Four cash/mark figures. No ΔMV. Mounted twice with complementary visibility.
 */
export function AnalysisCapitalBridge({
  snap,
  monthsPref,
}: {
  snap: PortfolioSnapshot;
  monthsPref: CashflowMonthsPref;
}) {
  const windowRows = sliceCashflowWindow(snap.cashflow_monthly ?? [], monthsPref);
  const net = netSecurityCashUsd(windowRows);

  return (
    <div className="card p-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Figure
          label="Net security cash (bought − sold)"
          caption={cashflowWindowCaption(monthsPref)}
          value={net.netDeployed}
        />
        <Figure
          label="Living draw 12m"
          caption="sells − buys · stored value_usd"
          value={snap.living_draw_12m?.draw_usd}
        />
        <Figure label="Lifetime fees" value={snap.fees?.total_fees_usd} />
        <Figure
          label="Staking marks"
          caption="not cash"
          value={snap.staking?.mark_usd_total}
        />
      </div>
      <p className="mt-3 text-[11px] text-ink-faint">{SIGN_CAPTION}</p>
    </div>
  );
}
