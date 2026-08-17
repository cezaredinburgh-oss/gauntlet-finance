import type { AlertItem } from "../../api/types";
import { cn } from "../../lib/cn";
import { AlertCardNext } from "./AlertCardNext";
import {
  DOMAIN_LABELS,
  type DomainKey,
} from "./domainBoard";

const DOMAIN_META: Record<DomainKey, { accent: string; border: string }> = {
  spending: { accent: "text-brand", border: "border-brand/30" },
  stocks: { accent: "text-ok", border: "border-ok/30" },
  crypto: { accent: "text-warn", border: "border-warn/30" },
};

/** Static map — Tailwind will not emit interpolated `lg:grid-cols-${n}`. */
const GRID_COLS: Record<1 | 2 | 3, string> = {
  1: "lg:grid-cols-1",
  2: "lg:grid-cols-2",
  3: "lg:grid-cols-3",
};

export function AlertsBoardNext({
  grouped,
  domains,
  seenTick,
  onActivate,
}: {
  grouped: Record<DomainKey, AlertItem[]>;
  domains: DomainKey[];
  seenTick: number;
  onActivate: (a: AlertItem) => void;
}) {
  if (domains.length === 0) return null;
  const n = Math.min(domains.length, 3) as 1 | 2 | 3;

  return (
    <div className={cn("grid min-w-0 gap-4", GRID_COLS[n])}>
      {domains.map((key) => {
        const meta = DOMAIN_META[key];
        const list = grouped[key];
        return (
          <div
            key={key}
            className={cn(
              "flex min-w-0 flex-col rounded-xl border bg-black/25 p-4",
              meta.border,
            )}
          >
            <div className="mb-3 flex min-w-0 items-center justify-between gap-2">
              <h2
                className={cn(
                  "min-w-0 text-sm font-semibold tracking-wide",
                  meta.accent,
                )}
              >
                {DOMAIN_LABELS[key]}
              </h2>
              <span className="badge shrink-0 bg-white/5 text-ink-muted tabular-nums">
                {list.length}
              </span>
            </div>
            <ul className="space-y-2">
              {list.map((a) => (
                <AlertCardNext
                  key={a.id}
                  alert={a}
                  seenTick={seenTick}
                  onActivate={onActivate}
                />
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
