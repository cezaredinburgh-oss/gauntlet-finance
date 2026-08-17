import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { isLabSession } from "../auth/isLabSession";
import {
  mergeDeskParam,
  resolveLabDesk,
  saveLabDesk,
  type LabDesk,
  type LabDeskConfig,
} from "../auth/labDesk";
import { LabDeskSwitch } from "../components/LabDeskSwitch";

export function LabNextChrome({
  config,
  label,
  eyebrow,
  children,
}: {
  config: LabDeskConfig;
  label: string;
  eyebrow?: ReactNode;
  children: ReactNode;
}) {
  const { user } = useAuth();
  const [params, setSearchParams] = useSearchParams();
  const desk = resolveLabDesk(user, params, config);

  function onSelectDesk(next: LabDesk) {
    setSearchParams(mergeDeskParam(params, next), { replace: true });
    saveLabDesk(next, config);
  }

  return (
    <div className="space-y-4">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <div className="min-w-0 text-[11px] text-ink-faint">{eyebrow}</div>
        {isLabSession(user) ? (
          <LabDeskSwitch
            desk={desk}
            onSelectDesk={onSelectDesk}
            label={label}
            embedded
          />
        ) : null}
      </div>
      {children}
    </div>
  );
}
