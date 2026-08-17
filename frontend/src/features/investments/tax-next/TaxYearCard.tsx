import type { TaxReport } from "../../../api/types";
import { formatCzk, formatUsd } from "../../../lib/money";

const FILING_SENTENCE = "On-screen FIFO · not a filing · official use is the pack.";

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "ok" | "warn";
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3">
      <div className="label mb-0.5">{label}</div>
      <div
        className={
          tone === "ok"
            ? "mt-1 text-lg font-semibold tabular-nums text-ok"
            : tone === "warn"
              ? "mt-1 text-lg font-semibold tabular-nums text-warn"
              : "mt-1 text-lg font-semibold tabular-nums"
        }
      >
        {value}
      </div>
    </div>
  );
}

export function TaxYearCard({ report }: { report: TaxReport }) {
  const { summary, meta } = report;
  return (
    <section className="card p-5">
      <div className="mb-3">
        <h2 className="text-sm font-semibold tracking-wide text-brand">
          Year {meta.tax_year} summary
        </h2>
        <p className="text-xs text-ink-faint">{FILING_SENTENCE}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi
          label="Taxable gain (CZK)"
          value={formatCzk(summary.taxable_realized_gain_czk)}
          tone="warn"
        />
        <Kpi
          label="Exempt gain (CZK)"
          value={formatCzk(summary.exempt_realized_gain_czk)}
          tone="ok"
        />
        <Kpi label="Total gain (USD)" value={formatUsd(summary.total_realized_gain_usd)} />
        <Kpi
          label="Disposals"
          value={`${summary.taxable_disposal_count} tax · ${summary.exempt_disposal_count} free`}
        />
      </div>
      <p className="mt-3 text-[11px] text-ink-faint">
        {meta.exemption_days} days · as of {meta.as_of} · {meta.currency_primary_reporting}
      </p>
    </section>
  );
}
