import { useEffect, useState } from "react";
import { Spinner } from "./Spinner";
import { cn } from "../lib/cn";

export function WorkingBanner({
  title,
  detail,
  className,
}: {
  title: string;
  detail?: string;
  className?: string;
}) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    setElapsed(0);
    const t0 = Date.now();
    const id = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - t0) / 1000)),
      500,
    );
    return () => window.clearInterval(id);
  }, [title]);

  return (
    <div
      className={cn(
        "rounded-xl border border-brand/40 bg-brand/10 px-3 py-3",
        className,
      )}
      aria-live="polite"
      aria-busy
    >
      <div className="flex items-start gap-2">
        <Spinner className="mt-0.5 h-4 w-4 shrink-0 border-t-brand" />
        <div className="min-w-0">
          <p className="text-xs font-semibold text-ink">{title}</p>
          <p className="mt-0.5 text-[11px] text-ink-muted">
            {elapsed ? `${elapsed}s elapsed · ` : ""}
            {detail ||
              "This usually takes 15–45 seconds. The spinner means the app is still working."}
          </p>
        </div>
      </div>
      <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10">
        <div className="bar-indet h-full w-1/3 rounded-full bg-brand" />
      </div>
    </div>
  );
}
