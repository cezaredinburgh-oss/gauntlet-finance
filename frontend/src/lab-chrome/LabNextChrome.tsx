import type { ReactNode } from "react";
import type { LabDeskConfig } from "../auth/labDesk";

export function LabNextChrome({
  eyebrow,
  children,
}: {
  config: LabDeskConfig;
  label: string;
  eyebrow?: ReactNode;
  children: ReactNode;
}) {
  if (!eyebrow) return <>{children}</>;
  return (
    <div className="space-y-4">
      <div className="min-w-0 text-[11px] text-ink-faint">{eyebrow}</div>
      {children}
    </div>
  );
}
