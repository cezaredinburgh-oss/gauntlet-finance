import { lazy, Suspense } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { isLabSession } from "../auth/isLabSession";
import {
  CATEGORIZE_DESK,
  mergeDeskParam,
  resolveLabDesk,
  saveLabDesk,
  type LabDesk,
} from "../auth/labDesk";
import { LabDeskSwitch } from "../components/LabDeskSwitch";
import { PageLoader } from "../components/Spinner";
import { NewEtCategorizePage } from "./NewEtCategorizePage";

const NewEtCategorizePageNext = lazy(() =>
  import("./NewEtCategorizePageNext").then((m) => ({
    default: m.NewEtCategorizePageNext,
  })),
);

export function NewEtCategorizePageGate() {
  const { user } = useAuth();
  const [params, setSearchParams] = useSearchParams();
  const desk = resolveLabDesk(user, params, CATEGORIZE_DESK);

  function onSelectDesk(next: LabDesk) {
    setSearchParams(mergeDeskParam(params, next), { replace: true });
    saveLabDesk(next, CATEGORIZE_DESK);
  }

  return (
    <div data-categorize-desk={desk}>
      {isLabSession(user) && desk === "classic" ? (
        <LabDeskSwitch desk={desk} onSelectDesk={onSelectDesk} label="Categorize desk" />
      ) : null}
      {desk === "next" ? (
        <Suspense fallback={<PageLoader label="Loading categorize…" />}>
          <NewEtCategorizePageNext />
        </Suspense>
      ) : (
        <NewEtCategorizePage />
      )}
    </div>
  );
}
