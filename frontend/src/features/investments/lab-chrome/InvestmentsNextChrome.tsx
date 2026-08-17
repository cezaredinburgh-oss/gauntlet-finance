import type { ReactNode } from "react";
import type { InvestmentsTab } from "../InvestmentsPageShell";
import { InvestmentsSubNav } from "../InvestmentsSubNav";

/** Next investments chrome: tab pills only. Classic Shell stays untouched. */
export function InvestmentsNextChrome({
  active,
  children,
}: {
  active: InvestmentsTab;
  children: ReactNode;
}) {
  return (
    <div className="space-y-4">
      <div className="-mt-3">
        <InvestmentsSubNav active={active} />
      </div>
      {children}
    </div>
  );
}
