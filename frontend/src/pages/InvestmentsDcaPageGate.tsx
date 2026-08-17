import { lazy, Suspense } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { isLabSession } from "../auth/isLabSession";
import {
  DCA_DESK,
  mergeDeskParam,
  resolveLabDesk,
  saveLabDesk,
  type LabDesk,
} from "../auth/labDesk";
import { LabDeskSwitch } from "../components/LabDeskSwitch";
import { PageLoader } from "../components/Spinner";
import { InvestmentsDcaPage } from "./InvestmentsDcaPage";

const InvestmentsDcaPageNext = lazy(() =>
  import("./InvestmentsDcaPageNext").then((m) => ({
    default: m.InvestmentsDcaPageNext,
  })),
);

export function InvestmentsDcaPageGate() {
  const { user } = useAuth();
  const [params, setSearchParams] = useSearchParams();
  const desk = resolveLabDesk(user, params, DCA_DESK);

  function onSelectDesk(next: LabDesk) {
    setSearchParams(mergeDeskParam(params, next), { replace: true });
    saveLabDesk(next, DCA_DESK);
  }

  return (
    <>
      {isLabSession(user) && desk === "classic" ? (
        <LabDeskSwitch desk={desk} onSelectDesk={onSelectDesk} label="DCA desk" />
      ) : null}
      {desk === "next" ? (
        <Suspense fallback={<PageLoader label="Loading DCA board…" />}>
          <InvestmentsDcaPageNext />
        </Suspense>
      ) : (
        <InvestmentsDcaPage />
      )}
    </>
  );
}
