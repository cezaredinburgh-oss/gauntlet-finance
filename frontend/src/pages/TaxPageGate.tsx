import { lazy, Suspense } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { isLabSession } from "../auth/isLabSession";
import {
  TAX_DESK,
  mergeDeskParam,
  resolveLabDesk,
  saveLabDesk,
  type LabDesk,
} from "../auth/labDesk";
import { LabDeskSwitch } from "../components/LabDeskSwitch";
import { PageLoader } from "../components/Spinner";
import { TaxPage } from "./TaxPage";

const TaxPageNext = lazy(() =>
  import("./TaxPageNext").then((m) => ({
    default: m.TaxPageNext,
  })),
);

export function TaxPageGate() {
  const { user } = useAuth();
  const [params, setSearchParams] = useSearchParams();
  const desk = resolveLabDesk(user, params, TAX_DESK);

  function onSelectDesk(next: LabDesk) {
    setSearchParams(mergeDeskParam(params, next), { replace: true });
    saveLabDesk(next, TAX_DESK);
  }

  return (
    <>
      {isLabSession(user) ? (
        <LabDeskSwitch desk={desk} onSelectDesk={onSelectDesk} label="Tax desk" />
      ) : null}
      {desk === "next" ? (
        <Suspense fallback={<PageLoader label="Loading tax report…" />}>
          <TaxPageNext />
        </Suspense>
      ) : (
        <TaxPage />
      )}
    </>
  );
}
