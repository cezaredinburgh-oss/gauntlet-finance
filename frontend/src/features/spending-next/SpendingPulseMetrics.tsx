import type { ReactNode } from "react";
import type { DashboardSummary } from "../../api/types";
import { HoverPanel } from "../../components/HoverPanel";
import { Money } from "../../components/Money";
import { cn } from "../../lib/cn";
import { d, formatCzk, formatUsd, hasMoneyValue } from "../../lib/money";

function deltaText(
  pct: number | null | undefined,
  invertGood = false,
): { text: string; cls: string } {
  if (pct === null || pct === undefined) return { text: "vs prior: —", cls: "text-ink-faint" };
  const good = invertGood ? pct < 0 : pct > 0;
  const bad = invertGood ? pct > 0 : pct < 0;
  const cls = good ? "text-ok" : bad ? "text-danger" : "text-ink-muted";
  const sign = pct >= 0 ? "+" : "";
  return { text: `vs prior: ${sign}${pct.toFixed(0)}%`, cls };
}

function HoverList({
  title,
  rows,
}: {
  title: string;
  rows: Array<{ label: string; value: string }>;
}) {
  if (!rows.length) return <div className="text-xs text-ink-faint">{title}: none</div>;
  return (
    <div className="mb-2">
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
        {title}
      </div>
      <ul className="space-y-0.5">
        {rows.map((r) => (
          <li key={r.label} className="flex justify-between gap-3 text-xs">
            <span className="truncate text-ink-muted">{r.label}</span>
            <span className="shrink-0 font-medium">{r.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function PulseMetric({
  label,
  figure,
  delta,
  tone,
  hover,
}: {
  label: string;
  figure: ReactNode;
  delta?: { text: string; cls: string };
  tone: string;
  hover?: ReactNode;
}) {
  const body = (
    <div className="min-w-0 max-w-full break-words">
      <div className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">
        {label}
      </div>
      <div className={cn("min-w-0 max-w-full break-words font-semibold tabular-nums tracking-tight", tone)}>
        {figure}
      </div>
      {delta ? (
        <div className={cn("min-w-0 max-w-full break-words text-[11px] font-medium tabular-nums", delta.cls)}>
          {delta.text}
        </div>
      ) : null}
    </div>
  );
  if (!hover) return body;
  return (
    <HoverPanel content={hover} className="min-w-0 max-w-full">
      {body}
    </HoverPanel>
  );
}

/** Two-row Net / Income / Expenses / Pace. Never figure + badge on one wrapping row. */
export function SpendingPulseMetrics({ dash }: { dash: DashboardSummary }) {
  const cf = dash.cashflow;
  const income = d(cf.income_usd ?? cf.income);
  const expense = d(cf.expense_usd ?? cf.expense);
  const net = d(cf.net_usd ?? cf.net);
  const comp = dash.comparison;
  const pace = dash.pace;
  const pacePct = pace?.pace_pct ?? null;

  const netDelta = deltaText(comp?.net_change_pct ?? null);
  const incomeDelta = deltaText(comp?.income_change_pct ?? null);
  const expenseDelta = deltaText(comp?.expense_change_pct ?? null, true);

  const paceFigure =
    pacePct === null
      ? "—"
      : `${pacePct >= 0 ? "+" : ""}${pacePct.toFixed(0)}%`;
  const paceTone =
    pacePct === null
      ? "text-ink-faint"
      : pacePct > 10
        ? "text-warn"
        : pacePct < -10
          ? "text-ok"
          : "text-ink";

  return (
    <div className="grid min-w-0 grid-cols-2 gap-3 sm:grid-cols-4">
      <PulseMetric
        label="Net"
        tone={net >= 0 ? "text-ok" : "text-danger"}
        delta={netDelta}
        figure={
          <Money
            amount={net}
            currency="USD"
            amountCzk={cf.net_czk}
            secondaryMode="hover"
            size="md"
            signed
          />
        }
        hover={
          <>
            <HoverList
              title="Summary"
              rows={[
                { label: "Income", value: formatUsd(income) },
                { label: "Expenses", value: formatUsd(expense) },
                { label: "Net", value: formatUsd(net) },
                ...(hasMoneyValue(cf.net_czk)
                  ? [{ label: "CZK net", value: formatCzk(cf.net_czk) }]
                  : []),
              ]}
            />
            {comp ? (
              <div className="text-xs text-ink-faint">
                Prior {comp.prior_from} → {comp.prior_to}: {formatUsd(comp.net_usd)}
              </div>
            ) : null}
          </>
        }
      />
      <PulseMetric
        label="Income"
        tone="text-ok"
        delta={incomeDelta}
        figure={
          <Money
            amount={income}
            currency="USD"
            amountCzk={cf.income_czk}
            secondaryMode="hover"
            size="md"
          />
        }
        hover={
          <HoverList
            title="Top sources"
            rows={(cf.top_income || []).map((t) => ({
              label: t.label,
              value: formatUsd(t.amount_usd),
            }))}
          />
        }
      />
      <PulseMetric
        label="Expenses"
        tone="text-danger"
        delta={expenseDelta}
        figure={
          <Money
            amount={expense}
            currency="USD"
            amountCzk={cf.expense_czk}
            secondaryMode="hover"
            size="md"
          />
        }
        hover={
          <HoverList
            title="Top merchants"
            rows={(cf.top_expense_merchants || []).map((t) => ({
              label: t.label,
              value: formatUsd(t.amount_usd),
            }))}
          />
        }
      />
      <PulseMetric
        label="Pace"
        tone={paceTone}
        figure={paceFigure}
        hover={
          <div className="text-xs text-ink-muted">
            30d spend {formatUsd(pace?.spend_30d_usd)}
          </div>
        }
      />
    </div>
  );
}
