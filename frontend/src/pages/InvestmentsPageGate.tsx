import { lazy, Suspense } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { isLabSession } from "../auth/isLabSession";
import { PageLoader } from "../components/Spinner";
import { HoldingsDeskSwitch } from "../features/investments/next/HoldingsDeskSwitch";
import {
  mergeDeskParam,
  resolveHoldingsDesk,
  savePersistedDesk,
  type HoldingsDesk,
} from "../features/investments/next/holdingsDesk";
import { InvestmentsPage } from "./InvestmentsPage";

const InvestmentsPageNext = lazy(() =>
  import("./InvestmentsPageNext").then((m) => ({ default: m.InvestmentsPageNext })),
);

export function InvestmentsPageGate() {
  const { user } = useAuth();
  const [params, setSearchParams] = useSearchParams();
  const desk = resolveHoldingsDesk(user, params);

  function onSelectDesk(next: HoldingsDesk) {
    const q = mergeDeskParam(params, next);
    setSearchParams(q, { replace: true });
    savePersistedDesk(next);
  }

  return (
    <>
      {isLabSession(user) && desk === "classic" ? (
        <HoldingsDeskSwitch desk={desk} onSelectDesk={onSelectDesk} />
      ) : null}
      {desk === "next" ? (
        <Suspense fallback={<PageLoader label="Loading investments…" />}>
          <InvestmentsPageNext />
        </Suspense>
      ) : (
        <InvestmentsPage />
      )}
    </>
  );
}
