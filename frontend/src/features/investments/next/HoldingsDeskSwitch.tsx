import { cn } from "../../../lib/cn";
import type { HoldingsDesk } from "./holdingsDesk";

/**
 * Lab-only classic/next comparison chrome. Persist lives in the gate click handler.
 */
export function HoldingsDeskSwitch({
  desk,
  onSelectDesk,
}: {
  desk: HoldingsDesk;
  onSelectDesk: (next: HoldingsDesk) => void;
}) {
  return (
    <div
      className="mb-3 flex h-8 w-fit items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-1.5"
      role="group"
      aria-label="Holdings desk"
    >
      <span className="pl-1 text-[10px] font-medium uppercase tracking-wide text-ink-faint">
        Desk
      </span>
      {(
        [
          ["next", "Next"],
          ["classic", "Classic"],
        ] as const
      ).map(([id, label]) => (
        <button
          key={id}
          type="button"
          onClick={() => onSelectDesk(id)}
          aria-pressed={desk === id}
          className={cn(
            "h-6 rounded-md px-2.5 text-[11px] font-semibold transition",
            desk === id
              ? "bg-brand/20 text-brand"
              : "text-ink-faint hover:text-ink-muted",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
