import { Link } from "react-router-dom";
import { cn } from "../../lib/cn";

export function InvestmentsSubNav({
  active,
}: {
  active: "holdings" | "analysis" | "dca" | "tax";
}) {
  const tab = (
    to: string,
    key: typeof active,
    label: string,
  ) => (
    <Link
      to={to}
      className={cn(
        "rounded-lg px-3 py-1.5 text-xs font-semibold transition",
        active === key
          ? "bg-brand/20 text-brand"
          : "text-ink-muted hover:text-ink",
      )}
    >
      {label}
    </Link>
  );

  return (
    <div className="mt-3 flex gap-1 rounded-xl border border-slate-500/25 bg-surface-raised/60 p-1 w-fit">
      {tab("/investments", "holdings", "Holdings")}
      {tab("/investments/analysis", "analysis", "Analysis")}
      {tab("/investments/dca", "dca", "DCA")}
      {tab("/investments/tax", "tax", "Tax")}
    </div>
  );
}

