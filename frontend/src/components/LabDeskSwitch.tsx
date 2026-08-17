import { cn } from "../lib/cn";
import type { LabDesk } from "../auth/labDesk";

/**
 * Lab-only classic/next comparison chrome. Persist lives in the gate click handler.
 */
export function LabDeskSwitch({
  desk,
  onSelectDesk,
  label,
  embedded = false,
}: {
  desk: LabDesk;
  onSelectDesk: (next: LabDesk) => void;
  label: string;
  embedded?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex h-8 w-fit items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-1.5",
        !embedded && "mb-3",
      )}
      role="group"
      aria-label={label}
    >
      <span className="pl-1 text-[10px] font-medium uppercase tracking-wide text-ink-faint">
        Desk
      </span>
      {(
        [
          ["next", "Next"],
          ["classic", "Classic"],
        ] as const
      ).map(([id, buttonLabel]) => (
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
          {buttonLabel}
        </button>
      ))}
    </div>
  );
}
