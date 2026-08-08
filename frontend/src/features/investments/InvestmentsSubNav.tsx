import { Link } from "react-router-dom";
import { cn } from "../../lib/cn";

export function InvestmentsSubNav({
  active,
}: {
  active: "holdings" | "analysis" | "tax";
}) {
  return (
    <div className="mt-3 flex gap-1 rounded-xl border border-slate-500/25 bg-surface-raised/60 p-1 w-fit">
      <Link
        to="/investments"
        className={cn(
          "rounded-lg px-3 py-1.5 text-xs font-semibold transition",
          active === "holdings"
            ? "bg-brand/20 text-brand"
            : "text-ink-muted hover:text-ink",
        )}
      >
        Holdings
      </Link>
      <Link
        to="/investments/analysis"
        className={cn(
          "rounded-lg px-3 py-1.5 text-xs font-semibold transition",
          active === "analysis"
            ? "bg-brand/20 text-brand"
            : "text-ink-muted hover:text-ink",
        )}
      >
        Analysis
      </Link>
      <Link
        to="/investments/tax"
        className={cn(
          "rounded-lg px-3 py-1.5 text-xs font-semibold transition",
          active === "tax"
            ? "bg-brand/20 text-brand"
            : "text-ink-muted hover:text-ink",
        )}
      >
        Tax
      </Link>
    </div>
  );
}

