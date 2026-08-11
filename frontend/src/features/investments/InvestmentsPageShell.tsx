import type { ReactNode } from "react";
import { InvestmentsSubNav } from "./InvestmentsSubNav";

export type InvestmentsTab = "holdings" | "analysis" | "dca" | "tax";

/**
 * Shared page chrome for all Investments routes: title, subtitle, subnav.
 */
export function InvestmentsPageShell({
  active,
  title,
  subtitle,
  children,
  actions,
}: {
  active: InvestmentsTab;
  title: string;
  subtitle: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
          <p className="text-sm text-ink-muted">{subtitle}</p>
          <InvestmentsSubNav active={active} />
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </div>
  );
}
