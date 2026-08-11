import {
  ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from "recharts";
import type { FeesSummary } from "../../api/types";
import { Money } from "../../components/Money";
import { d, formatUsd } from "../../lib/money";

export function FeesBreakdownSection({
  fees,
  embedded = false,
}: {
  fees: FeesSummary;
  embedded?: boolean;
}) {
  const byType = fees.fees_by_event_type.map((x) => ({
    name: x.label,
    amount: d(x.amount_usd),
  }));
  const byPlat = fees.fees_by_platform.map((x) => ({
    name: x.platform,
    amount: d(x.amount_usd),
  }));
  const hasAmounts = d(fees.total_fees_usd) > 0 || byType.length > 0;

  return (
    <div className={embedded ? "p-0" : "card p-5"}>
      <div className="mb-1">
        <h2
          className={
            embedded
              ? "text-sm font-semibold tracking-wide text-warn"
              : "text-sm font-semibold"
          }
        >
          Fees breakdown
        </h2>
        <p className="text-xs text-ink-faint">
          Trade commissions and explicit fee events from investment statements (lifetime). Buy
          fees include Revolut crypto service fees (the same Fees column used to fee-net DOGE/XRP
          units at import).
        </p>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MiniStat label="Total fees" value={fees.total_fees_usd} />
        <MiniStat label="Trade fees" value={fees.trade_fees_usd} sub="Buy / Sell fees_usd" />
        <MiniStat
          label="Explicit fee events"
          value={fees.explicit_fee_events_usd}
          sub="Custody · Commission · Fee"
        />
        <MiniStat label="Deposits" value={fees.deposits_usd} sub="Context · not a fee" />
      </div>

      {!hasAmounts ? (
        <p className="mt-4 text-xs text-ink-faint">No fee amounts on imported investment events.</p>
      ) : (
        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <FeeBarChart title="Fees by type" data={byType} />
          <FeeBarChart title="Fees by platform" data={byPlat} />
        </div>
      )}

      <p className="mt-3 text-[11px] text-ink-faint">
        Withdrawals {formatUsd(fees.withdrawals_usd)} · full history · living draw above is
        rolling 365d only
      </p>
    </div>
  );
}

function MiniStat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
      <div className="label mb-0.5">{label}</div>
      <Money amount={value} currency="USD" secondaryMode="none" size="lg" />
      {sub ? <div className="mt-0.5 text-[11px] text-ink-faint">{sub}</div> : null}
    </div>
  );
}

function FeeBarChart({
  title,
  data,
}: {
  title: string;
  data: Array<{ name: string; amount: number }>;
}) {
  if (!data.length) {
    return (
      <div>
        <p className="mb-2 text-xs font-medium text-ink-muted">{title}</p>
        <p className="text-xs text-ink-faint">No series</p>
      </div>
    );
  }
  return (
    <div>
      <p className="mb-2 text-xs font-medium text-ink-muted">{title}</p>
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 24 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
            <XAxis
              dataKey="name"
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              interval={0}
              angle={-20}
              textAnchor="end"
              height={48}
            />
            <YAxis
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              tickFormatter={(v: number) =>
                v >= 1000 ? `$${(v / 1000).toFixed(1)}k` : `$${v}`
              }
            />
            <Tooltip
              contentStyle={{
                background: "#0f172a",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={(value: number | string) => [
                formatUsd(typeof value === "number" ? value : d(String(value))),
                "Fees",
              ]}
            />
            <Bar dataKey="amount" fill="rgba(45, 212, 168, 0.75)" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

