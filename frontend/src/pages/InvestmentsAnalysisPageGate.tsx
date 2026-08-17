import { lazy, Suspense } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { isLabSession } from "../auth/isLabSession";
import {
  ANALYSIS_DESK,
  mergeDeskParam,
  resolveLabDesk,
  saveLabDesk,
  type LabDesk,
} from "../auth/labDesk";
import { LabDeskSwitch } from "../components/LabDeskSwitch";
import { PageLoader } from "../components/Spinner";
import { InvestmentsAnalysisPage } from "./InvestmentsAnalysisPage";

const InvestmentsAnalysisPageNext = lazy(() =>
  import("./InvestmentsAnalysisPageNext").then((m) => ({
    default: m.InvestmentsAnalysisPageNext,
  })),
);

export function InvestmentsAnalysisPageGate() {
  const { user } = useAuth();
  const [params, setSearchParams] = useSearchParams();
  const desk = resolveLabDesk(user, params, ANALYSIS_DESK);

  function onSelectDesk(next: LabDesk) {
    setSearchParams(mergeDeskParam(params, next), { replace: true });
    saveLabDesk(next, ANALYSIS_DESK);
  }

  return (
    <>
      {isLabSession(user) ? (
        <LabDeskSwitch desk={desk} onSelectDesk={onSelectDesk} label="Analysis desk" />
      ) : null}
      {desk === "next" ? (
        <Suspense fallback={<PageLoader label="Loading analysis…" />}>
          <InvestmentsAnalysisPageNext />
        </Suspense>
      ) : (
        <InvestmentsAnalysisPage />
      )}
    </>
  );
}
