import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { cn } from "../lib/cn";

type Props = {
  children: React.ReactNode;
  content: React.ReactNode;
  className?: string;
  panelClassName?: string;
};

const CLOSE_DELAY_MS = 220;
const EDGE_PAD = 8;

type Placement = {
  /** Prefer below; flip above when insufficient space */
  placeAbove: boolean;
  /** Horizontal shift so panel stays in viewport */
  shiftX: number;
};

/**
 * Desktop: show panel on hover (with delay so cursor can enter the panel).
 * Mobile/touch: toggle on click.
 *
 * Flips above the trigger when near the bottom of the viewport (tablet tax runway).
 * Horizontal clamp near left/right edges.
 *
 * Important: no dead gap between trigger and panel — leave closes only after
 * a short delay so the user can move the pointer onto the popup.
 */
export function HoverPanel({ children, content, className, panelClassName }: Props) {
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<Placement>({
    placeAbove: false,
    shiftX: 0,
  });
  const id = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
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

  useLayoutEffect(() => {
    if (!open) return;

    function measure() {
      const root = rootRef.current;
      const panel = panelRef.current;
      if (!root || !panel) return;

      const trigger = root.getBoundingClientRect();
      // Temporarily place below to measure natural size
      const panelRect = panel.getBoundingClientRect();
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      const spaceBelow = vh - trigger.bottom - EDGE_PAD;
      const spaceAbove = trigger.top - EDGE_PAD;
      const need = panelRect.height || 200;
      const placeAbove = spaceBelow < need && spaceAbove > spaceBelow;

      // Horizontal: prefer left-aligned to trigger; clamp into viewport
      let shiftX = 0;
      const left = trigger.left;
      const width = panelRect.width || 272;
      if (left + width + EDGE_PAD > vw) {
        shiftX = Math.min(0, vw - EDGE_PAD - width - left);
      }
      if (left + shiftX < EDGE_PAD) {
        shiftX = EDGE_PAD - left;
      }

      setPlacement({ placeAbove, shiftX });
    }

    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [open, content]);

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
          ref={panelRef}
          id={id}
          role="tooltip"
          className={cn(
            "absolute z-50 w-max max-w-[20rem]",
            placement.placeAbove
              ? "bottom-full left-0 pb-2"
              : "left-0 top-full pt-2",
            panelClassName,
          )}
          style={{
            transform:
              placement.shiftX !== 0
                ? `translateX(${placement.shiftX}px)`
                : undefined,
          }}
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
