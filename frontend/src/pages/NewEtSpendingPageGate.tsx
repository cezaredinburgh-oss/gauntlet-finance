import { lazy, Suspense } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { isLabSession } from "../auth/isLabSession";
import {
  SPENDING_DESK,
  mergeDeskParam,
  resolveLabDesk,
  saveLabDesk,
  type LabDesk,
} from "../auth/labDesk";
import { LabDeskSwitch } from "../components/LabDeskSwitch";
import { PageLoader } from "../components/Spinner";
import { NewEtSpendingPage } from "./NewEtSpendingPage";

const NewEtSpendingPageNext = lazy(() =>
  import("./NewEtSpendingPageNext").then((m) => ({
    default: m.NewEtSpendingPageNext,
  })),
);

export function NewEtSpendingPageGate() {
  const { user } = useAuth();
  const [params, setSearchParams] = useSearchParams();
  const desk = resolveLabDesk(user, params, SPENDING_DESK);

  function onSelectDesk(next: LabDesk) {
    setSearchParams(mergeDeskParam(params, next), { replace: true });
    saveLabDesk(next, SPENDING_DESK);
  }

  return (
    <div data-spending-desk={desk}>
      {isLabSession(user) && desk === "classic" ? (
        <LabDeskSwitch desk={desk} onSelectDesk={onSelectDesk} label="Spending desk" />
      ) : null}
      {desk === "next" ? (
        <Suspense fallback={<PageLoader label="Loading spending…" />}>
          <NewEtSpendingPageNext />
        </Suspense>
      ) : (
        <NewEtSpendingPage />
      )}
    </div>
  );
}
