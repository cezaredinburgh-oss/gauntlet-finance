import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../../../auth/AuthContext";
import { isLabSession } from "../../../auth/isLabSession";
import {
  ANALYSIS_DESK,
  DCA_DESK,
  TAX_DESK,
  mergeDeskParam as mergeLabDeskParam,
  resolveLabDesk,
  saveLabDesk,
  type LabDesk,
  type LabDeskConfig,
} from "../../../auth/labDesk";
import { LabDeskSwitch } from "../../../components/LabDeskSwitch";
import {
  mergeDeskParam as mergeHoldingsDeskParam,
  resolveHoldingsDesk,
  savePersistedDesk,
} from "../next/holdingsDesk";
import type { InvestmentsTab } from "../InvestmentsPageShell";
import { InvestmentsSubNav } from "../InvestmentsSubNav";

const SURFACE: Record<
  Exclude<InvestmentsTab, "holdings">,
  { config: LabDeskConfig; label: string }
> = {
  analysis: { config: ANALYSIS_DESK, label: "Analysis desk" },
  dca: { config: DCA_DESK, label: "DCA desk" },
  tax: { config: TAX_DESK, label: "Tax desk" },
};

function DeskSwitch({ active }: { active: InvestmentsTab }) {
  const { user } = useAuth();
  const [params, setSearchParams] = useSearchParams();
  if (!isLabSession(user)) return null;

  if (active === "holdings") {
    const desk = resolveHoldingsDesk(user, params);
    return (
      <LabDeskSwitch
        desk={desk}
        embedded
        label="Holdings desk"
        onSelectDesk={(next) => {
          setSearchParams(mergeHoldingsDeskParam(params, next), { replace: true });
          savePersistedDesk(next);
        }}
      />
    );
  }

  const { config, label } = SURFACE[active];
  const desk = resolveLabDesk(user, params, config);
  return (
    <LabDeskSwitch
      desk={desk}
      embedded
      label={label}
      onSelectDesk={(next: LabDesk) => {
        setSearchParams(mergeLabDeskParam(params, next), { replace: true });
        saveLabDesk(next, config);
      }}
    />
  );
}

/** Lab next chrome: pills + desk switch, no title block. Classic Shell stays untouched. */
export function InvestmentsNextChrome({
  active,
  children,
}: {
  active: InvestmentsTab;
  children: ReactNode;
}) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="-mt-3">
          <InvestmentsSubNav active={active} />
        </div>
        <DeskSwitch active={active} />
      </div>
      {children}
    </div>
  );
}
