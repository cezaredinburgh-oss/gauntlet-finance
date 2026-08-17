import { lazy, Suspense } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { isLabSession } from "../auth/isLabSession";
import {
  HOME_DESK,
  mergeDeskParam,
  resolveLabDesk,
  saveLabDesk,
  type LabDesk,
} from "../auth/labDesk";
import { LabDeskSwitch } from "../components/LabDeskSwitch";
import { PageLoader } from "../components/Spinner";
import { DashboardPage } from "./DashboardPage";

const DashboardPageNext = lazy(() =>
  import("./DashboardPageNext").then((m) => ({
    default: m.DashboardPageNext,
  })),
);

export function DashboardPageGate() {
  const { user } = useAuth();
  const [params, setSearchParams] = useSearchParams();
  const desk = resolveLabDesk(user, params, HOME_DESK);

  function onSelectDesk(next: LabDesk) {
    setSearchParams(mergeDeskParam(params, next), { replace: true });
    saveLabDesk(next, HOME_DESK);
  }

  return (
    <div data-home-desk={desk}>
      {isLabSession(user) && desk === "classic" ? (
        <LabDeskSwitch desk={desk} onSelectDesk={onSelectDesk} label="Home desk" />
      ) : null}
      {desk === "next" ? (
        <Suspense fallback={<PageLoader label="Loading home…" />}>
          <DashboardPageNext />
        </Suspense>
      ) : (
        <DashboardPage />
      )}
    </div>
  );
}
