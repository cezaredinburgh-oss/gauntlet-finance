import { useEffect, useId, useRef, useState } from "react";
import { cn } from "../lib/cn";

type Props = {
  children: React.ReactNode;
  content: React.ReactNode;
  className?: string;
  panelClassName?: string;
};

const CLOSE_DELAY_MS = 220;

/**
 * Desktop: show panel on hover (with delay so cursor can enter the panel).
 * Mobile/touch: toggle on click.
 *
 * Important: no dead gap between trigger and panel — leave closes only after
 * a short delay so the user can move the pointer onto the popup.
 */
export function HoverPanel({ children, content, className, panelClassName }: Props) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function clearCloseTimer() {
    if (closeTimer.current != null) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }

  function openNow() {
    clearCloseTimer();
    setOpen(true);
  }

  function scheduleClose() {
    clearCloseTimer();
    closeTimer.current = setTimeout(() => setOpen(false), CLOSE_DELAY_MS);
  }

  useEffect(() => {
    return () => clearCloseTimer();
  }, []);

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) {
        clearCloseTimer();
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div
      ref={rootRef}
      className={cn("relative", className)}
      onMouseEnter={openNow}
      onMouseLeave={scheduleClose}
    >
      <button
        type="button"
        className="w-full cursor-default text-left"
        aria-describedby={open ? id : undefined}
        onClick={() => {
          clearCloseTimer();
          setOpen((v) => !v);
        }}
      >
        {children}
      </button>
      {open && (
        <div
          id={id}
          role="tooltip"
          className={cn(
            // pt-2 bridges the visual gap: hit area includes padding so leave
            // does not fire while moving from trigger into the panel body.
            "absolute left-0 top-full z-50 w-max max-w-[20rem] pt-2",
            panelClassName,
          )}
          onMouseEnter={openNow}
          onMouseLeave={scheduleClose}
        >
          <div
            className={cn(
              "max-h-80 min-w-[17rem] overflow-y-auto rounded-xl border border-slate-500/25 bg-slate-900/95 p-3.5 text-sm shadow-xl backdrop-blur-md",
            )}
          >
            {content}
          </div>
        </div>
      )}
    </div>
  );
}
