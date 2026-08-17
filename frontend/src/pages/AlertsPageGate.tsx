import { lazy, Suspense } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { isLabSession } from "../auth/isLabSession";
import {
  ALERTS_DESK,
  mergeDeskParam,
  resolveLabDesk,
  saveLabDesk,
  type LabDesk,
} from "../auth/labDesk";
import { LabDeskSwitch } from "../components/LabDeskSwitch";
import { PageLoader } from "../components/Spinner";
import { AlertsPage } from "./AlertsPage";

const AlertsPageNext = lazy(() =>
  import("./AlertsPageNext").then((m) => ({
    default: m.AlertsPageNext,
  })),
);

export function AlertsPageGate() {
  const { user } = useAuth();
  const [params, setSearchParams] = useSearchParams();
  const desk = resolveLabDesk(user, params, ALERTS_DESK);

  function onSelectDesk(next: LabDesk) {
    setSearchParams(mergeDeskParam(params, next), { replace: true });
    saveLabDesk(next, ALERTS_DESK);
  }

  return (
    <div data-alerts-desk={desk}>
      {isLabSession(user) && desk === "classic" ? (
        <LabDeskSwitch desk={desk} onSelectDesk={onSelectDesk} label="Alerts desk" />
      ) : null}
      {desk === "next" ? (
        <Suspense fallback={<PageLoader label="Loading alerts…" />}>
          <AlertsPageNext />
        </Suspense>
      ) : (
        <AlertsPage />
      )}
    </div>
  );
}
