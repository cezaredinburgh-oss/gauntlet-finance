import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/** min-w-0 card; scroll-mt clears Layout’s sticky top bar on hash jump. */
export function SettingsSection({
  id,
  title,
  children,
  danger,
}: {
  id: string;
  title: string;
  children: ReactNode;
  danger?: boolean;
}) {
  return (
    <section
      id={id}
      className={cn(
        "card min-w-0 space-y-4 p-5 scroll-mt-20 lg:scroll-mt-4",
        danger && "border border-danger/25",
      )}
    >
      <h2
        className={cn(
          "text-pretty break-words text-sm font-semibold",
          danger && "text-danger",
        )}
      >
        {title}
      </h2>
      {children}
    </section>
  );
}
