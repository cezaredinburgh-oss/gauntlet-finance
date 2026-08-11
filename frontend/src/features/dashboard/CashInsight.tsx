import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import type { DashboardSummary } from "../../api/types";
import { d, formatUsd } from "../../lib/money";

/**
 * One cash insight from existing dashboard payload (no extra fetch).
 * Prefers top spend domain; falls back to top merchant.
 */
export function CashInsight({
  dash,
  periodLabel,
}: {
  dash: DashboardSummary;
  periodLabel: string;
}) {
  const domains = dash.spending?.by_domain || [];
  const merchants = dash.cashflow?.top_expense_merchants || [];
  const topDomain = [...domains].sort((a, b) => d(b.amount_usd) - d(a.amount_usd))[0];
  const topMerchant = merchants[0];

  if (!topDomain && !topMerchant) return null;

  const expense = d(dash.cashflow.expense_usd ?? dash.cashflow.expense);
  const domainShare =
    topDomain && expense > 0
      ? Math.round((d(topDomain.amount_usd) / expense) * 100)
      : null;

  return (
    <section className="card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold tracking-wide text-brand">Cash insight</h2>
          <p className="mt-0.5 text-xs text-ink-faint">{periodLabel}</p>
          <div className="mt-2 space-y-1 text-sm">
            {topDomain && (
              <p className="text-ink">
                Top domain{" "}
                <span className="font-semibold">{topDomain.name}</span>
                {" · "}
                <span className="tabular-nums font-medium">
                  {formatUsd(topDomain.amount_usd)}
                </span>
                {domainShare != null && (
                  <span className="text-ink-muted"> ({domainShare}% of spend)</span>
                )}
              </p>
            )}
            {topMerchant && (
              <p className="text-ink-muted">
                Top merchant{" "}
                <span className="font-medium text-ink">{topMerchant.label}</span>
                {" · "}
                <span className="tabular-nums">{formatUsd(topMerchant.amount_usd)}</span>
              </p>
            )}
          </div>
        </div>
        <Link
          to="/expenses/spending"
          className="inline-flex shrink-0 items-center gap-0.5 text-xs font-medium text-brand hover:underline"
        >
          Full spending <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </section>
  );
}
