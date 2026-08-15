import { useLocation } from "react-router-dom";
import { GrokPlusStatus } from "./GrokPlusStatus";

/** Floats on every New ET route except Categorize, where status lives in the Grok+ panel. */
export function FloatingMatchChip() {
  const location = useLocation();
  if (location.pathname === "/new-et/categorize") return null;

  return (
    <aside
      className="pointer-events-auto fixed z-50 w-[min(22rem,calc(100vw-1.5rem))] bottom-20 right-3 lg:bottom-6 lg:right-4"
      aria-live="polite"
    >
      <GrokPlusStatus variant="float" />
    </aside>
  );
}
