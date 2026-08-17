import { lazy, Suspense } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { isLabSession } from "../auth/isLabSession";
import {
  SETTINGS_DESK,
  mergeDeskParam,
  resolveLabDesk,
  saveLabDesk,
  type LabDesk,
} from "../auth/labDesk";
import { LabDeskSwitch } from "../components/LabDeskSwitch";
import { PageLoader } from "../components/Spinner";
import { SettingsPage } from "./SettingsPage";

const SettingsPageNext = lazy(() =>
  import("./SettingsPageNext").then((m) => ({
    default: m.SettingsPageNext,
  })),
);

export function SettingsPageGate() {
  const { user } = useAuth();
  const [params, setSearchParams] = useSearchParams();
  const desk = resolveLabDesk(user, params, SETTINGS_DESK);

  function onSelectDesk(next: LabDesk) {
    setSearchParams(mergeDeskParam(params, next), { replace: true });
    saveLabDesk(next, SETTINGS_DESK);
  }

  return (
    <div data-settings-desk={desk}>
      {isLabSession(user) && desk === "classic" ? (
        <LabDeskSwitch desk={desk} onSelectDesk={onSelectDesk} label="Settings desk" />
      ) : null}
      {desk === "next" ? (
        <Suspense fallback={<PageLoader label="Loading settings…" />}>
          <SettingsPageNext />
        </Suspense>
      ) : (
        <SettingsPage />
      )}
    </div>
  );
}
