import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { Money } from "../../components/Money";
import { formatUsd } from "../../lib/money";
import { cn } from "../../lib/cn";
import type { CompactDrawStatus } from "./drawStatus";

function SignalCell({
  label,
  children,
  footer,
}: {
  label: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-black/20 p-3">
      <div className="label mb-1">{label}</div>
      {children}
      {footer}
    </div>
  );
}

export function SignalStrip({
  unrealizedPct,
  pacePct,
  pacePctLiving,
  draw,
  taxFreeNowUsd,
}: {
  unrealizedPct: number | null | undefined;
  pacePct: number | null | undefined;
  pacePctLiving?: number | null;
  draw: CompactDrawStatus | null;
  taxFreeNowUsd: string | null | undefined;
}) {
  return (
    <section className="card p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold tracking-wide text-ink">Signals</h2>
          <p className="text-[11px] text-ink-faint">
            Secondary pulse · detail on Holdings / Analysis / Spending
          </p>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SignalCell label="Unrealized">
          {unrealizedPct != null ? (
            <div
              className={cn(
                "text-xl font-semibold tabular-nums",
                unrealizedPct >= 0 ? "text-ok" : "text-danger",
              )}
            >
              {unrealizedPct >= 0 ? "+" : ""}
              {unrealizedPct.toFixed(1)}%
            </div>
          ) : (
            <div className="text-xl text-ink-faint">—</div>
          )}
          <div className="text-[11px] text-ink-faint">vs open cost</div>
        </SignalCell>

        <SignalCell label="Spend pace (30d)">
          <div
            className={cn(
              "text-xl font-semibold tabular-nums",
              pacePct != null && pacePct > 10
                ? "text-warn"
                : pacePct != null && pacePct < -10
                  ? "text-ok"
                  : "text-ink",
            )}
          >
            {pacePct == null
              ? "—"
              : `${pacePct >= 0 ? "+" : ""}${pacePct.toFixed(0)}%`}
          </div>
          <div className="text-[11px] text-ink-faint">
            vs 6‑mo avg
            {pacePctLiving != null && (
              <>
                {" · "}
                living {pacePctLiving >= 0 ? "+" : ""}
                {pacePctLiving.toFixed(0)}%
              </>
            )}
          </div>
        </SignalCell>

        <SignalCell
          label="Living draw (TTM)"
          footer={
            <Link
              to="/investments/analysis"
              className="mt-1 inline-flex items-center gap-0.5 text-[11px] font-medium text-brand hover:underline"
            >
              Full draw <ArrowRight className="h-3 w-3" />
            </Link>
          }
        >
          {draw ? (
            <>
              <div
                className={cn(
                  "text-xl font-semibold tabular-nums",
                  draw.status === "over"
                    ? "text-danger"
                    : draw.status === "warn"
                      ? "text-warn"
                      : draw.livingUsd <= 0
                        ? "text-ok"
                        : "text-ink",
                )}
              >
                {draw.livingUsd >= 0 ? "+" : ""}
                {formatUsd(draw.livingUsd)}
              </div>
              <div
                className={cn(
                  "text-[11px] font-medium",
                  draw.status === "ok" && "text-ok",
                  draw.status === "warn" && "text-warn",
                  draw.status === "over" && "text-danger",
                  draw.status === "n/a" && "text-ink-faint",
                )}
              >
                {draw.label}
                {draw.safeUsd > 0 && (
                  <span className="font-normal text-ink-faint">
                    {" "}
                    · safe {formatUsd(draw.safeUsd)}
                  </span>
                )}
              </div>
            </>
          ) : (
            <div className="text-xl text-ink-faint">—</div>
          )}
        </SignalCell>

        <SignalCell
          label="Tax-free now"
          footer={
            <Link
              to="/investments?focus=tax_runway"
              className="mt-1 inline-flex items-center gap-0.5 text-[11px] font-medium text-brand hover:underline"
            >
              Runway <ArrowRight className="h-3 w-3" />
            </Link>
          }
        >
          {taxFreeNowUsd != null ? (
            <Money
              amount={taxFreeNowUsd}
              currency="USD"
              secondaryMode="hover"
              size="lg"
            />
          ) : (
            <div className="text-xl text-ink-faint">—</div>
          )}
          <div className="text-[11px] text-ink-faint">Czech 3y eligible MV</div>
        </SignalCell>
      </div>
    </section>
  );
}
