import { lazy, Suspense } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { isLabSession } from "../auth/isLabSession";
import {
  UPLOAD_DESK,
  mergeDeskParam,
  resolveLabDesk,
  saveLabDesk,
  type LabDesk,
} from "../auth/labDesk";
import { LabDeskSwitch } from "../components/LabDeskSwitch";
import { PageLoader } from "../components/Spinner";
import { UploadPage } from "./UploadPage";

const UploadPageNext = lazy(() =>
  import("./UploadPageNext").then((m) => ({
    default: m.UploadPageNext,
  })),
);

export function UploadPageGate() {
  const { user } = useAuth();
  const [params, setSearchParams] = useSearchParams();
  const desk = resolveLabDesk(user, params, UPLOAD_DESK);

  function onSelectDesk(next: LabDesk) {
    setSearchParams(mergeDeskParam(params, next), { replace: true });
    saveLabDesk(next, UPLOAD_DESK);
  }

  return (
    <div data-upload-desk={desk}>
      {isLabSession(user) && desk === "classic" ? (
        <LabDeskSwitch desk={desk} onSelectDesk={onSelectDesk} label="Upload desk" />
      ) : null}
      {desk === "next" ? (
        <Suspense fallback={<PageLoader label="Loading upload…" />}>
          <UploadPageNext />
        </Suspense>
      ) : (
        <UploadPage />
      )}
    </div>
  );
}
